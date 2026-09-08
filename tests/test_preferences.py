# /tests/test_preferences.py
"""Unit tests for core/preferences.py and its wiring into the brain.

The learning rule is deliberately conservative: a habit is only recorded
when the *same* preference-shaped request recurs, so JARVIS never mistakes
one-off details for how the user works.
"""

from __future__ import annotations

import json

from core.preferences import Preferences


def test_usage_is_counted_per_tool(tmp_path):
    prefs = Preferences(tmp_path / "prefs.json")
    prefs.observe("blender.render", {"blend_file": "x.blend", "samples": 32})
    prefs.observe("blender.render", {"blend_file": "y.blend", "samples": 32})
    prefs.observe("web_search.search", {"query": "cats"})
    assert prefs.tool_counts()["blender.render"] == 2
    assert prefs.tool_counts()["web_search.search"] == 1


def test_a_repeated_request_becomes_a_routine(tmp_path):
    prefs = Preferences(tmp_path / "prefs.json")
    params = {"samples": 64, "resolution_percent": 50}
    prefs.observe("blender.render", params)
    assert prefs.routines() == []          # one-off: nothing learned yet
    prefs.observe("blender.render", params)
    routines = prefs.routines()
    assert len(routines) == 1
    assert routines[0][0] == "blender.render"
    assert routines[0][1]["times"] == 1
    prefs.observe("blender.render", params)
    assert prefs.routines()[0][1]["times"] == 2


def test_a_different_request_resets_the_streak(tmp_path):
    prefs = Preferences(tmp_path / "prefs.json")
    prefs.observe("blender.render", {"samples": 64})
    prefs.observe("blender.render", {"samples": 128})   # changed mind
    prefs.observe("blender.render", {"samples": 64})
    assert prefs.routines() == []          # never two identical in a row


def test_noise_parameters_are_not_preferences(tmp_path):
    prefs = Preferences(tmp_path / "prefs.json")
    # blend_file / output paths change every time; they are not preferences.
    prefs.observe("blender.render", {"blend_file": "a.blend", "samples": 32})
    prefs.observe("blender.render", {"blend_file": "b.blend", "samples": 32})
    routines = prefs.routines()
    assert len(routines) == 1
    assert "blend_file" not in routines[0][1]["params"]


def test_summary_reads_as_advice_for_the_model(tmp_path):
    prefs = Preferences(tmp_path / "prefs.json")
    prefs.observe("blender.render",
                  {"animation": True, "samples": 128, "resolution_percent": 50})
    prefs.observe("blender.render",
                  {"animation": True, "samples": 128, "resolution_percent": 50})
    summary = prefs.summary()
    assert "50% preview resolution" in summary
    assert "the full animation" in summary
    assert "128" in summary
    # One recurrence (two identical requests) records the routine; a third
    # identical request shows it has now been seen twice as a routine.
    prefs.observe("blender.render",
                  {"animation": True, "samples": 128, "resolution_percent": 50})
    assert "seen 2 times" in prefs.summary()


def test_summary_is_empty_until_something_is_learned(tmp_path):
    prefs = Preferences(tmp_path / "prefs.json")
    assert prefs.summary() == ""


def test_preferences_survive_a_restart(tmp_path):
    path = tmp_path / "prefs.json"
    first = Preferences(path)
    first.observe("blender.render", {"samples": 96})
    first.observe("blender.render", {"samples": 96})

    second = Preferences(path)            # fresh instance = fresh session
    assert second.routines()[0][1]["params"] == {"samples": 96}
    assert second.tool_counts()["blender.render"] == 2


def test_a_corrupt_file_starts_clean(tmp_path):
    path = tmp_path / "prefs.json"
    path.write_text("{ this is not json", encoding="utf-8")
    prefs = Preferences(path)
    assert prefs.routines() == []
    prefs.observe("blender.render", {"samples": 32})
    assert json.loads(path.read_text())["tool_counts"]["blender.render"] == 1
