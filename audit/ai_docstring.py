"""Contour line generation from digital elevation models (DEMs) for GeoDesk.

This module provides the building blocks used by GeoDesk's terrain tools to
turn a raster elevation grid into vector contour lines:

* :class:`ElevationGrid` - an immutable, validated DEM held in memory.
* :class:`ContourLine` - a single polyline at one elevation.
* :class:`ContourLayer` - a collection of contour lines derived from a DEM,
  exportable as GeoJSON.
* :class:`ContourGenerator` - traces contours at a regular interval using a
  marching-squares style approach with linear interpolation along cell edges.

Example:
    >>> from geodesk.terrain import ElevationGrid, ContourGenerator
    >>> grid = ElevationGrid.from_rows(
    ...     "layer_dem_01",
    ...     [[100, 110, 120], [105, 115, 125], [110, 120, 130]],
    ...     cell_size_m=30.0,
    ...     origin=(500000.0, 5200000.0),
    ... )
    >>> layer = ContourGenerator(interval_m=10.0).generate(grid)
    >>> layer.elevations()
    [110.0, 120.0]

See Also:
    :mod:`geodesk.errors` for the exceptions raised by this module.
"""
from __future__ import annotations
import math
from dataclasses import dataclass, field
from geodesk.errors import DEMTooLargeError, InvalidIntervalError, NoDataCoverageError
__all__ = ['ElevationGrid', 'ContourLine', 'ContourLayer', 'ContourGenerator']
Point = tuple[float, float]
_BYTES_PER_CELL = 4

