from __future__ import annotations
import math
from dataclasses import dataclass, field
from geodesk.errors import DEMTooLargeError, InvalidIntervalError, NoDataCoverageError
__all__ = ['ElevationGrid', 'ContourLine', 'ContourLayer', 'ContourGenerator']
Point = tuple[float, float]
_BYTES_PER_CELL = 4

@dataclass(frozen=True)
class ElevationGrid:
    layer_id: str
    elevations: tuple[tuple[float, ...], ...]
    cell_size_m: float
    origin: Point
    crs: str = 'EPSG:32648'
    nodata: float | None = None

    @classmethod
    def from_rows(cls, layer_id: str, rows: list[list[float]], *, cell_size_m: float, origin: Point, crs: str='EPSG:32648', nodata: float | None=None) -> ElevationGrid:
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
        return (len(self.elevations), len(self.elevations[0]))

    @property
    def size_mb(self) -> float:
        row_count, column_count = self.shape
        return row_count * column_count * _BYTES_PER_CELL / 1000000

    def nodata_ratio(self) -> float:
        cells = [value for row in self.elevations for value in row]
        missing = sum((1 for value in cells if self._is_nodata(value)))
        return missing / len(cells)

    def valid_range(self) -> tuple[float, float]:
        valid = [value for row in self.elevations for value in row if not self._is_nodata(value)]
        if not valid:
            raise NoDataCoverageError(f'DEM {self.layer_id} contains only NoData cells.')
        return (min(valid), max(valid))

    def _is_nodata(self, value: float) -> bool:
        return math.isnan(value) or (self.nodata is not None and value == self.nodata)

@dataclass(frozen=True)
class ContourLine:
    elevation_m: float
    points: tuple[Point, ...]

    @property
    def length_m(self) -> float:
        segment_lengths = (math.dist(start, end) for start, end in zip(self.points, self.points[1:]))
        return round(sum(segment_lengths), 2)

@dataclass(frozen=True)
class ContourLayer:
    layer_id: str
    source_layer_id: str
    interval_m: float
    crs: str
    lines: tuple[ContourLine, ...] = field(default_factory=tuple)

    def elevations(self) -> list[float]:
        return sorted({line.elevation_m for line in self.lines})

    def to_geojson(self) -> dict:
        features = [{'type': 'Feature', 'properties': {'elevation_m': line.elevation_m}, 'geometry': {'type': 'LineString', 'coordinates': [list(point) for point in line.points]}} for line in self.lines]
        return {'type': 'FeatureCollection', 'name': self.layer_id, 'features': features}

class ContourGenerator:
    MIN_INTERVAL_M = 0.5

    def __init__(self, interval_m: float, *, max_size_mb: float=200.0, max_nodata_ratio: float=0.2) -> None:
        self.interval_m = self._validate_interval(interval_m)
        self.max_size_mb = max_size_mb
        self.max_nodata_ratio = max_nodata_ratio

    def levels(self, grid: ElevationGrid) -> list[float]:
        lowest, highest = grid.valid_range()
        first_level = math.floor(lowest / self.interval_m + 1) * self.interval_m
        level_count = max(0, math.ceil((highest - first_level) / self.interval_m))
        return [round(first_level + step * self.interval_m, 6) for step in range(level_count)]

    def generate(self, grid: ElevationGrid, *, output_layer_id: str='layer_contour_9a21') -> ContourLayer:
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
