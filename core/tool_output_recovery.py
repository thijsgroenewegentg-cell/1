"""Recover structured tool requests from local-model text output.

This module is intentionally a parser for MARK's already-advertised tool names;
it is not an executor and never accepts a new capability from model text.
"""
from __future__ import annotations

import json
import re
from typing import Callable


def _balanced_objects(text: str):
    depth = 0
    start = None
    quote = False
    escaped = False
    for index, char in enumerate(text or ""):
        if quote:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                quote = False
            continue
        if char == '"':
            quote = True
        elif char == "{":
            if depth == 0:
                start = index
            depth += 1
        elif char == "}" and depth:
            depth -= 1
            if depth == 0 and start is not None:
                yield start, index + 1, text[start:index + 1]
                start = None


def _call_from_object(obj: object, names: set[str]) -> bool:
    if not isinstance(obj, dict):
        return False
    candidates = []
    if isinstance(obj.get("tool_calls"), list):
        candidates.extend(obj["tool_calls"])
    else:
        candidates.append(obj)
    for candidate in candidates:
        if not isinstance(candidate, dict):
            continue
        for key in ("name", "tool", "function", "tool_name"):
            value = candidate.get(key, "")
            nested_name = value.get("name", "") if isinstance(value, dict) else value
            if str(nested_name).strip() in names:
                return True
        for key in names:
            if key in candidate:
                return True
    return False


def _parse_json_call(raw: str, names: set[str], parser: Callable[[str, set[str]], list[dict]]) -> list[dict]:
    try:
        obj = json.loads(raw)
    except Exception:
        return []
    if not _call_from_object(obj, names):
        return []
    # The existing parser owns Ollama-compatible argument normalization.
    return parser(raw, names)


def recover_tool_output(text: str, known_names, parser: Callable[[str, set[str]], list[dict]]) -> tuple[str, list[dict]]:
    """Return user-safe content and recovered calls from a model response."""
    value = str(text or "")
    names = {str(name) for name in (known_names or []) if str(name)}
    if not value or not names:
        return value.strip(), []

    calls = parser(value, names)
    if not calls:
        return value.strip(), []

    spans: list[tuple[int, int]] = []
    for start, end, raw in _balanced_objects(value):
        if _parse_json_call(raw, names, parser):
            spans.append((start, end))

    # Remove slash-prefixed tool markers and their balanced JSON object. The
    # object span is already covered; this removes only the marker immediately
    # preceding it.
    for start, end in list(spans):
        prefix = value[max(0, start - 120):start]
        marker = re.search(r"/(?:" + "|".join(re.escape(name) for name in sorted(names, key=len, reverse=True)) + r")\s*$", prefix)
        if marker:
            spans.append((max(0, start - len(prefix) + marker.start()), start))

    cleaned = value
    for start, end in sorted(set(spans), reverse=True):
        cleaned = cleaned[:start] + " " + cleaned[end:]
    cleaned = re.sub(r"<\/?(?:tool_call|function_call)>", "", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"```(?:json)?", "", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"\s+", " ", cleaned).strip(" \n:;,-")
    return cleaned, calls
