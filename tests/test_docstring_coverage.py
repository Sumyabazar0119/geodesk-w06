"""US-6.1: every public API symbol is fully documented (acceptance criteria).

Public = listed in ``geodesk.__all__`` plus their public methods/properties.
Each docstring needs a description, ``Args`` when the callable takes
parameters, ``Returns`` when it returns a value, ``Raises`` when the code
raises, and a runnable ``>>>`` example. Internal helpers (leading ``_``) must
instead carry a comment explaining why they are excluded.
"""
import ast
import inspect

import pytest

import geodesk


def public_symbols():
    for class_name in geodesk.__all__:
        public_class = getattr(geodesk, class_name)
        yield class_name, public_class
        for member_name, member in vars(public_class).items():
            if member_name.startswith("_") or not (callable(member) or isinstance(member, (property, classmethod))):
                continue
            yield f"{class_name}.{member_name}", member


def underlying_function(member):
    if isinstance(member, property):
        return member.fget
    if isinstance(member, (classmethod, staticmethod)):
        return member.__func__
    return member


def raises_anything(function):
    tree = ast.parse(inspect.cleandoc("\n" + inspect.getsource(function)))
    return any(isinstance(node, ast.Raise) for node in ast.walk(tree))


SYMBOLS = list(public_symbols())


@pytest.mark.parametrize("name,member", SYMBOLS, ids=[name for name, _ in SYMBOLS])
def test_public_symbol_is_fully_documented(name, member):
    docstring = inspect.getdoc(underlying_function(member)) or ""
    assert docstring.strip(), f"{name} has no description"
    assert ">>>" in docstring, f"{name} needs a runnable example"
    if inspect.isclass(member) or isinstance(member, property):
        return
    function = underlying_function(member)
    signature = inspect.signature(function)
    parameters = [p for p in signature.parameters if p not in ("self", "cls")]
    if parameters:
        assert "Args:" in docstring, f"{name} must document its parameters"
    if signature.return_annotation not in (None, "None", inspect.Signature.empty):
        assert "Returns:" in docstring, f"{name} must document its return value"
    if raises_anything(function):
        assert "Raises:" in docstring, f"{name} raises but documents no errors"


def test_internal_helpers_explain_their_exclusion():
    source = inspect.getsource(geodesk.terrain)
    for helper in ("_is_nodata", "_round_point", "_validate_interval", "_check_dem", "_trace_level", "_cell_segments"):
        definition_line = next(i for i, line in enumerate(source.splitlines()) if f"def {helper}(" in line)
        preceding = "\n".join(source.splitlines()[max(0, definition_line - 12):definition_line])
        assert "Internal" in preceding, f"{helper} needs a comment explaining why it is not public"


def test_public_symbol_count():
    assert len(SYMBOLS) == 18
