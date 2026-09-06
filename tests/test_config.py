# /tests/test_config.py
"""Unit tests for core/config.py.

Covers dotted access, disk round-trips, environment overrides, path
resolution and the alias layer that lets an alternatively-spelled
config.yaml drive the real settings.
"""

from __future__ import annotations

import sys
from typing import Iterator

import pytest

from core.config import DEFAULT_CONFIG, KEY_ALIASES, Config
from tests.conftest import PROJECT_ROOT


def test_dotted_keys_are_read_and_written(tmp_path):
    config = Config(data={}, path=tmp_path / "config.yaml")
    config.set("llm.model", "mistral")
    assert config.get("llm.model") == "mistral"


def test_a_missing_key_returns_the_default(tmp_path):
    config = Config(data={}, path=tmp_path / "config.yaml")
    assert config.get("nothing.here.at.all", "fallback") == "fallback"


def test_defaults_are_merged_under_user_settings(tmp_path):
    config = Config(data={"llm": {"model": "custom"}}, path=tmp_path / "config.yaml")
    assert config.get("llm.model") == "custom"
    assert config.get("llm.host") == DEFAULT_CONFIG["llm"]["host"]


def test_a_section_comes_back_as_a_dict(tmp_path):
    config = Config(data={}, path=tmp_path / "config.yaml")
    assert isinstance(config.section("llm"), dict)


def test_settings_survive_a_save_and_load(tmp_path):
    path = tmp_path / "config.yaml"
    first = Config(data={}, path=path)
    first.set("assistant.name", "FRIDAY")
    assert first.save()

    assert Config.load(path).get("assistant.name") == "FRIDAY"


def test_loading_a_missing_file_writes_the_defaults(tmp_path):
    path = tmp_path / "brand-new.yaml"
    config = Config.load(path)
    assert path.exists()
    assert config.get("llm.model")


def test_a_corrupt_file_falls_back_to_defaults(tmp_path):
    path = tmp_path / "broken.yaml"
    path.write_text("this: is: not: valid: yaml: at: all\n  - nope")
    assert Config.load(path).get("llm.host")


def test_relative_paths_resolve_against_the_config_file(tmp_path):
    config = Config(data={"paths": {"data": "data"}}, path=tmp_path / "config.yaml")
    assert config.path_for("data").is_absolute()
    assert str(config.path_for("data")).startswith(str(tmp_path))


def test_directories_are_created_on_demand(tmp_path):
    config = Config(data={"paths": {"data": str(tmp_path / "made-up")}},
                    path=tmp_path / "config.yaml")
    config.ensure_directories()
    assert (tmp_path / "made-up").is_dir()


def test_environment_variables_override_the_file(tmp_path, monkeypatch):
    monkeypatch.setenv("JARVIS_LLM_MODEL", "from-the-environment")
    assert Config(data={}, path=tmp_path / "config.yaml").get("llm.model") == (
        "from-the-environment"
    )


# ----------------------------------------------------------------- aliases
@pytest.mark.parametrize(
    ("alias", "canonical", "value"),
    [
        ("llm.base_url", "llm.host", "http://elsewhere:11434"),
        ("voice.stt_model", "voice.stt.model", "small"),
        ("voice.tts_voice", "voice.tts.voice", "en-GB-RyanNeural"),
        ("paths.data_dir", "paths.data", "./somewhere"),
        ("security.confirm_destructive", "security.confirm_dangerous", False),
        ("self_improve.can_modify_code", "self_improve.allow_code_edit", False),
        ("language", "assistant.language", "nl"),
    ],
)
def test_alias_keys_drive_the_real_setting(tmp_path, alias, canonical, value):
    data: dict = {}
    node = data
    parts = alias.split(".")
    for part in parts[:-1]:
        node = node.setdefault(part, {})
    node[parts[-1]] = value

    config = Config(data=data, path=tmp_path / "config.yaml")
    assert config.get(canonical) == value


def test_the_canonical_key_wins_when_both_are_present(tmp_path):
    config = Config(
        data={"llm": {"base_url": "http://alias", "host": "http://canonical"}},
        path=tmp_path / "config.yaml",
    )
    assert config.get("llm.host") == "http://canonical"


