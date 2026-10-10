"""Terrain analysis tools for GeoDesk: elevation grids and contour lines.

Quickstart:
    GeoDesk's terrain module works on an in-memory `ElevationGrid`. It does
    not read GeoTIFF files itself. To load a DEM, read the raster with a
    library such as `rasterio` and build the grid with
    `ElevationGrid.from_rows`. Then pass the grid to a `ContourGenerator`
    and write the resulting `ContourLayer` out as GeoJSON.

    The example below assumes `rasterio` is installed and that the DEM is
    in a projected CRS with square cells measured in metres.

    ```python
    import json

    import rasterio

    from geodesk.terrain import ContourGenerator, ElevationGrid

    # 1. Load the DEM from a GeoTIFF on disk.
    with rasterio.open("dem.tif") as src:
        rows = src.read(1).astype(float).tolist()  # first band as list[list[float]]
        transform = src.transform
        grid = ElevationGrid.from_rows(
            "layer_dem",
            rows,
            cell_size_m=abs(transform.a),            # cell width in metres
            origin=(transform.c, transform.f),       # x, y of the raster's upper-left corner
            crs=src.crs.to_string(),                 # e.g. "EPSG:32648"
            nodata=src.nodata,                       # None if the file defines no NoData value
        )

    # 2. Generate 1 m contour lines.
    generator = ContourGenerator(interval_m=1.0)
    contours = generator.generate(grid, output_layer_id="layer_contour_1m")

    # 3. Save the contours to a GeoJSON file.
    with open("contours_1m.geojson", "w", encoding="utf-8") as f:
        json.dump(contours.to_geojson(), f)
    ```

    Notes:
        * Check that `origin` matches the corner convention your
          `ElevationGrid` expects. The example passes the raster's
          upper-left corner, which is where GeoTIFF row 0 starts.
        * The contour layer keeps the CRS of the source grid (`contours.crs`).
          Reproject the output if your GeoJSON consumer expects EPSG:4326.
        * The smallest allowed interval is `ContourGenerator.MIN_INTERVAL_M`
          (0.5 m).

Error handling:
    `ContourGenerator` and `generate` can raise the exceptions below, all
    defined in `geodesk.errors`. Catch them to give the user a clear message.

    ```python
    from geodesk.errors import (
        DEMTooLargeError,
        InvalidIntervalError,
        NoDataCoverageError,
    )

    try:
        generator = ContourGenerator(interval_m=1.0, max_size_mb=200.0)
        contours = generator.generate(grid)
    except InvalidIntervalError:
        # The contour interval is not usable, e.g. below the 0.5 m minimum.
        print("Choose a larger contour interval.")
    except DEMTooLargeError:
        # The grid exceeds max_size_mb. Clip the DEM or raise the limit.
        print(f"DEM is {grid.size_mb:.1f} MB; clip it or raise max_size_mb.")
    except NoDataCoverageError:
        # Too much of the grid is NoData (limit: max_nodata_ratio, default 0.2).
        print(f"{grid.nodata_ratio():.0%} of the DEM is NoData.")
    ```
"""
