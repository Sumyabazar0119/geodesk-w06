"""UE-6 (d): reflection test that every API named in documentation really exists.

An LLM can write a docstring that reads well but calls a method, class or
keyword argument the code never had (a "ghost API"). This test parses the
examples and Sphinx cross-references in a docstring, follows the names
through ``importlib`` / ``inspect`` and reports every reference that does not
resolve. It runs on our own docstrings (must be clean) and on the raw AI
outputs stored in ``audit/`` (results must match the Use-Verify-Cite log).
"""
from __future__ import annotations

import ast
import doctest
import importlib
import inspect
import re
import textwrap
import typing
from pathlib import Path

import pytest

import geodesk
import geodesk.terrain

AUDIT_DIR = Path(__file__).resolve().parent.parent / "audit"
SPHINX_ROLE = re.compile(r":(?:class|meth|attr|func|mod|exc):`~?([\w.]+)`")
FENCED_PYTHON = re.compile(r"```python\n(.*?)```", re.DOTALL)


# ---------------------------------------------------------------------------
# Reference extraction
# ---------------------------------------------------------------------------
def code_snippets(docstring: str) -> list[str]:
    """Return doctest examples, ```python fences and indented Python blocks."""
    doctest_code = "\n".join(example.source for example in doctest.DocTestParser().get_examples(docstring))
    fenced = [inspect.cleandoc(block) for block in FENCED_PYTHON.findall(docstring)]
    return [code for code in [doctest_code, *fenced, *indented_blocks(docstring)] if code.strip()]


def indented_blocks(docstring: str) -> list[str]:
    """Google-style ``Example:`` sections often hold plain indented code, not doctests."""
    lines = inspect.cleandoc(docstring).splitlines()
    blocks = []
    for index, line in enumerate(lines):
        if not line.rstrip().endswith(":") or "```" in docstring:
            continue
        header_indent = len(line) - len(line.lstrip())
        block = []
        for body_line in lines[index + 1:]:
            if body_line.strip() and len(body_line) - len(body_line.lstrip()) <= header_indent:
                break
            block.append(body_line)
        code = textwrap.dedent("\n".join(block)).strip()
        if ">>>" in code or "import " not in code:
            continue
        try:
            ast.parse(code)
        except SyntaxError:
            continue
        blocks.append(code)
    return blocks


def has_member(owner: object, name: str) -> bool:
    """True for attributes, methods, properties and dataclass fields."""
    return hasattr(owner, name) or name in getattr(owner, "__dataclass_fields__", {})


def resolve_role(target: str, context_class: type | None) -> bool:
    """Resolve a Sphinx cross-reference like ``ContourLayer.to_geojson`` or ``geodesk.errors``."""
    if target.startswith("geodesk"):
        module_name, _, member = target.rpartition(".")
        try:
            importlib.import_module(target)
            return True
        except ImportError:
            module = importlib.import_module(module_name)
            return has_member(module, member)
    first, *rest = target.split(".")
    owner = getattr(geodesk.terrain, first, None)
    if owner is None and context_class is not None and has_member(context_class, first):
        return True
    if owner is None:
        return False
    for attribute in rest:
        if not has_member(owner, attribute):
            return False
        owner = getattr(owner, attribute, None)
    return True


class ApiReferenceChecker(ast.NodeVisitor):
    """Track which variables hold GeoDesk objects and verify every use of them."""

    def __init__(self) -> None:
        self.known: dict[str, object] = {"geodesk": geodesk}
        self.ghosts: list[str] = []

    # --- imports -------------------------------------------------------------
    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        if node.module and node.module.split(".")[0] == "geodesk":
            module = importlib.import_module(node.module)
            for alias in node.names:
                if not has_member(module, alias.name):
                    self.ghosts.append(f"from {node.module} import {alias.name}")
                else:
                    self.known[alias.asname or alias.name] = getattr(module, alias.name)

    # --- assignments: remember the type of the value -------------------------
    def visit_Assign(self, node: ast.Assign) -> None:
        self.generic_visit(node)
        value_type = self.type_of(node.value)
        for target in node.targets:
            if isinstance(target, ast.Name) and value_type is not None:
                self.known[target.id] = value_type

    def type_of(self, node: ast.AST) -> object | None:
        if isinstance(node, ast.Call):
            callee = self.resolve(node.func)
            if inspect.isclass(callee):
                return callee
            if callable(callee):
                hints = typing.get_type_hints(callee, vars(geodesk.terrain))
                return hints.get("return")
        return None

    def resolve(self, node: ast.AST) -> object | None:
        if isinstance(node, ast.Name):
            return self.known.get(node.id)
        if isinstance(node, ast.Call):
            return self.type_of(node)
        if isinstance(node, ast.Attribute):
            owner = self.resolve(node.value)
            if owner is not None and has_member(owner, node.attr):
                return getattr(owner, node.attr, None)
        return None

    # --- uses: attributes and keyword arguments ------------------------------
    def visit_Attribute(self, node: ast.Attribute) -> None:
        self.generic_visit(node)
        owner = self.resolve(node.value)
        owner_type = owner if inspect.isclass(owner) or inspect.ismodule(owner) else None
        if owner_type is not None and getattr(owner_type, "__module__", "geodesk").startswith("geodesk"):
            if not has_member(owner_type, node.attr):
                self.ghosts.append(f"{owner_type.__name__}.{node.attr}")

    def visit_Call(self, node: ast.Call) -> None:
        self.generic_visit(node)
        callee = self.resolve(node.func)
        if callee is None or not getattr(callee, "__module__", "").startswith("geodesk"):
            return
        parameters = inspect.signature(callee).parameters
        accepts_any = any(p.kind is inspect.Parameter.VAR_KEYWORD for p in parameters.values())
        for keyword in node.keywords:
            if keyword.arg and keyword.arg not in parameters and not accepts_any:
                self.ghosts.append(f"{getattr(callee, '__qualname__', callee)}({keyword.arg}=...)")


