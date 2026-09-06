# /tests/test_install.py
"""Unit tests for install.py, in particular its --everything mode.

The installer is the first thing a new user runs and the hardest thing to
test, because most of what it does is irreversible on the machine running it.
These tests cover the parts that are pure logic — argument parsing, the
capability list it writes, and the package tables — rather than the parts
that install software.
"""

from __future__ import annotations

import importlib.util
import sys

import pytest

from tests.conftest import PROJECT_ROOT


@pytest.fixture(scope="module")
def installer():
    """Import install.py as a module without running it."""
    spec = importlib.util.spec_from_file_location("jarvis_installer",
                                                  PROJECT_ROOT / "install.py")
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules["jarvis_installer"] = module
    spec.loader.exec_module(module)
    return module


# ------------------------------------------------------------------ arguments
def test_everything_is_accepted(installer):
    arguments = installer.parse_arguments(["--everything", "-y"])
    assert arguments.everything is True
    assert arguments.yes is True


def test_everything_implies_the_full_profile(installer):
    # --everything sets the profile itself; the parser leaves it unset.
    arguments = installer.parse_arguments(["--everything"])
    assert arguments.profile is None


def test_the_intrusive_extras_have_their_own_flags(installer):
    arguments = installer.parse_arguments(["--everything", "--blender", "--autostart"])
    assert arguments.blender is True
    assert arguments.autostart is True


def test_they_are_off_unless_asked_for(installer):
    arguments = installer.parse_arguments(["--everything", "-y"])
    assert arguments.blender is False
    assert arguments.autostart is False


# --------------------------------------------------------------- capabilities
def test_every_module_is_switched_on(installer):
    from core.config import DEFAULT_CONFIG

    for name in DEFAULT_CONFIG["modules"]:
        assert installer.EVERYTHING_ON[f"modules.{name}"] is True, name


def test_the_two_footguns_are_left_alone(installer):
    # Turning these on for someone is not "helpful", it is presumptuous.
    assert installer.EVERYTHING_ON.get("self_improve.allow_pip_install") is not True
    assert installer.EVERYTHING_ON.get("security.confirm_dangerous") is not False


def test_the_wake_word_is_not_forced_back_on(installer):
    assert "voice.engine" not in installer.EVERYTHING_ON
    assert "voice.wake_word" not in installer.EVERYTHING_ON


def test_every_key_it_writes_is_a_real_setting(installer):
    from core.config import DEFAULT_CONFIG

    def exists(dotted: str) -> bool:
        node = DEFAULT_CONFIG
        for part in dotted.split("."):
            if not isinstance(node, dict) or part not in node:
                return False
            node = node[part]
        return True

    unknown = [key for key in installer.EVERYTHING_ON if not exists(key)]
    assert not unknown, f"install.py writes settings that do not exist: {unknown}"


# ------------------------------------------------------------------- packages
def test_the_audio_libraries_cover_every_manager(installer):
    for manager in ("apt-get", "dnf", "pacman", "zypper", "brew"):
        assert installer.SYSTEM_PACKAGES[manager], manager
    # PortAudio and FFmpeg are the two that matter on Linux.
    apt = " ".join(installer.SYSTEM_PACKAGES["apt-get"])
    assert "portaudio" in apt and "ffmpeg" in apt


def test_the_package_manager_lookup_never_raises(installer):
    assert isinstance(installer.package_manager(), str)


def test_a_long_error_is_shortened_for_one_line(installer):
    assert len(installer.truncate_reason("x" * 400)) <= 90
    assert installer.truncate_reason("first line\nsecond line") == "first line"
    assert installer.truncate_reason("") == "unknown error"