@dataclass(frozen=True)
class ElevationGrid:
    """An immutable regular grid of elevation values (a DEM).

    Rows run from north to south and columns from west to east. The
    ``origin`` is the north-west corner of the grid in the grid's CRS.

    Args:
        layer_id: Identifier of the DEM layer in the GeoDesk project.
        elevations: Elevation values in metres as a tuple of row tuples. Use
            :meth:`from_rows` to build one from ordinary lists with validation.
        cell_size_m: Width and height of a cell, in metres.
        origin: ``(x, y)`` coordinates of the north-west corner of the grid.
        crs: Coordinate reference system code of the grid.
        nodata: Sentinel value marking missing data, or ``None`` if only NaN
            values mark missing cells.

    Returns:
        ElevationGrid: A new frozen grid instance.

    Raises:
        dataclasses.FrozenInstanceError: If an attribute is assigned after
            construction.

    Example:
        >>> grid = ElevationGrid.from_rows(
        ...     "layer_dem_01",
        ...     [[100, 110], [105, 115]],
        ...     cell_size_m=30.0,
        ...     origin=(500000.0, 5200000.0),
        ... )
        >>> grid.shape
        (2, 2)

    See Also:
        :class:`ContourGenerator` for turning a grid into contour lines.
    """
    layer_id: str
    elevations: tuple[tuple[float, ...], ...]
    cell_size_m: float
    origin: Point
    crs: str = 'EPSG:32648'
    nodata: float | None = None

    @classmethod
    def from_rows(cls, layer_id: str, rows: list[list[float]], *, cell_size_m: float, origin: Point, crs: str='EPSG:32648', nodata: float | None=None) -> ElevationGrid:
        """Build a validated, immutable grid from nested lists of elevations.

        Args:
            layer_id: Identifier of the DEM layer in the GeoDesk project.
            rows: Elevation values in metres, one inner list per grid row,
                ordered north to south. Needs at least 2 rows and 2 columns.
            cell_size_m: Width and height of a cell, in metres. Must be
                positive.
            origin: ``(x, y)`` coordinates of the north-west corner.
            crs: Coordinate reference system code of the grid.
            nodata: Sentinel value that marks missing cells, or ``None``.

        Returns:
            ElevationGrid: A frozen grid whose values are converted to floats.

        Raises:
            ValueError: If the grid is smaller than 2 x 2 cells, the rows have
                differing lengths, or ``cell_size_m`` is not positive.

        Example:
            >>> grid = ElevationGrid.from_rows(
            ...     "layer_dem_01",
            ...     [[100, 110, 120], [105, 115, 125], [110, 120, 130]],
            ...     cell_size_m=30.0,
            ...     origin=(500000.0, 5200000.0),
            ...     nodata=-9999.0,
            ... )
            >>> grid.shape
            (3, 3)

        See Also:
            :attr:`shape` for the dimensions of the resulting grid.
        """
        if len(rows) < 2 or len(rows[0]) < 2:
            raise ValueError('a DEM needs at least 2 x 2 cells to trace contours')
        if any((len(row) != len(rows[0]) for row in rows)):
            raise ValueError('every DEM row must have the same number of cells')
        if cell_size_m <= 0:
            raise ValueError(f'cell_size_m must be positive, got {cell_size_m}')
        frozen_rows = tuple((tuple((float(value) for value in row)) for row in rows))
        return cls(layer_id, frozen_rows, float(cell_size_m), origin, crs, nodata)

    @property
    def shape(self) -> tuple[int, int]:
        """tuple[int, int]: The grid dimensions as ``(row_count, column_count)``.

        Args:
            None: This is a read-only property.

        Returns:
            tuple[int, int]: Number of rows and number of columns.

        Raises:
            IndexError: If the grid was constructed directly with no rows.

        Example:
            >>> grid = ElevationGrid.from_rows(
            ...     "layer_dem_01", [[1, 2, 3], [4, 5, 6]],
            ...     cell_size_m=10.0, origin=(0.0, 0.0),
            ... )
            >>> grid.shape
            (2, 3)

        See Also:
            :attr:`size_mb` for the memory footprint derived from the shape.
        """
        return (len(self.elevations), len(self.elevations[0]))

    @property
    def size_mb(self) -> float:
        """float: Estimated in-memory size of the grid, in megabytes.

        The estimate assumes 4 bytes per cell and 1,000,000 bytes per
        megabyte.

        Args:
            None: This is a read-only property.

        Returns:
            float: Approximate size of the DEM in megabytes.

        Raises:
            IndexError: If the grid was constructed directly with no rows.

        Example:
            >>> grid = ElevationGrid.from_rows(
            ...     "layer_dem_01", [[0, 0], [0, 0]],
            ...     cell_size_m=10.0, origin=(0.0, 0.0),
            ... )
            >>> grid.size_mb
            1.6e-05

        See Also:
            :class:`ContourGenerator`, whose ``max_size_mb`` limit is checked
            against this value.
        """
        row_count, column_count = self.shape
        return row_count * column_count * _BYTES_PER_CELL / 1000000

    def nodata_ratio(self) -> float:
        """Compute the fraction of cells that hold no data.

        A cell counts as missing if it is NaN or equals the ``nodata``
        sentinel.

        Args:
            None.

        Returns:
            float: Ratio of missing cells between 0.0 and 1.0.

        Raises:
            ZeroDivisionError: If the grid contains no cells at all (only
                possible when built without :meth:`from_rows`).

        Example:
            >>> grid = ElevationGrid.from_rows(
            ...     "layer_dem_01", [[1, -9999], [3, 4]],
            ...     cell_size_m=10.0, origin=(0.0, 0.0), nodata=-9999.0,
            ... )
            >>> grid.nodata_ratio()
            0.25

        See Also:
            :meth:`valid_range` for the range of the valid cells.
        """
        cells = [value for row in self.elevations for value in row]
        missing = sum((1 for value in cells if self._is_nodata(value)))
        return missing / len(cells)

    def valid_range(self) -> tuple[float, float]:
        """Return the lowest and highest valid elevations in the grid.

        Args:
            None.

        Returns:
            tuple[float, float]: ``(minimum, maximum)`` of all cells that are
            not NoData.

        Raises:
            NoDataCoverageError: If every cell in the grid is NoData.

        Example:
            >>> grid = ElevationGrid.from_rows(
            ...     "layer_dem_01", [[100, 110], [105, 130]],
            ...     cell_size_m=30.0, origin=(0.0, 0.0),
            ... )
            >>> grid.valid_range()
            (100.0, 130.0)

        See Also:
            :meth:`ContourGenerator.levels` which uses this range to choose
            contour elevations.
        """
        valid = [value for row in self.elevations for value in row if not self._is_nodata(value)]
        if not valid:
            raise NoDataCoverageError(f'DEM {self.layer_id} contains only NoData cells.')
        return (min(valid), max(valid))

    def _is_nodata(self, value: float) -> bool:
        return math.isnan(value) or (self.nodata is not None and value == self.nodata)

