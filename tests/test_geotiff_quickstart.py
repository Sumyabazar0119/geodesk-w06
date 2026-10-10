"""Runs the module Quickstart on a real GeoTIFF (Bhatti p. 94 "Trustworthy").

It also reproduces the half-cell error found in AI runs 2 and 3, which passed
the raster's outer corner ``(transform.c, transform.f)`` as ``origin``.
"""
import json
import re
import textwrap

import pytest

rasterio = pytest.importorskip("rasterio")
from rasterio.transform import from_origin  # noqa: E402

import geodesk.terrain  # noqa: E402
from geodesk import ContourGenerator  # noqa: E402
from geodesk.terrain import ElevationGrid  # noqa: E402

ZAISAN_ROWS = [[1350.0, 1351.0, 1352.0], [1351.0, 1352.0, 1353.0], [1352.0, 1353.0, 1354.0]]


@pytest.fixture
def zaisan_geotiff(tmp_path, monkeypatch):
    # Outer corner is half a 30 m cell north-west of the first cell centre (650000, 5310000).
    import numpy

    monkeypatch.chdir(tmp_path)
    with rasterio.open(
        "zaisan_dem.tif", "w", driver="GTiff", height=3, width=3, count=1, dtype="float32",
        crs="EPSG:32648", transform=from_origin(649985.0, 5310015.0, 30.0, 30.0), nodata=-9999.0,
    ) as dem_file:
        dem_file.write(numpy.array(ZAISAN_ROWS, dtype="float32"), 1)
    return tmp_path


def quickstart_source():
    block = re.search(r"\.\. code-block:: python\n\n(.*)", geodesk.terrain.__doc__, re.DOTALL).group(1)
    return textwrap.dedent(block)


def test_module_quickstart_runs_and_matches_in_memory_example(zaisan_geotiff):
    exec(compile(quickstart_source(), "<terrain Quickstart>", "exec"), {})

    exported = json.loads((zaisan_geotiff / "zaisan_contours_1m.geojson").read_text(encoding="utf-8"))
    in_memory = ElevationGrid.from_rows("layer_dem_44c1", ZAISAN_ROWS, cell_size_m=30.0, origin=(650000.0, 5310000.0))
    expected = ContourGenerator(interval_m=1.0).generate(in_memory).to_geojson()
    assert exported["features"] == json.loads(json.dumps(expected["features"]))


def test_ai_corner_origin_shifts_contours_by_half_a_cell(zaisan_geotiff):
    with rasterio.open("zaisan_dem.tif") as dem_file:
        transform = dem_file.transform
        ai_grid = ElevationGrid.from_rows(
            "layer_dem_44c1", dem_file.read(1).tolist(), cell_size_m=transform.a,
            origin=(transform.c, transform.f),  # as written by AI runs 2 and 3
        )
    correct_grid = ElevationGrid.from_rows("layer_dem_44c1", ZAISAN_ROWS, cell_size_m=30.0, origin=(650000.0, 5310000.0))

    ai_first = ContourGenerator(interval_m=1.0).generate(ai_grid).lines[0].points[0]
    correct_first = ContourGenerator(interval_m=1.0).generate(correct_grid).lines[0].points[0]
    assert (ai_first[0] - correct_first[0], ai_first[1] - correct_first[1]) == (-15.0, 15.0)
