"""Contour line generation from DEM rasters (arc42 block B5.2, FR-09).

This module is the engine behind ``POST /terrain/contours`` in the W05 API.
Its public API is :class:`ElevationGrid` (the input DEM),
:class:`ContourGenerator` (the algorithm) and :class:`ContourLayer` /
:class:`ContourLine` (the result).

Every example in this module uses the same 3 × 3 sample of the Zaisan hill DEM
(layer ``layer_dem_44c1``, 30 m cells, UTM zone 48N) so that results can be
compared across classes::

    1350  1351  1352
    1351  1352  1353
    1352  1353  1354

Quickstart: from a GeoTIFF file to a GeoJSON contour file.
This module does not read files itself, so the DEM is loaded with ``rasterio``.
A GeoTIFF transform points at the *outer corner* of the first pixel, while
:attr:`ElevationGrid.origin` is the *centre* of that pixel, so move half a
cell inwards. Passing ``(transform.c, transform.f)`` directly shifts every
contour by half a cell (15 m for this DEM).

.. code-block:: python

    import json

    import rasterio

    from geodesk import ContourGenerator
    from geodesk.terrain import ElevationGrid

    with rasterio.open("zaisan_dem.tif") as dem_file:
        transform = dem_file.transform
        zaisan_dem = ElevationGrid.from_rows(
            "layer_dem_44c1",
            dem_file.read(1).tolist(),
            cell_size_m=transform.a,
            origin=(transform.c + transform.a / 2, transform.f + transform.e / 2),
            crs=dem_file.crs.to_string(),
            nodata=dem_file.nodata,
        )

    contour_layer = ContourGenerator(interval_m=1.0).generate(zaisan_dem)
    with open("zaisan_contours_1m.geojson", "w", encoding="utf-8") as geojson_file:
        json.dump(contour_layer.to_geojson(), geojson_file)
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

from geodesk.errors import DEMTooLargeError, InvalidIntervalError, NoDataCoverageError

__all__ = ["ElevationGrid", "ContourLine", "ContourLayer", "ContourGenerator"]

Point = tuple[float, float]

# Bytes per DEM cell when stored as float32 GeoTIFF; used to estimate file size.
_BYTES_PER_CELL = 4


@dataclass(frozen=True)
class ElevationGrid:
    """A DEM raster held in memory as rows of elevations in metres.

    Rows run from north to south and columns from west to east, matching the
    GeoTIFF pixel order produced by B1.2 (raster reader).

    Attributes:
        layer_id (str): GeoDesk layer ID of the DEM, e.g. ``"layer_dem_44c1"``.
        elevations (tuple[tuple[float, ...], ...]): Elevation of every cell in metres.
        cell_size_m (float): Width and height of one cell in metres.
        origin (tuple[float, float]): ``(x, y)`` of the *centre* of the
            north-west cell in the units of ``crs`` — not the raster's outer
            corner. From a GeoTIFF transform use
            ``(transform.c + transform.a / 2, transform.f + transform.e / 2)``.
        crs (str): Coordinate reference system of ``origin``.
        nodata (float | None): Sentinel value marking cells without data, or
            ``None`` if only NaN values mark missing cells.

    Example:
        >>> from geodesk.terrain import ElevationGrid
        >>> zaisan_dem = ElevationGrid.from_rows(
        ...     "layer_dem_44c1",
        ...     [[1350.0, 1351.0, 1352.0],
        ...      [1351.0, 1352.0, 1353.0],
        ...      [1352.0, 1353.0, 1354.0]],
        ...     cell_size_m=30.0, origin=(650000.0, 5310000.0))
        >>> zaisan_dem.shape
        (3, 3)
    """

    layer_id: str
    elevations: tuple[tuple[float, ...], ...]
    cell_size_m: float
    origin: Point
    crs: str = "EPSG:32648"
    nodata: float | None = None

    @classmethod
    def from_rows(
        cls,
        layer_id: str,
        rows: list[list[float]],
        *,
        cell_size_m: float,
        origin: Point,
        crs: str = "EPSG:32648",
        nodata: float | None = None,
    ) -> ElevationGrid:
        """Build a grid from nested lists, as returned by ``rasterio`` ``read(1).tolist()``.

        Args:
            layer_id: GeoDesk layer ID of the DEM.
            rows: Elevations in metres, north row first. All rows must have
                the same length and the grid must be at least 2 × 2.
            cell_size_m: Cell width and height in metres; must be positive.
            origin: ``(x, y)`` of the north-west cell *centre* in ``crs``
                units (see the module Quickstart for GeoTIFF files).
            crs: Coordinate reference system, UTM 48N by default.
            nodata: Value that marks missing cells, or ``None`` if only NaN
                values mark missing cells.

        Returns:
            ElevationGrid: An immutable grid.

        Raises:
            ValueError: If the rows are ragged, smaller than 2 × 2, or
                ``cell_size_m`` is not positive.

        Example:
            >>> from geodesk.terrain import ElevationGrid
            >>> zaisan_dem = ElevationGrid.from_rows(
            ...     "layer_dem_44c1",
            ...     [[1350.0, 1351.0, 1352.0],
            ...      [1351.0, 1352.0, 1353.0],
            ...      [1352.0, 1353.0, 1354.0]],
            ...     cell_size_m=30.0, origin=(650000.0, 5310000.0))
            >>> zaisan_dem.crs
            'EPSG:32648'
        """
        if len(rows) < 2 or len(rows[0]) < 2:
            raise ValueError("a DEM needs at least 2 x 2 cells to trace contours")
        if any(len(row) != len(rows[0]) for row in rows):
            raise ValueError("every DEM row must have the same number of cells")
        if cell_size_m <= 0:
            raise ValueError(f"cell_size_m must be positive, got {cell_size_m}")
        frozen_rows = tuple(tuple(float(value) for value in row) for row in rows)
        return cls(layer_id, frozen_rows, float(cell_size_m), origin, crs, nodata)

    @property
    def shape(self) -> tuple[int, int]:
        """tuple[int, int]: Number of ``(rows, columns)``.

        Example:
            >>> from geodesk.terrain import ElevationGrid
            >>> zaisan_dem = ElevationGrid.from_rows(
            ...     "layer_dem_44c1",
            ...     [[1350.0, 1351.0, 1352.0],
            ...      [1351.0, 1352.0, 1353.0],
            ...      [1352.0, 1353.0, 1354.0]],
            ...     cell_size_m=30.0, origin=(650000.0, 5310000.0))
            >>> zaisan_dem.shape
            (3, 3)
        """
        return len(self.elevations), len(self.elevations[0])

    @property
    def size_mb(self) -> float:
        """float: Estimated size of the DEM as a float32 GeoTIFF, in megabytes.

        Example:
            >>> from geodesk.terrain import ElevationGrid
            >>> zaisan_dem = ElevationGrid.from_rows(
            ...     "layer_dem_44c1",
            ...     [[1350.0, 1351.0, 1352.0],
            ...      [1351.0, 1352.0, 1353.0],
            ...      [1352.0, 1353.0, 1354.0]],
            ...     cell_size_m=30.0, origin=(650000.0, 5310000.0))
            >>> zaisan_dem.size_mb
            3.6e-05
        """
        row_count, column_count = self.shape
        return row_count * column_count * _BYTES_PER_CELL / 1_000_000

    def nodata_ratio(self) -> float:
        """Return the share of cells that are NoData.

        A cell counts as missing if it is NaN or equals ``nodata``.

        Returns:
            float: A value from ``0.0`` (complete DEM) to ``1.0`` (no data at all).

        Example:
            >>> from geodesk.terrain import ElevationGrid
            >>> zaisan_dem = ElevationGrid.from_rows(
            ...     "layer_dem_44c1",
            ...     [[1350.0, 1351.0, 1352.0],
            ...      [1351.0, 1352.0, 1353.0],
            ...      [1352.0, -9999.0, 1354.0]],
            ...     cell_size_m=30.0, origin=(650000.0, 5310000.0), nodata=-9999.0)
            >>> round(zaisan_dem.nodata_ratio(), 3)
            0.111
        """
        cells = [value for row in self.elevations for value in row]
        missing = sum(1 for value in cells if self._is_nodata(value))
        return missing / len(cells)

    def valid_range(self) -> tuple[float, float]:
        """Return the lowest and highest elevation, ignoring NoData cells.

        Returns:
            tuple[float, float]: ``(min_elevation_m, max_elevation_m)``.

        Raises:
            NoDataCoverageError: If every cell is NoData.

        Example:
            >>> from geodesk.terrain import ElevationGrid
            >>> zaisan_dem = ElevationGrid.from_rows(
            ...     "layer_dem_44c1",
            ...     [[1350.0, 1351.0, 1352.0],
            ...      [1351.0, 1352.0, 1353.0],
            ...      [1352.0, 1353.0, 1354.0]],
            ...     cell_size_m=30.0, origin=(650000.0, 5310000.0))
            >>> zaisan_dem.valid_range()
            (1350.0, 1354.0)
        """
        valid = [value for row in self.elevations for value in row if not self._is_nodata(value)]
        if not valid:
            raise NoDataCoverageError(f"DEM {self.layer_id} contains only NoData cells.")
        return min(valid), max(valid)

    # Internal: NaN-aware NoData test shared by the methods above; not part of
    # the public API because callers should use nodata_ratio() instead.
    def _is_nodata(self, value: float) -> bool:
        return math.isnan(value) or (self.nodata is not None and value == self.nodata)


@dataclass(frozen=True)
class ContourLine:
    """One contour segment at a single elevation.

    Attributes:
        elevation_m (float): Elevation of the line in metres.
        points (tuple[tuple[float, float], ...]): Vertices in ``crs`` units,
            west-to-east order is not guaranteed.

    Example:
        >>> from geodesk.terrain import ContourLine
        >>> ridge_line = ContourLine(1352.0, ((650030.0, 5310000.0), (650000.0, 5309970.0)))
        >>> ridge_line.length_m
        42.43
    """

    elevation_m: float
    points: tuple[Point, ...]

    @property
    def length_m(self) -> float:
        """float: Planar length of the line in metres, rounded to centimetres.

        Example:
            >>> from geodesk.terrain import ContourLine
            >>> ridge_line = ContourLine(1352.0, ((650030.0, 5310000.0), (650000.0, 5309970.0)))
            >>> ridge_line.length_m
            42.43
        """
        segment_lengths = (math.dist(start, end) for start, end in zip(self.points, self.points[1:]))
        return round(sum(segment_lengths), 2)


@dataclass(frozen=True)
class ContourLayer:
    """The vector layer returned by :meth:`ContourGenerator.generate`.

    It is handed to B3 (layer manager) and becomes ``output_layer_id`` in the
    W05 ``ContourResult`` API response.

    Attributes:
        layer_id (str): ID of the new contour layer, e.g. ``"layer_contour_9a21"``.
        source_layer_id (str): ID of the DEM the contours were traced from.
        interval_m (float): Vertical distance between neighbouring contours.
        crs (str): Coordinate reference system of every point.
        lines (tuple[ContourLine, ...]): All traced contour segments.

    Example:
        >>> from geodesk import ContourGenerator
        >>> from geodesk.terrain import ElevationGrid
        >>> zaisan_dem = ElevationGrid.from_rows(
        ...     "layer_dem_44c1",
        ...     [[1350.0, 1351.0, 1352.0],
        ...      [1351.0, 1352.0, 1353.0],
        ...      [1352.0, 1353.0, 1354.0]],
        ...     cell_size_m=30.0, origin=(650000.0, 5310000.0))
        >>> contour_layer = ContourGenerator(interval_m=1.0).generate(zaisan_dem)
        >>> contour_layer.elevations()
        [1351.0, 1352.0, 1353.0]
    """

    layer_id: str
    source_layer_id: str
    interval_m: float
    crs: str
    lines: tuple[ContourLine, ...] = field(default_factory=tuple)

    def elevations(self) -> list[float]:
        """Return each distinct contour elevation once, lowest first.

        Returns:
            list[float]: Sorted elevations in metres.

        Example:
            >>> from geodesk import ContourGenerator
            >>> from geodesk.terrain import ElevationGrid
            >>> zaisan_dem = ElevationGrid.from_rows(
            ...     "layer_dem_44c1",
            ...     [[1350.0, 1351.0, 1352.0],
            ...      [1351.0, 1352.0, 1353.0],
            ...      [1352.0, 1353.0, 1354.0]],
            ...     cell_size_m=30.0, origin=(650000.0, 5310000.0))
            >>> ContourGenerator(interval_m=2.0).generate(zaisan_dem).elevations()
            [1352.0]
        """
        return sorted({line.elevation_m for line in self.lines})

    def to_geojson(self) -> dict:
        """Export the layer as a GeoJSON ``FeatureCollection`` (B1.3 format writer input).

        Each line becomes a ``LineString`` feature with an ``elevation_m``
        property, so the result can be saved directly with ``json.dump``.

        Returns:
            dict: A GeoJSON FeatureCollection. Coordinates stay in ``crs``;
            no reprojection to WGS84 is done.

        Example:
            >>> from geodesk import ContourGenerator
            >>> from geodesk.terrain import ElevationGrid
            >>> zaisan_dem = ElevationGrid.from_rows(
            ...     "layer_dem_44c1",
            ...     [[1350.0, 1351.0, 1352.0],
            ...      [1351.0, 1352.0, 1353.0],
            ...      [1352.0, 1353.0, 1354.0]],
            ...     cell_size_m=30.0, origin=(650000.0, 5310000.0))
            >>> geojson = ContourGenerator(interval_m=1.0).generate(zaisan_dem).to_geojson()
            >>> geojson["features"][0]["properties"]
            {'elevation_m': 1351.0}
        """
        # TODO(#3): Reproject coordinates to EPSG:4326 as RFC 7946 requires.
        features = [
            {
                "type": "Feature",
                "properties": {"elevation_m": line.elevation_m},
                "geometry": {"type": "LineString", "coordinates": [list(point) for point in line.points]},
            }
            for line in self.lines
        ]
        return {"type": "FeatureCollection", "name": self.layer_id, "features": features}


class ContourGenerator:
    """Traces contour lines from a DEM at a fixed vertical interval (FR-09).

    The generator validates the DEM first (B5.1 DEM validator) so that
    oversized or damaged rasters fail with a clear error instead of crashing
    the Geo Processing Engine (NFR-05).

    Args:
        interval_m: Vertical distance between contours in metres. Must be
            finite and at least :attr:`MIN_INTERVAL_M` (0.5 m), the accuracy
            guaranteed by FR-09.
        max_size_mb: Largest DEM accepted, in megabytes (default 200).
        max_nodata_ratio: Largest share of NoData cells accepted, from 0 to 1
            (default 0.2).

    Raises:
        InvalidIntervalError: If ``interval_m`` is below 0.5, infinite or NaN.

    Example:
        >>> from geodesk import ContourGenerator
        >>> from geodesk.terrain import ElevationGrid
        >>> zaisan_dem = ElevationGrid.from_rows(
        ...     "layer_dem_44c1",
        ...     [[1350.0, 1351.0, 1352.0],
        ...      [1351.0, 1352.0, 1353.0],
        ...      [1352.0, 1353.0, 1354.0]],
        ...     cell_size_m=30.0, origin=(650000.0, 5310000.0))
        >>> one_metre_contours = ContourGenerator(interval_m=1.0)
        >>> contour_layer = one_metre_contours.generate(zaisan_dem)
        >>> len(contour_layer.lines)
        7
    """

    #: Smallest interval accepted, in metres (FR-09 accuracy of ±0.5 m).
    MIN_INTERVAL_M = 0.5

    def __init__(self, interval_m: float, *, max_size_mb: float = 200.0, max_nodata_ratio: float = 0.2) -> None:
        self.interval_m = self._validate_interval(interval_m)
        self.max_size_mb = max_size_mb
        self.max_nodata_ratio = max_nodata_ratio

    def levels(self, grid: ElevationGrid) -> list[float]:
        """Return the contour elevations that fall strictly inside the DEM's range.

        Levels are multiples of ``interval_m``, so two DEMs processed with the
        same generator always share contour elevations and can be merged.

        Args:
            grid: The DEM to inspect.

        Returns:
            list[float]: Contour elevations in metres, lowest first. Empty if
            the terrain is flatter than one interval.

        Raises:
            NoDataCoverageError: If every cell of ``grid`` is NoData.

        Example:
            >>> from geodesk import ContourGenerator
            >>> from geodesk.terrain import ElevationGrid
            >>> zaisan_dem = ElevationGrid.from_rows(
            ...     "layer_dem_44c1",
            ...     [[1350.0, 1351.0, 1352.0],
            ...      [1351.0, 1352.0, 1353.0],
            ...      [1352.0, 1353.0, 1354.0]],
            ...     cell_size_m=30.0, origin=(650000.0, 5310000.0))
            >>> ContourGenerator(interval_m=2.0).levels(zaisan_dem)
            [1352.0]
        """
        lowest, highest = grid.valid_range()
        first_level = math.floor(lowest / self.interval_m + 1) * self.interval_m
        level_count = max(0, math.ceil((highest - first_level) / self.interval_m))
        return [round(first_level + step * self.interval_m, 6) for step in range(level_count)]

    def generate(self, grid: ElevationGrid, *, output_layer_id: str = "layer_contour_9a21") -> ContourLayer:
        """Validate ``grid`` and trace all contour lines with marching squares.

        A 50 MB DEM finishes in under 8 seconds on the reference machine
        (FR-09 verification). Cells that touch a NoData value are skipped, so
        lines stop at data gaps instead of bending towards the sentinel value.

        Args:
            grid: The DEM to contour, typically from B1.2 (raster reader).
            output_layer_id: ID given to the returned layer.

        Returns:
            ContourLayer: One :class:`ContourLine` per cell crossing, in the
            CRS of ``grid``.

        Raises:
            DEMTooLargeError: If ``grid.size_mb`` exceeds ``max_size_mb``.
            NoDataCoverageError: If the NoData share exceeds ``max_nodata_ratio``.

        Example:
            >>> from geodesk import ContourGenerator
            >>> from geodesk.terrain import ElevationGrid
            >>> zaisan_dem = ElevationGrid.from_rows(
            ...     "layer_dem_44c1",
            ...     [[1350.0, 1351.0, 1352.0],
            ...      [1351.0, 1352.0, 1353.0],
            ...      [1352.0, 1353.0, 1354.0]],
            ...     cell_size_m=30.0, origin=(650000.0, 5310000.0))
            >>> contour_layer = ContourGenerator(interval_m=1.0).generate(zaisan_dem)
            >>> contour_layer.lines[0]
            ContourLine(elevation_m=1351.0, points=((650030.0, 5310000.0), (650000.0, 5309970.0)))
        """
        self._check_dem(grid)
        lines = [
            ContourLine(level, segment)
            for level in self.levels(grid)
            for segment in self._trace_level(grid, level)
        ]
        return ContourLayer(output_layer_id, grid.layer_id, self.interval_m, grid.crs, tuple(lines))

    # ------------------------------------------------------------------
    # Internal helpers (B5.2.1–B5.2.3). They are excluded from the public
    # API because their signatures follow the algorithm, not the user's
    # task, and may change when chunked reading (#2) is added.
    # ------------------------------------------------------------------

    # Internal (B5.2.1): called once from __init__; users get InvalidIntervalError instead.
    @classmethod
    def _validate_interval(cls, interval_m: float) -> float:
        if not math.isfinite(interval_m) or interval_m < cls.MIN_INTERVAL_M:
            raise InvalidIntervalError(
                f"interval_m must be a finite number >= {cls.MIN_INTERVAL_M} m, got {interval_m}."
            )
        return float(interval_m)

    # Internal (B5.1): validation step of generate(); its errors are documented there.
    def _check_dem(self, grid: ElevationGrid) -> None:
        # TODO(#2): Read the DEM in row blocks (B5.2.2) instead of loading it all into memory.
        if grid.size_mb > self.max_size_mb:
            raise DEMTooLargeError(
                f"DEM {grid.layer_id} is {grid.size_mb:.1f} MB; the limit is {self.max_size_mb:.0f} MB."
            )
        nodata_ratio = grid.nodata_ratio()
        if nodata_ratio > self.max_nodata_ratio:
            raise NoDataCoverageError(
                f"DEM {grid.layer_id} has {nodata_ratio:.0%} NoData cells; "
                f"the limit is {self.max_nodata_ratio:.0%}."
            )

    # Internal (B5.2.3): one marching-squares pass for a single level.
    def _trace_level(self, grid: ElevationGrid, level: float) -> list[tuple[Point, Point]]:
        segments = []
        row_count, column_count = grid.shape
        for row in range(row_count - 1):
            for column in range(column_count - 1):
                corners = (
                    grid.elevations[row][column],
                    grid.elevations[row][column + 1],
                    grid.elevations[row + 1][column + 1],
                    grid.elevations[row + 1][column],
                )
                if any(grid._is_nodata(value) for value in corners):
                    continue
                segments.extend(self._cell_segments(grid, row, column, corners, level))
        return segments

    # Internal (B5.2.3): segment lookup for one cell; signature follows the algorithm.
    @staticmethod
    def _cell_segments(grid, row, column, corners, level):
        # Corners are clockwise from north-west: NW, NE, SE, SW.
        north_west, north_east, south_east, south_west = corners
        x0 = grid.origin[0] + column * grid.cell_size_m
        y0 = grid.origin[1] - row * grid.cell_size_m
        size = grid.cell_size_m

        def crossing(start_value, end_value):
            return (level - start_value) / (end_value - start_value)

        edge_points = {}
        if (north_west >= level) != (north_east >= level):
            edge_points["north"] = (x0 + size * crossing(north_west, north_east), y0)
        if (north_east >= level) != (south_east >= level):
            edge_points["east"] = (x0 + size, y0 - size * crossing(north_east, south_east))
        if (south_west >= level) != (south_east >= level):
            edge_points["south"] = (x0 + size * crossing(south_west, south_east), y0 - size)
        if (north_west >= level) != (south_west >= level):
            edge_points["west"] = (x0, y0 - size * crossing(north_west, south_west))

        if len(edge_points) == 2:
            first, second = edge_points.values()
            return [(_round_point(first), _round_point(second))]
        if len(edge_points) == 4:
            # TODO(#1): Resolve saddle cells with the cell-centre average instead of a fixed pairing.
            return [
                (_round_point(edge_points["north"]), _round_point(edge_points["west"])),
                (_round_point(edge_points["south"]), _round_point(edge_points["east"])),
            ]
        return []


# Internal: rounds to millimetres so floating-point noise does not create
# duplicate vertices; not exported because it is a numeric detail.
def _round_point(point: Point) -> Point:
    return round(point[0], 3), round(point[1], 3)
