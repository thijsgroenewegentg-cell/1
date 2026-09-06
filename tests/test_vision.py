# /tests/test_vision.py
"""Unit tests for modules/vision.py — screenshots and image understanding."""

from __future__ import annotations

import pytest

from modules.vision import Vision
from tests.conftest import run


@pytest.fixture
def vision(config):
    """A Vision module with no vision model available."""
    return Vision(config)


@pytest.mark.parametrize(
    ("phrase", "expected"),
    [
        ("what's on my screen", "describe_screen"),
        ("read the text on screen", "read_screen"),
        ("describe the image at /tmp/photo.png", "describe_image"),
    ],
)
def test_offline_router_recognises_vision_requests(vision, phrase, expected):
    routed = vision.offline_router(phrase)
    assert routed is not None, f"{phrase!r} should route without an LLM"
    assert routed[0] == expected


def test_a_bare_this_image_means_the_screen(vision):
    # With no path in the sentence the only image JARVIS can see is the screen.
    routed = vision.offline_router("describe this image")
    assert routed is not None and routed[0] == "describe_screen"


def test_status_explains_what_is_missing(vision):
    result = run(vision.call_tool("vision_status", {}))
    assert result.success
    assert result.output.strip()


def test_describing_a_missing_image_fails_politely(vision, tmp_path):
    result = run(vision.call_tool("describe_image", {"path": str(tmp_path / "ghost.png")}))
    assert not result.success
    assert result.error


def test_describing_the_screen_without_a_display_does_not_crash(vision):
    result = run(vision.call_tool("describe_screen", {}))
    assert isinstance(result.success, bool)
    assert result.output or result.error


def test_comparing_two_missing_images_fails_politely(vision, tmp_path):
    result = run(vision.call_tool("compare_images", {
        "first": str(tmp_path / "a.png"), "second": str(tmp_path / "b.png")
    }))
    assert not result.success


def test_image_descriptions_are_untrusted(vision):
    # A screenshot can contain text that tries to talk to the model.
    assert vision.tools["describe_image"].untrusted


# --------------------------------------------- settings that were being ignored
def test_the_model_settings_are_actually_read(config):
    config.set("vision.max_tokens", 999)
    config.set("vision.temperature", 0.9)
    config.set("vision.fallback_models", ["moondream", "bakllava"])
    module = Vision(config)
    assert module.max_tokens == 999
    assert module.temperature == 0.9
    assert module.fallback_models == ["moondream", "bakllava"]


def test_screenshots_default_to_the_configured_folder(config):
    config.set("paths.screenshots", "data/pics")
    config.set("vision.screenshot_dir", "")
    # A blank override must not resolve to the project root.
    assert Vision(config).screenshot_dir.name == "pics"


def test_an_explicit_screenshot_folder_wins(config, tmp_path):
    config.set("vision.screenshot_dir", str(tmp_path / "shots"))
    assert Vision(config).screenshot_dir == tmp_path / "shots"


def test_a_missing_model_falls_back_to_an_installed_one(config):
    """Llava absent used to be a flat refusal, ignoring the fallback list."""
    class FakeLLM:
        available = True

        async def has_model(self, name: str) -> bool:
            return name == "moondream"

    config.set("vision.model", "llava")
    config.set("vision.fallback_models", ["moondream"])
    module = Vision(config)
    module.llm = FakeLLM()
    assert run(module._ensure_model()) is None
    assert module.model == "moondream"


def test_no_vision_model_at_all_lists_what_to_pull(config):
    class FakeLLM:
        available = True

        async def has_model(self, name: str) -> bool:
            return False

    module = Vision(config)
    module.llm = FakeLLM()
    complaint = run(module._ensure_model())
    assert complaint and "ollama pull" in complaint.lower()
