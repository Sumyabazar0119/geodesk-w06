"""Terrain analysis for GeoDesk: elevation grids and contour generation.

Quickstart:
    Load a DEM from a GeoTIFF, generate contour lines every 1 m, and save
    them to a GeoJSON file. ``ElevationGrid`` holds the elevation values,
    ``ContourGenerator.generate()`` returns a ``ContourLayer``, and
    ``ContourLayer.to_geojson()`` returns a GeoJSON-compatible dict.

    Example:
        import json

        import rasterio

        from geodesk.terrain import ContourGenerator, ElevationGrid

        # Step 1: load the DEM from a GeoTIFF file on disk.
        with rasterio.open("dem.tif") as src:
            transform = src.transform
            grid = ElevationGrid.from_rows(
                "dem_source",
                src.read(1).tolist(),
                cell_size_m=transform.a,
                origin=(transform.c, transform.f),
                crs=src.crs.to_string(),
                nodata=src.nodata,
            )

        # Step 2: generate contour lines every 1 m.
        contours = ContourGenerator(interval_m=1.0).generate(grid)

        # Step 3: save the contours to a GeoJSON file.
        with open("contours_1m.geojson", "w", encoding="utf-8") as f:
            json.dump(contours.to_geojson(), f)

Error handling:
    Catch the module's errors around generation:
        from geodesk.errors import (
            DEMTooLargeError,
            InvalidIntervalError,
            NoDataCoverageError,
        )
        from geodesk.terrain import ContourGenerator

        try:
            contours = ContourGenerator(interval_m=1.0).generate(grid)
        except InvalidIntervalError:
            print("Interval is below ContourGenerator.MIN_INTERVAL_M (0.5 m).")
        except DEMTooLargeError:
            print("DEM exceeds max_size_mb; raise the limit or crop the DEM.")
        except NoDataCoverageError:
            print("DEM has too many nodata cells; fill or crop it first.")
"""
# Model note returned after the docstring (verbatim):
# "Note: the provided code has no GeoTIFF reader, so Step 1 uses `rasterio` (a
# third-party library, not part of the provided code) and assumes `origin` is the
# transform's top-left corner. Verify both before publishing."
