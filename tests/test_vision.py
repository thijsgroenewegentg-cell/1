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