@dataclass(frozen=True)
class ContourLine:
    """A single contour polyline at one elevation.

    Args:
        elevation_m: Elevation of the contour, in metres.
        points: Ordered ``(x, y)`` vertices of the line in the layer CRS.

    Returns:
        ContourLine: A new frozen contour line.

    Raises:
        dataclasses.FrozenInstanceError: If an attribute is assigned after
            construction.

    Example:
        >>> line = ContourLine(110.0, ((0.0, 0.0), (3.0, 4.0)))
        >>> line.length_m
        5.0

    See Also:
        :class:`ContourLayer` which groups lines produced from one DEM.
    """
    elevation_m: float
    points: tuple[Point, ...]

    @property
    def length_m(self) -> float:
        """float: Planar length of the line in metres, rounded to 2 decimals.

        Args:
            None: This is a read-only property.

        Returns:
            float: Sum of straight segment lengths between consecutive points.
            A line with fewer than two points has length 0.

        Raises:
            None.

        Example:
            >>> ContourLine(100.0, ((0.0, 0.0), (3.0, 4.0), (3.0, 10.0))).length_m
            11.0

        See Also:
            :meth:`ContourLayer.to_geojson` to export the geometry.
        """
        segment_lengths = (math.dist(start, end) for start, end in zip(self.points, self.points[1:]))
        return round(sum(segment_lengths), 2)

@dataclass(frozen=True)
class ContourLayer:
    """A set of contour lines derived from a single DEM layer.

    Args:
        layer_id: Identifier of this contour layer.
        source_layer_id: Identifier of the DEM the contours came from.
        interval_m: Vertical spacing between contour levels, in metres.
        crs: Coordinate reference system code of the line coordinates.
        lines: The contour lines in the layer.

    Returns:
        ContourLayer: A new frozen contour layer.

    Raises:
        dataclasses.FrozenInstanceError: If an attribute is assigned after
            construction.

    Example:
        >>> layer = ContourLayer(
        ...     "layer_contour_01", "layer_dem_01", 10.0, "EPSG:32648",
        ...     (ContourLine(110.0, ((0.0, 0.0), (30.0, 0.0))),),
        ... )
        >>> layer.elevations()
        [110.0]

    See Also:
        :class:`ContourGenerator` which creates layers from an
        :class:`ElevationGrid`.
    """
    layer_id: str
    source_layer_id: str
    interval_m: float
    crs: str
    lines: tuple[ContourLine, ...] = field(default_factory=tuple)

    def elevations(self) -> list[float]:
        """List the distinct contour elevations present in the layer.

        Args:
            None.

        Returns:
            list[float]: Unique elevations in metres, sorted ascending.

        Raises:
            None.

        Example:
            >>> layer = ContourLayer(
            ...     "layer_contour_01", "layer_dem_01", 10.0, "EPSG:32648",
            ...     (ContourLine(120.0, ((0.0, 0.0), (1.0, 0.0))),
            ...      ContourLine(110.0, ((0.0, 1.0), (1.0, 1.0))),
            ...      ContourLine(110.0, ((0.0, 2.0), (1.0, 2.0)))),
            ... )
            >>> layer.elevations()
            [110.0, 120.0]

        See Also:
            :meth:`ContourGenerator.levels` for the levels planned from a DEM.
        """
        return sorted({line.elevation_m for line in self.lines})

    def to_geojson(self) -> dict:
        """Convert the layer to a GeoJSON ``FeatureCollection``.

        Each contour line becomes a ``LineString`` feature with an
        ``elevation_m`` property. The collection ``name`` is the layer id.
        Coordinates are left in the layer CRS.

        Args:
            None.

        Returns:
            dict: A GeoJSON-compatible dictionary ready for ``json.dumps``.

        Raises:
            None.

        Example:
            >>> layer = ContourLayer(
            ...     "layer_contour_01", "layer_dem_01", 10.0, "EPSG:32648",
            ...     (ContourLine(110.0, ((0.0, 0.0), (30.0, 0.0))),),
            ... )
            >>> data = layer.to_geojson()
            >>> data["features"][0]["properties"]
            {'elevation_m': 110.0}

        See Also:
            :attr:`ContourLine.length_m` for measuring individual features.
        """
        features = [{'type': 'Feature', 'properties': {'elevation_m': line.elevation_m}, 'geometry': {'type': 'LineString', 'coordinates': [list(point) for point in line.points]}} for line in self.lines]
        return {'type': 'FeatureCollection', 'name': self.layer_id, 'features': features}