def find_ghost_apis(docstring: str, context_class: type | None = None) -> list[str]:
    """Return every GeoDesk API that ``docstring`` mentions but the code does not define."""
    ghosts = [f":role:`{target}`" for target in SPHINX_ROLE.findall(docstring) if not resolve_role(target, context_class)]
    checker = ApiReferenceChecker()
    for snippet in code_snippets(docstring):
        checker.visit(ast.parse(snippet))
    return ghosts + checker.ghosts


def module_docstrings(module_source: str) -> list[tuple[str, type | None]]:
    """Every docstring in a module's source, with the class it belongs to."""
    tree = ast.parse(module_source)
    found = [(ast.get_docstring(tree) or "", None)]
    for class_node in (node for node in tree.body if isinstance(node, ast.ClassDef)):
        owner = getattr(geodesk.terrain, class_node.name, None)
        for node in [class_node, *ast.walk(class_node)]:
            if isinstance(node, (ast.ClassDef, ast.FunctionDef)) and ast.get_docstring(node):
                found.append((ast.get_docstring(node), owner))
    return found


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------
def test_checker_detects_an_invented_method():
    # Self-test: a known ghost must be reported, otherwise a green run means nothing.
    invented = '''
    >>> from geodesk.terrain import ElevationGrid
    >>> zaisan_dem = ElevationGrid.from_geotiff("zaisan.tif")
    '''
    assert find_ghost_apis(invented) == ["ElevationGrid.from_geotiff"]


def test_checker_detects_an_invented_keyword_argument():
    invented = '''
    >>> from geodesk import ContourGenerator
    >>> ContourGenerator(interval_m=1.0, smoothing=True)
    '''
    assert find_ghost_apis(invented) == ["ContourGenerator(smoothing=...)"]


@pytest.mark.parametrize("module", [geodesk.terrain, importlib.import_module("geodesk.errors")])
def test_published_docstrings_reference_only_real_apis(module):
    ghosts = [
        ghost
        for docstring, owner in module_docstrings(inspect.getsource(module))
        for ghost in find_ghost_apis(docstring, owner)
    ]
    assert ghosts == []


# Expected results are copied from audit/use_verify_cite_log.md; if a re-run of
# the checker disagrees with the log, the log is lying and this test fails.
AI_RUN_EXPECTED_GHOSTS = {
    "ai_docstring.py": [],
    "ai_runs/run2_sonnet_quickstart.py": [],
    "ai_runs/run3_haiku_quickstart.py": [],
}


@pytest.mark.parametrize("ai_file", sorted(AI_RUN_EXPECTED_GHOSTS))
def test_ai_outputs_match_use_verify_cite_log(ai_file):
    ai_source = (AUDIT_DIR / ai_file).read_text(encoding="utf-8")
    ghosts = sorted(
        ghost for docstring, owner in module_docstrings(ai_source) for ghost in find_ghost_apis(docstring, owner)
    )
    assert ghosts == AI_RUN_EXPECTED_GHOSTS[ai_file]


def test_checker_reads_indented_google_examples():
    # Negative control shaped like the run-3 output: plain indented code, no doctest prompts.
    invented = '''Load a DEM.

    Example:
        from geodesk.terrain import ElevationGrid, ContourGenerator
        grid = ElevationGrid.from_geotiff("dem.tif")
        layer = ContourGenerator(interval_m=1.0, smooth=True).generate(grid)
        layer.save("out.geojson")
    '''
    assert find_ghost_apis(invented) == [
        "ElevationGrid.from_geotiff",
        "ContourGenerator(smooth=...)",
        "ContourLayer.save",
    ]


@pytest.mark.parametrize("ai_file", sorted(AI_RUN_EXPECTED_GHOSTS))
def test_ai_outputs_were_actually_parsed(ai_file):
    # Guards against a vacuous pass: each AI output must yield code for the checker.
    ai_source = (AUDIT_DIR / ai_file).read_text(encoding="utf-8")
    assert any(code_snippets(docstring) for docstring, _ in module_docstrings(ai_source))
