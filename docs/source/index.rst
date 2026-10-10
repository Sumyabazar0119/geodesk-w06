GeoDesk GIS — API Reference
===========================

GeoDesk-ийн Geo Processing Engine-ийн нийтийн Python API. Энэ лавлах нь
``src/geodesk`` доторх docstring-оос ``sphinx-build -W`` (анхааруулгагүй)
горимоор GitLab CI-д автоматаар үүсдэг.

.. code-block:: python

   from geodesk import ContourGenerator
   from geodesk.terrain import ElevationGrid

   zaisan_dem = ElevationGrid.from_rows(
       "layer_dem_44c1",
       [[1350.0, 1351.0, 1352.0],
        [1351.0, 1352.0, 1353.0],
        [1352.0, 1353.0, 1354.0]],
       cell_size_m=30.0, origin=(650000.0, 5310000.0))

   contour_layer = ContourGenerator(interval_m=1.0).generate(zaisan_dem)
   print(contour_layer.elevations())   # [1351.0, 1352.0, 1353.0]

.. toctree::
   :maxdepth: 2
   :caption: API

   api

.. toctree::
   :maxdepth: 1
   :caption: Sprint 06 audit

   audit/bhatti_audit_table
   audit/use_verify_cite_log
   audit/technical_debt
