"""Static guards on how ``@tool`` is attached to methods.

A decorator applies to the function *immediately below* it. When a tool block
is written above the wrong ``def`` — easy to do when a private helper sits
between the decorator and its intended method — the public tool silently
disappears from the catalogue and the private helper is exposed in its place.
Nothing fails loudly: the module imports, the tests pass, and the assistant
simply answers "Unknown tool" forever after.

These checks parse the source rather than importing it, so they cover every
module regardless of which optional dependencies are installed.
"""

from __future__ import annotations

import ast
import pathlib
from typing import Iterator, List, Tuple

PROJECT_ROOT = pathlib.Path(__file__).resolve().parent.parent
SOURCE_DIRECTORIES = ("modules", "plugins")
FUNCTION_TYPES = (ast.FunctionDef, ast.AsyncFunctionDef)


def _decorated_tools() -> Iterator[Tuple[pathlib.Path, ast.AST, ast.Call]]:
    """Yield every ``(file, function, @tool call)`` triple in the source tree."""
    for directory in SOURCE_DIRECTORIES:
        for path in sorted((PROJECT_ROOT / directory).rglob("*.py")):
            if "pending" in path.parts:
                continue
            tree = ast.parse(path.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                if not isinstance(node, FUNCTION_TYPES):
                    continue
                for decorator in node.decorator_list:
                    if (
                        isinstance(decorator, ast.Call)
                        and getattr(decorator.func, "id", "") == "tool"
                    ):
                        yield path, node, decorator


def _keyword(decorator: ast.Call, name: str) -> ast.expr | None:
    """Return the value node of a keyword argument, when it is present."""
    for keyword in decorator.keywords:
        if keyword.arg == name:
            return keyword.value
    return None


def _tool_name(function: ast.AST, decorator: ast.Call) -> str:
    """The registered tool name: the explicit ``name=`` or the method name."""
    explicit = _keyword(decorator, "name")
    if isinstance(explicit, ast.Constant) and isinstance(explicit.value, str):
        return explicit.value
    return function.name  # type: ignore[attr-defined]


def test_no_private_method_is_decorated_as_a_tool() -> None:
    offenders: List[str] = []
    for path, function, _decorator in _decorated_tools():
        if function.name.startswith("_"):  # type: ignore[attr-defined]
            offenders.append(
                f"{path.relative_to(PROJECT_ROOT)}:{function.lineno} "  # type: ignore[attr-defined]
                f"@tool sits on the private helper {function.name!r} "  # type: ignore[attr-defined]
                "— it probably belongs on the method below it"
            )
    assert not offenders, "\n".join(offenders)


def test_examples_name_the_tool_they_document() -> None:
    """An example calling a different tool means the decorator drifted."""
    offenders: List[str] = []
    for path, function, decorator in _decorated_tools():
        name = _tool_name(function, decorator)
        examples = _keyword(decorator, "examples")
        if not isinstance(examples, ast.List) or not examples.elts:
            continue
        first = examples.elts[0]
        if not isinstance(first, ast.Constant) or not isinstance(first.value, str):
            continue
        text = first.value.strip()
        # Only judge examples written as a call: prose examples ("what time is
        # it?") are deliberate and say nothing about which method is decorated.
        if "(" not in text or " " in text.split("(", 1)[0]:
            continue
        called = text.split("(", 1)[0].strip()
        if called != name:
            offenders.append(
                f"{path.relative_to(PROJECT_ROOT)}:{function.lineno} "  # type: ignore[attr-defined]
                f"tool {name!r} shows an example calling {called!r}"
            )
    assert not offenders, "\n".join(offenders)


def test_declared_parameters_exist_on_the_signature() -> None:
    """Every declared param must be a real argument of the decorated method."""
    offenders: List[str] = []
    for path, function, decorator in _decorated_tools():
        params = _keyword(decorator, "params")
        if not isinstance(params, ast.Dict):
            continue
        arguments = function.args  # type: ignore[attr-defined]
        accepted = {
            argument.arg
            for argument in (
                list(getattr(arguments, "posonlyargs", []))
                + list(arguments.args)
                + list(arguments.kwonlyargs)
            )
        }
        if arguments.kwarg is not None:
            continue  # **kwargs accepts anything
        for key in params.keys:
            if not isinstance(key, ast.Constant) or not isinstance(key.value, str):
                continue
            if key.value not in accepted:
                offenders.append(
                    f"{path.relative_to(PROJECT_ROOT)}:{function.lineno} "  # type: ignore[attr-defined]
                    f"{_tool_name(function, decorator)!r} declares parameter "
                    f"{key.value!r}, which {function.name}() does not accept"  # type: ignore[attr-defined]
                )
    assert not offenders, "\n".join(offenders)
