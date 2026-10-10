"""Write audit/manual_vs_ai.diff: a per-symbol unified diff of docstrings only.

Comparing whole files would mix docstring changes with code reformatting, so
this extracts the docstring of every class/function and diffs them pairwise.

Usage (from the repo root): python audit/make_docstring_diff.py
"""
import ast
import difflib
from pathlib import Path

AUDIT_DIR = Path(__file__).resolve().parent


def docstrings_by_symbol(path):
    tree = ast.parse(path.read_text(encoding="utf-8"))
    found = {"<module>": ast.get_docstring(tree) or ""}
    for class_node in (node for node in tree.body if isinstance(node, ast.ClassDef)):
        found[class_node.name] = ast.get_docstring(class_node) or ""
        for node in class_node.body:
            if isinstance(node, ast.FunctionDef) and not node.name.startswith("_"):
                found[f"{class_node.name}.{node.name}"] = ast.get_docstring(node) or ""
    return found


def main():
    manual = docstrings_by_symbol(AUDIT_DIR / "manual_docstring.py")
    generated = docstrings_by_symbol(AUDIT_DIR / "ai_docstring.py")
    chunks = []
    for symbol in manual:
        chunks.extend(
            difflib.unified_diff(
                manual[symbol].splitlines(keepends=True),
                generated.get(symbol, "").splitlines(keepends=True),
                fromfile=f"manual/{symbol}",
                tofile=f"ai/{symbol}",
            )
        )
    output = "".join(line if line.endswith("\n") else line + "\n" for line in chunks)
    (AUDIT_DIR / "manual_vs_ai.diff").write_text(output, encoding="utf-8", newline="\n")
    print(f"{len(manual)} symbols compared, {output.count(chr(10))} diff lines")


if __name__ == "__main__":
    main()