class ContourGenerator:
    """Generate contour lines from an :class:`ElevationGrid`.

    Contours are traced cell by cell, interpolating linearly along cell edges
    where the surface crosses a contour level. Cells touching NoData values
    are skipped.

    Args:
        interval_m: Vertical spacing between contours, in metres. Must be
            finite and at least :attr:`MIN_INTERVAL_M`.
        max_size_mb: Largest DEM, in megabytes, that will be processed.
        max_nodata_ratio: Largest allowed fraction of NoData cells (0 to 1).

    Returns:
        ContourGenerator: A configured generator.

    Raises:
        InvalidIntervalError: If ``interval_m`` is not finite or is below
            :attr:`MIN_INTERVAL_M`.

    Example:
        >>> generator = ContourGenerator(interval_m=10.0, max_size_mb=100.0)
        >>> generator.interval_m
        10.0

    See Also:
        :class:`ElevationGrid` for the input and :class:`ContourLayer` for the
        output.
    """
    MIN_INTERVAL_M = 0.5

    def __init__(self, interval_m: float, *, max_size_mb: float=200.0, max_nodata_ratio: float=0.2) -> None:
        self.interval_m = self._validate_interval(interval_m)
        self.max_size_mb = max_size_mb
        self.max_nodata_ratio = max_nodata_ratio

    def levels(self, grid: ElevationGrid) -> list[float]:
        """Compute the contour elevations that apply to a grid.

        Levels are multiples of the interval, starting with the first multiple
        strictly above the grid's lowest valid elevation.

        Args:
            grid: The DEM whose valid elevation range determines the levels.

        Returns:
            list[float]: Contour elevations in metres, ascending. May be empty
            if the terrain is too flat for any level.

        Raises:
            NoDataCoverageError: If the grid contains only NoData cells.

        Example:
            >>> grid = ElevationGrid.from_rows(
            ...     "layer_dem_01",
            ...     [[100, 110, 120], [105, 115, 125], [110, 120, 130]],
            ...     cell_size_m=30.0, origin=(500000.0, 5200000.0),
            ... )
            >>> ContourGenerator(interval_m=10.0).levels(grid)
            [110.0, 120.0]

        See Also:
            :meth:`generate` which traces lines at each of these levels.
        """
        lowest, highest = grid.valid_range()
        first_level = math.floor(lowest / self.interval_m + 1) * self.interval_m
        level_count = max(0, math.ceil((highest - first_level) / self.interval_m))
        return [round(first_level + step * self.interval_m, 6) for step in range(level_count)]

    def generate(self, grid: ElevationGrid, *, output_layer_id: str='layer_contour_9a21') -> ContourLayer:
        """Trace contour lines for every level of a DEM.

        The DEM is first checked against the size and NoData limits.

        Args:
            grid: The DEM to contour.
            output_layer_id: Identifier to give the resulting layer.

        Returns:
            ContourLayer: A layer holding one segment line per traced contour
            piece, in the grid's CRS.

        Raises:
            DEMTooLargeError: If the grid is larger than ``max_size_mb``.
            NoDataCoverageError: If the NoData ratio exceeds
                ``max_nodata_ratio`` or the grid has no valid cells.

        Example:
            >>> grid = ElevationGrid.from_rows(
            ...     "layer_dem_01",
            ...     [[100, 110, 120], [105, 115, 125], [110, 120, 130]],
            ...     cell_size_m=30.0, origin=(500000.0, 5200000.0),
            ... )
            >>> layer = ContourGenerator(interval_m=10.0).generate(
            ...     grid, output_layer_id="layer_contour_site_a")
            >>> layer.source_layer_id
            'layer_dem_01'

        See Also:
            :meth:`ContourLayer.to_geojson` to export the result.
        """
        self._check_dem(grid)
        lines = [ContourLine(level, segment) for level in self.levels(grid) for segment in self._trace_level(grid, level)]
        return ContourLayer(output_layer_id, grid.layer_id, self.interval_m, grid.crs, tuple(lines))

    @classmethod
    def _validate_interval(cls, interval_m: float) -> float:
        if not math.isfinite(interval_m) or interval_m < cls.MIN_INTERVAL_M:
            raise InvalidIntervalError(f'interval_m must be a finite number >= {cls.MIN_INTERVAL_M} m, got {interval_m}.')
        return float(interval_m)

    def _check_dem(self, grid: ElevationGrid) -> None:
        if grid.size_mb > self.max_size_mb:
            raise DEMTooLargeError(f'DEM {grid.layer_id} is {grid.size_mb:.1f} MB; the limit is {self.max_size_mb:.0f} MB.')
        nodata_ratio = grid.nodata_ratio()
        if nodata_ratio > self.max_nodata_ratio:
            raise NoDataCoverageError(f'DEM {grid.layer_id} has {nodata_ratio:.0%} NoData cells; the limit is {self.max_nodata_ratio:.0%}.')

    def _trace_level(self, grid: ElevationGrid, level: float) -> list[tuple[Point, Point]]:
        segments = []
        row_count, column_count = grid.shape
        for row in range(row_count - 1):
            for column in range(column_count - 1):
                corners = (grid.elevations[row][column], grid.elevations[row][column + 1], grid.elevations[row + 1][column + 1], grid.elevations[row + 1][column])
                if any((grid._is_nodata(value) for value in corners)):
                    continue
                segments.extend(self._cell_segments(grid, row, column, corners, level))
        return segments

    @staticmethod
    def _cell_segments(grid, row, column, corners, level):
        north_west, north_east, south_east, south_west = corners
        x0 = grid.origin[0] + column * grid.cell_size_m
        y0 = grid.origin[1] - row * grid.cell_size_m
        size = grid.cell_size_m

        def crossing(start_value, end_value):
            return (level - start_value) / (end_value - start_value)
        edge_points = {}
        if (north_west >= level) != (north_east >= level):
            edge_points['north'] = (x0 + size * crossing(north_west, north_east), y0)
        if (north_east >= level) != (south_east >= level):
            edge_points['east'] = (x0 + size, y0 - size * crossing(north_east, south_east))
        if (south_west >= level) != (south_east >= level):
            edge_points['south'] = (x0 + size * crossing(south_west, south_east), y0 - size)
        if (north_west >= level) != (south_west >= level):
            edge_points['west'] = (x0, y0 - size * crossing(north_west, south_west))
        if len(edge_points) == 2:
            first, second = edge_points.values()
            return [(_round_point(first), _round_point(second))]
        if len(edge_points) == 4:
            return [(_round_point(edge_points['north']), _round_point(edge_points['west'])), (_round_point(edge_points['south']), _round_point(edge_points['east']))]
        return []

def _round_point(point: Point) -> Point:
    return (round(point[0], 3), round(point[1], 3))
