"""Behavioural tests for the public geodesk.terrain API (FR-09, NFR-05)."""
import math

import pytest

from geodesk import (
    ContourGenerator,
    DEMTooLargeError,
    InvalidIntervalError,
    NoDataCoverageError,
)
from geodesk.terrain import ElevationGrid

ZAISAN_ROWS = [
    [1350.0, 1351.0, 1352.0],
    [1351.0, 1352.0, 1353.0],
    [1352.0, 1353.0, 1354.0],
]


def zaisan_dem(rows=ZAISAN_ROWS, nodata=None):
    return ElevationGrid.from_rows(
        "layer_dem_44c1", rows, cell_size_m=30.0, origin=(650000.0, 5310000.0), nodata=nodata
    )


@pytest.mark.parametrize("bad_interval", [0.0, 0.49, -1.0, math.inf, math.nan])
def test_interval_below_fr09_accuracy_is_rejected(bad_interval):
    with pytest.raises(InvalidIntervalError):
        ContourGenerator(interval_m=bad_interval)


def test_levels_are_multiples_of_interval_inside_range():
    assert ContourGenerator(interval_m=1.0).levels(zaisan_dem()) == [1351.0, 1352.0, 1353.0]
    assert ContourGenerator(interval_m=2.0).levels(zaisan_dem()) == [1352.0]


def test_flat_terrain_produces_no_contours():
    flat_rows = [[1352.0, 1352.0], [1352.0, 1352.0]]
    assert ContourGenerator(interval_m=1.0).generate(zaisan_dem(flat_rows)).lines == ()


def test_every_vertex_lies_on_its_contour_elevation():
    # ±0.5 m accuracy (FR-09): interpolate the DEM at each vertex and compare.
    contour_layer = ContourGenerator(interval_m=1.0).generate(zaisan_dem())
    for line in contour_layer.lines:
        for x, y in line.points:
            column = (x - 650000.0) / 30.0
            row = (5310000.0 - y) / 30.0
            # The Zaisan sample is a plane: elevation = 1350 + row + column.
            assert abs(1350.0 + row + column - line.elevation_m) <= 0.5


def test_saddle_cell_produces_two_segments():
    saddle_rows = [[1353.0, 1351.0], [1351.0, 1353.0]]
    contour_layer = ContourGenerator(interval_m=2.0).generate(zaisan_dem(saddle_rows))
    assert len(contour_layer.lines) == 2


def test_cells_touching_nodata_are_skipped():
    rows = [[1350.0, 1351.0, 1352.0], [1351.0, 1352.0, 1353.0], [1352.0, -9999.0, 1354.0]]
    contour_layer = ContourGenerator(interval_m=1.0).generate(zaisan_dem(rows, nodata=-9999.0))
    assert all(-9999.0 not in point for line in contour_layer.lines for point in line.points)
    assert len(contour_layer.lines) == 4  # 2 southern cells skipped: 1 + 2 + 1 segments


def test_oversized_dem_is_rejected_with_api_error_code():
    with pytest.raises(DEMTooLargeError) as error:
        ContourGenerator(interval_m=1.0, max_size_mb=0.00001).generate(zaisan_dem())
    assert error.value.error_code == "PAYLOAD_TOO_LARGE"


def test_all_nodata_dem_reports_invalid_dem():
    empty_rows = [[-9999.0, -9999.0], [-9999.0, -9999.0]]
    with pytest.raises(NoDataCoverageError):
        ContourGenerator(interval_m=1.0, max_nodata_ratio=1.0).generate(zaisan_dem(empty_rows, nodata=-9999.0))


def test_geojson_export_keeps_elevation_property():
    geojson = ContourGenerator(interval_m=1.0).generate(zaisan_dem()).to_geojson()
    assert geojson["type"] == "FeatureCollection"
    assert {feature["properties"]["elevation_m"] for feature in geojson["features"]} == {1351.0, 1352.0, 1353.0}
