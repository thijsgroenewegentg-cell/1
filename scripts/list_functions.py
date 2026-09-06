# /scripts/list_functions.py
"""Regenerate ``docs/FUNCTIONS.md`` — an index of every function in JARVIS.

Run it from the project root after adding or renaming anything::

    python scripts/list_functions.py

It parses the source with :mod:`ast` rather than importing it, so it works
without the optional dependencies installed and can never execute project
code as a side effect.
"""

from __future__ import annotations

import ast
import pathlib
from typing import Dict, List, Optional, Tuple, Union

#: Directories that are never part of the public source tree.
SKIP = {".venv", "node_modules", "__pycache__", ".git", "plugins", "build", "dist"}

#: The order sections appear in, after the two entry points.
FOLDERS = ["core", "interfaces", "modules", "utils", "tests"]

FunctionNode = Union[ast.FunctionDef, ast.AsyncFunctionDef]
FUNCTION_TYPES = (ast.FunctionDef, ast.AsyncFunctionDef)


def signature(node: FunctionNode) -> str:
    """Render a function's declaration line as it appears in the source.

    Args:
        node: The parsed function.

    Returns:
        Something like ``async def speak(text: str) -> bool``.
    """
    arguments = node.args
    parts: List[str] = []
    positional = list(getattr(arguments, "posonlyargs", [])) + list(arguments.args)
    defaults: List[Optional[ast.expr]] = (
        [None] * (len(positional) - len(arguments.defaults)) + list(arguments.defaults)
    )
    for argument, default in zip(positional, defaults):
        text = argument.arg
        if argument.annotation is not None:
            text += f": {ast.unparse(argument.annotation)}"
        if default is not None:
            text += f" = {ast.unparse(default)}"
        parts.append(text)
    if arguments.vararg is not None:
        annotation = arguments.vararg.annotation
        parts.append(
            "*" + arguments.vararg.arg
            + (f": {ast.unparse(annotation)}" if annotation is not None else "")
        )
    for argument, keyword_default in zip(arguments.kwonlyargs, arguments.kw_defaults):
        text = argument.arg
        if argument.annotation is not None:
            text += f": {ast.unparse(argument.annotation)}"
        if keyword_default is not None:
            text += f" = {ast.unparse(keyword_default)}"
        parts.append(text)
    if arguments.kwarg is not None:
        annotation = arguments.kwarg.annotation
        parts.append(
            "**" + arguments.kwarg.arg
            + (f": {ast.unparse(annotation)}" if annotation is not None else "")
        )
    returns = f" -> {ast.unparse(node.returns)}" if node.returns is not None else ""
    keyword = "async def " if isinstance(node, ast.AsyncFunctionDef) else "def "
    return f"{keyword}{node.name}({', '.join(parts)}){returns}"


def first_line(node: ast.AST) -> str:
    """Return the first line of a node's docstring, or an empty string."""
    try:
        text = ast.get_docstring(node) or ""      # type: ignore[arg-type]
    except TypeError:
        return ""
    return text.strip().split("\n")[0].strip()


def markers(node: FunctionNode) -> str:
    """Render the decorators worth knowing about as inline badges."""
    names: List[str] = []
    for decorator in node.decorator_list:
        try:
            names.append(ast.unparse(decorator).split("(")[0].lstrip("@"))
        except Exception:
            continue
    badges = " **@tool**" if "tool" in names else ""
    for name in ("staticmethod", "classmethod", "property"):
        if name in names:
            badges += f" *{name}*"
    return badges


def render_function(node: FunctionNode, lines: List[str], indent: str = "",
                    nested: bool = False) -> None:
    """Append one function (and its inner functions) to the document.

    Args:
        node: The function to render.
        lines: The document being built, appended to in place.
        indent: Leading whitespace for nesting.
        nested: Whether this is an inner function.
    """
    bullet = "·" if nested else "-"
    text = f"{indent}{bullet} `{signature(node)}`{markers(node)}"
    summary = first_line(node)
    if summary:
        text += f" — {summary}"
    lines.append(text)
    for child in node.body:
        if isinstance(child, FUNCTION_TYPES):
            render_function(child, lines, indent + "  ", nested=True)


def sort_key(path: pathlib.Path) -> Tuple[int, int, str]:
    """Order entry points first, then core, interfaces, modules, utils, tests."""
    entry_points = {"main.py": 0, "install.py": 1}
    if str(path) in entry_points:
        return (0, entry_points[str(path)], str(path))
    top = path.parts[0]
    rank = FOLDERS.index(top) if top in FOLDERS else len(FOLDERS)
    return (1 + rank, 0, str(path))


def collect(root: pathlib.Path) -> List[pathlib.Path]:
    """Find every source file worth documenting, in reading order."""
    return sorted(
        (
            path.relative_to(root)
            for path in root.rglob("*.py")
            if not SKIP.intersection(path.relative_to(root).parts)
            and path.name not in {"conftest.py", "__init__.py"}
        ),
        key=sort_key,
    )


def build(root: pathlib.Path) -> Tuple[str, int]:
    """Build the whole document.

    Args:
        root: The project directory.

    Returns:
        The markdown text and the number of functions in it.
    """
    header = [
        "# /docs/FUNCTIONS.md",
        "",
        "# Every function in JARVIS",
        "",
        "Generated by `python scripts/list_functions.py`, which parses the source",
        "with `ast` rather than importing it. Inner helper functions are included",
        "and marked with `·`; methods the intent router can call are marked",
        "**@tool**.",
        "",
    ]
    body: List[str] = []
    counts: Dict[str, int] = {}
    total = 0

    for path in collect(root):
        tree = ast.parse((root / path).read_text(encoding="utf-8"))
        every = [n for n in ast.walk(tree) if isinstance(n, FUNCTION_TYPES)]
        if not every:
            continue
        counts[str(path)] = len(every)
        total += len(every)

        body += [f"## `{path}`", "", f"*{len(every)} functions*", ""]
        module_doc = first_line(tree)
        if module_doc:
            body += ["> " + module_doc, ""]

        top_level = [n for n in tree.body if isinstance(n, FUNCTION_TYPES)]
        for node in top_level:
            render_function(node, body)
        if top_level:
            body.append("")

        for klass in [n for n in tree.body if isinstance(n, ast.ClassDef)]:
            doc = first_line(klass)
            body.append(f"### `class {klass.name}`" + (f" — {doc}" if doc else ""))
            body.append("")
            methods = [n for n in klass.body if isinstance(n, FUNCTION_TYPES)]
            if not methods:
                body.append("*(no methods)*")
            for node in methods:
                render_function(node, body)
            body.append("")

    contents = ["## Contents", ""]
    for name, count in counts.items():
        anchor = name.replace("/", "").replace(".", "")
        contents.append(f"- [`{name}`](#{anchor}) — {count}")
    contents.append("")

    footer = ["---", "", f"**{total} functions across {len(counts)} files.**", ""]
    return "\n".join(header + contents + body + footer) + "\n", total


def main() -> int:
    """Write ``docs/FUNCTIONS.md`` and report what was written."""
    root = pathlib.Path(__file__).resolve().parent.parent
    text, total = build(root)
    target = root / "docs" / "FUNCTIONS.md"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(text, encoding="utf-8")
    print(f"{target.relative_to(root)}: {total} functions")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