def test_quiet_hours_can_be_written_as_a_block(tmp_path):
    config = Config(
        data={"quiet_hours": {"enabled": True, "start": "23:00", "end": "07:00"}},
        path=tmp_path / "config.yaml",
    )
    assert config.get("productivity.quiet_hours") == "23:00-07:00"


def test_disabled_quiet_hours_become_an_empty_window(tmp_path):
    config = Config(
        data={"quiet_hours": {"enabled": False, "start": "23:00", "end": "07:00"}},
        path=tmp_path / "config.yaml",
    )
    assert config.get("productivity.quiet_hours") == ""


def test_every_alias_points_at_a_plausible_key():
    for alias, canonical in KEY_ALIASES.items():
        assert canonical, f"{alias} maps to nothing"
        assert " " not in canonical


def test_a_malformed_section_keeps_the_defaults(tmp_path):
    # `voice: yes` used to blank out every setting under voice.
    path = tmp_path / "broken.yaml"
    path.write_text("voice: yes\nllm:\n  - one\n  - two\n")
    config = Config.load(path)
    assert config.get("llm.model") == DEFAULT_CONFIG["llm"]["model"]
    assert config.get("voice.enabled") is not None


def test_an_empty_value_keeps_the_default(tmp_path):
    path = tmp_path / "empty-value.yaml"
    path.write_text("llm:\n  model: ~\n")
    assert Config.load(path).get("llm.model") == DEFAULT_CONFIG["llm"]["model"]


def test_quiet_hours_can_be_a_plain_string(tmp_path):
    path = tmp_path / "quiet.yaml"
    path.write_text('quiet_hours: "22:00-06:00"\n')
    assert Config.load(path).get("productivity.quiet_hours") == "22:00-06:00"


def test_every_setting_is_read_by_something():
    """A setting that nothing reads is a promise the assistant cannot keep.

    Matching on the leaf name alone was too generous — "enabled" appears in a
    dozen files, so ``web_ui.enabled`` passed this test for months while doing
    absolutely nothing. A setting now counts as read only if its dotted key
    appears, or its leaf appears in a file that also names its section.
    """
    sources = {}
    for folder in ("core", "modules", "utils", "interfaces", "plugins"):
        for path in (PROJECT_ROOT / folder).rglob("*.py"):
            sources[path] = path.read_text(encoding="utf-8")
    sources[PROJECT_ROOT / "main.py"] = (PROJECT_ROOT / "main.py").read_text()

    def walk(node: dict, prefix: str = "") -> Iterator[str]:
        for key, value in node.items():
            dotted = f"{prefix}.{key}" if prefix else key
            if isinstance(value, dict) and value and all(isinstance(k, str) for k in value):
                yield from walk(value, dotted)
            else:
                yield dotted

    #: Sections handed to another module wholesale, which then reads the leaves
    #: without ever naming the section: setup_logging(config.section("logging")).
    OWNERS = {
        "logging": ("utils/logger.py",),
        "security": ("utils/security.py",),
        "paths": ("core/config.py",),
        "user": ("core/config.py", "core/personality.py"),
        "database": ("core/memory.py",),
    }

    orphans = []
    for dotted in walk(DEFAULT_CONFIG):
        top, leaf = dotted.split(".")[0], dotted.split(".")[-1]
        quoted = (f'"{dotted}"', f"'{dotted}'")
        found = any(any(form in text for form in quoted) for text in sources.values())
        if not found:
            for path, text in sources.items():
                names_section = f'section("{top}")' in text or "path_for(" in text
                owner = any(str(path).endswith(name) for name in OWNERS.get(top, ()))
                if (names_section or owner) and (f'"{leaf}"' in text or f"'{leaf}'" in text):
                    found = True
                    break
        if not found:
            orphans.append(dotted)

    assert not orphans, f"settings nothing reads: {orphans}"


def test_every_setting_is_documented():
    """A knob nobody can explain is a knob nobody can use."""
    import subprocess

    result = subprocess.run(
        [sys.executable, "scripts/list_settings.py"],
        capture_output=True, text=True, cwd=str(PROJECT_ROOT),
    )
    assert result.returncode == 0, result.stdout + result.stderr
