#!/usr/bin/env python3
"""Forbid nested calls and conditions inside function/method call arguments.

Rules:
  - No IfExp / BoolOp / Lambda as call arguments (app + tests)
  - No nested non-constructor Calls as call arguments (app only)

Allowed nested calls: CapWords constructors (FieldError(...), UUID(...), ...).
Skipped for nested-call rule: **/models.py, **/schemas.py.
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path

SKIP_NESTED_CALL_NAMES = frozenset({"models.py", "schemas.py", "check_call_style.py"})


def _call_attr_or_name(node: ast.Call) -> str | None:
    func = node.func
    if isinstance(func, ast.Name):
        return func.id
    if isinstance(func, ast.Attribute):
        return func.attr
    return None


def _is_constructor_call(node: ast.Call) -> bool:
    name = _call_attr_or_name(node)
    return bool(name) and name[:1].isupper()


class CallStyleVisitor(ast.NodeVisitor):
    def __init__(self, path: Path, *, check_nested_calls: bool) -> None:
        self.path = path
        self.check_nested_calls = check_nested_calls
        self.errors: list[str] = []

    def visit_Call(self, node: ast.Call) -> None:
        args: list[ast.AST] = list(node.args)
        args.extend(kw.value for kw in node.keywords if kw.value is not None)
        for arg in args:
            if isinstance(arg, ast.IfExp):
                self.errors.append(
                    f"{self.path}:{arg.lineno}: conditional expression not allowed "
                    "inside function call arguments"
                )
            elif isinstance(arg, ast.BoolOp):
                self.errors.append(
                    f"{self.path}:{arg.lineno}: boolean condition not allowed "
                    "inside function call arguments"
                )
            elif isinstance(arg, ast.Lambda):
                self.errors.append(
                    f"{self.path}:{arg.lineno}: lambda not allowed inside function call arguments"
                )
            elif (
                self.check_nested_calls
                and isinstance(arg, ast.Call)
                and not _is_constructor_call(arg)
            ):
                snippet = ast.unparse(arg)
                if len(snippet) > 80:
                    snippet = snippet[:77] + "..."
                self.errors.append(
                    f"{self.path}:{arg.lineno}: nested call not allowed inside "
                    f"function call arguments: {snippet}"
                )
        self.generic_visit(node)


def check_file(path: Path) -> list[str]:
    source = path.read_text(encoding="utf-8")
    tree = ast.parse(source, filename=str(path))
    under_app = "app" in path.parts
    check_nested = under_app and path.name not in SKIP_NESTED_CALL_NAMES
    visitor = CallStyleVisitor(path, check_nested_calls=check_nested)
    visitor.visit(tree)
    return visitor.errors


def _collect_paths(argv: list[str]) -> list[Path]:
    raw = [Path(a) for a in argv[1:]] if len(argv) > 1 else [Path("app"), Path("tests")]
    paths: list[Path] = []
    for item in raw:
        if item.is_dir():
            paths.extend(sorted(item.rglob("*.py")))
        elif item.is_file():
            paths.append(item)
    return paths


def main(argv: list[str]) -> int:
    paths = _collect_paths(argv)
    errors: list[str] = []
    checked = 0
    for path in paths:
        if not path.is_file() or path.suffix != ".py":
            continue
        checked += 1
        errors.extend(check_file(path))

    if errors:
        print("call-style check failed:")
        for err in errors:
            print(f"  {err}")
        print(f"\n{len(errors)} violation(s)")
        return 1

    print(f"call-style check passed ({checked} files)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
