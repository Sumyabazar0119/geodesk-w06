"""Exceptions raised by the GeoDesk terrain analysis API.

Each exception maps to one error response of ``POST /terrain/contours`` in the
W05 OpenAPI specification, so a desktop user and an API client see the same
error code for the same problem.
"""


class TerrainError(Exception):
    """Base class for every error raised by :mod:`geodesk.terrain`.

    Attributes:
        error_code (str): Stable machine-readable code, identical to the
            ``error_code`` field of the W05 API ``Error`` schema.

    Example:
        Catch the base class to handle every terrain failure in one place:

        >>> from geodesk import ContourGenerator, TerrainError
        >>> try:
        ...     ContourGenerator(interval_m=0.1)
        ... except TerrainError as error:
        ...     print(f"{error.error_code}: {error}")
        INVALID_INTERVAL: interval_m must be a finite number >= 0.5 m, got 0.1.
    """

    error_code = "TERRAIN_ERROR"


class InvalidIntervalError(TerrainError, ValueError):
    """The contour interval is not a finite number of at least 0.5 metres.

    FR-09 guarantees ±0.5 m accuracy, so a finer interval would draw lines the
    DEM cannot support.

    Example:
        >>> from geodesk import ContourGenerator, InvalidIntervalError
        >>> try:
        ...     ContourGenerator(interval_m=0.1)
        ... except InvalidIntervalError as error:
        ...     print(error.error_code)
        INVALID_INTERVAL
    """

    error_code = "INVALID_INTERVAL"


class DEMTooLargeError(TerrainError):
    """The DEM exceeds the size limit (200 MB by default, NFR-01 / HTTP 413).

    Example:
        >>> from geodesk import ContourGenerator, DEMTooLargeError
        >>> from geodesk.terrain import ElevationGrid
        >>> zaisan_dem = ElevationGrid.from_rows(
        ...     "layer_dem_44c1",
        ...     [[1350.0, 1351.0, 1352.0],
        ...      [1351.0, 1352.0, 1353.0],
        ...      [1352.0, 1353.0, 1354.0]],
        ...     cell_size_m=30.0, origin=(650000.0, 5310000.0))
        >>> tiny_limit = ContourGenerator(interval_m=1.0, max_size_mb=0.00001)
        >>> try:
        ...     tiny_limit.generate(zaisan_dem)
        ... except DEMTooLargeError as error:
        ...     print(error.error_code)
        PAYLOAD_TOO_LARGE
    """

    error_code = "PAYLOAD_TOO_LARGE"


class NoDataCoverageError(TerrainError):
    """Too many DEM cells are NoData to compute reliable contours (NFR-05 / HTTP 422).

    Example:
        >>> from geodesk import ContourGenerator, NoDataCoverageError
        >>> from geodesk.terrain import ElevationGrid
        >>> damaged_dem = ElevationGrid.from_rows(
        ...     "layer_dem_44c1",
        ...     [[1350.0, -9999.0, -9999.0],
        ...      [1351.0, -9999.0, 1353.0],
        ...      [1352.0, 1353.0, 1354.0]],
        ...     cell_size_m=30.0, origin=(650000.0, 5310000.0), nodata=-9999.0)
        >>> try:
        ...     ContourGenerator(interval_m=1.0).generate(damaged_dem)
        ... except NoDataCoverageError as error:
        ...     print(error.error_code, error)
        INVALID_DEM DEM layer_dem_44c1 has 33% NoData cells; the limit is 20%.
    """

    error_code = "INVALID_DEM"
