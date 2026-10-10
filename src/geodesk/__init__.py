"""GeoDesk Geo Processing Engine — public Python API.

Only the names listed in ``__all__`` are public and covered by the API
reference; everything else is internal and may change without notice.
"""

from geodesk.errors import (
    DEMTooLargeError,
    InvalidIntervalError,
    NoDataCoverageError,
    TerrainError,
)
from geodesk.terrain import ContourGenerator, ContourLayer, ContourLine, ElevationGrid

__all__ = [
    "ContourGenerator",
    "ContourLayer",
    "ContourLine",
    "ElevationGrid",
    "TerrainError",
    "InvalidIntervalError",
    "DEMTooLargeError",
    "NoDataCoverageError",
]

__version__ = "0.6.0"
