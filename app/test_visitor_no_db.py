"""
Guard: the visitor routes (modes 2A/2B) must never import the DB layer.

AST-based on purpose: a naive `"app.database" in source` substring check gives
a FALSE POSITIVE, because the module's own docstring names those modules in
prose ("must never import app.database or app.models"). Parsing real import
nodes is the only correct way to assert this.
"""
import ast
import os

_FORBIDDEN = ("app.database", "app.models")
_FILES = ["app/routers/visitor.py", "app/visitor_sample.py"]


def _real_imports(path):
    tree = ast.parse(open(path, encoding="utf-8").read())
    names = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names += [a.name for a in node.names]
        elif isinstance(node, ast.ImportFrom):
            names.append(node.module or "")
    return names


def test_visitor_routes_never_import_db():
    for rel in _FILES:
        path = os.path.join(os.path.dirname(os.path.dirname(__file__)), rel)
        imports = _real_imports(path)
        bad = [m for m in imports if any(f in m for f in _FORBIDDEN)]
        assert not bad, f"{rel} imports forbidden DB module(s): {bad}"


if __name__ == "__main__":
    test_visitor_routes_never_import_db()
    print("PASS: visitor routes import no DB layer")
