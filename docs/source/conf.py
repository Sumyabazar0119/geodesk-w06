"""Sphinx configuration for the GeoDesk API reference."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

import geodesk  # noqa: E402

project = "GeoDesk GIS"
author = "С.Сумъяабазар (21B1NUM0119)"
copyright = "2026, " + author
release = geodesk.__version__

extensions = [
    "sphinx.ext.autodoc",
    "sphinx.ext.napoleon",
    "sphinx.ext.doctest",
    "sphinx.ext.viewcode",
    "myst_parser",
]

# Google-style docstrings only; reST field lists come from napoleon.
napoleon_google_docstring = True
napoleon_numpy_docstring = False
napoleon_use_rtype = False

autodoc_default_options = {"members": True, "show-inheritance": True}
autodoc_member_order = "bysource"
autodoc_typehints = "description"

# Every cross-reference must resolve; together with -W this fails the build on ghost APIs.
nitpicky = True
nitpick_ignore = [("py:class", "Point")]

source_suffix = {".rst": "restructuredtext", ".md": "markdown"}
exclude_patterns = []

html_theme = "sphinx_rtd_theme"
html_static_path = []
html_title = f"GeoDesk API {release}"
