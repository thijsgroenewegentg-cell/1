# /tests/test_smart_assistant.py
"""Unit tests for modules/smart_assistant.py.

The interesting parts of this module are the ones that work with no model
running: arithmetic, unit conversion and the offline router. Anything that
genuinely needs the LLM is asserted only on its failure manners.
"""

from __future__ import annotations

import pytest

from modules.smart_assistant import LANGUAGE_CODES, SmartAssistant
from tests.conftest import run


@pytest.fixture
def smart(config):
    """A SmartAssistant with no reachable LLM."""
    return SmartAssistant(config)


@pytest.mark.parametrize(
    ("phrase", "expected"),
    [
        ("what is 15% of 240", "calculate"),
        ("convert 10 miles to km", "convert"),
        ("translate good morning into french", "translate"),
        ("define serendipity", "define"),
        ("write me a haiku about rain", "write_creative"),
        ("brainstorm names for a cat", "brainstorm"),
        ("compare python and rust", "compare"),
    ],
)
def test_offline_router_picks_the_right_tool(smart, phrase, expected):
    routed = smart.offline_router(phrase)
    assert routed is not None, f"{phrase!r} should route without an LLM"
    assert routed[0] == expected


@pytest.mark.parametrize(
    ("expression", "answer"),
    [("2 + 2", "4"), ("10 * 12", "120"), ("2 ** 10", "1024"), ("sqrt(144)", "12")],
)
def test_arithmetic_is_evaluated_locally(smart, expression, answer):
    result = run(smart.call_tool("calculate", {"expression": expression}))
    assert result.success
    # Output is thousands-separated for humans, so compare the parsed value.
    assert float(result.data["result"]) == pytest.approx(float(answer))


def test_percentages_of_a_number_work(smart):
    result = run(smart.call_tool("calculate", {"expression": "15% of 240"}))
    assert result.success
    assert "36" in result.output


def test_the_calculator_refuses_to_execute_code(smart):
    result = run(smart.call_tool(
        "calculate", {"expression": "__import__('os').system('echo pwned')"}
    ))
    assert not result.success


@pytest.mark.parametrize(
    ("value", "source", "target", "fragment"),
    [
        (10, "miles", "km", "16.09"),
        (100, "celsius", "fahrenheit", "212"),
        (1, "kg", "pounds", "2.2"),
        (1, "hour", "minutes", "60"),
    ],
)
def test_unit_conversion_uses_the_built_in_tables(smart, value, source, target, fragment):
    result = run(smart.call_tool(
        "convert", {"value": value, "from_unit": source, "to_unit": target}
    ))
    assert result.success
    assert fragment in result.output


def test_a_nonsense_conversion_fails_without_an_llm(smart):
    result = run(smart.call_tool(
        "convert", {"value": 5, "from_unit": "bananas", "to_unit": "sadness"}
    ))
    assert not result.success


def test_the_language_table_covers_the_common_requests():
    for language in ("dutch", "french", "german", "japanese", "spanish"):
        assert language in LANGUAGE_CODES


def test_answering_without_a_model_explains_itself(smart):
    result = run(smart.call_tool("answer", {"question": "what is the meaning of life"}))
    assert not result.success
    assert result.error


def test_translating_an_empty_string_is_refused(smart):
    result = run(smart.call_tool("translate", {"text": "", "target_language": "dutch"}))
    assert not result.success
