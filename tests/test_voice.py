# /tests/test_voice.py
"""Unit tests for interfaces/voice.py.

There is no microphone, no speaker and no Whisper model in CI, so what is
tested is everything around them: wake-word matching including the
mishearings, the streaming speaker's sentence chunking, cache paths and the
graceful degradation when no audio stack exists at all.
"""

from __future__ import annotations

import pytest

from interfaces.voice import (
    Microphone,
    SpeechToText,
    StreamingSpeaker,
    TextToSpeech,
    VoiceInterface,
    WakeWordDetector,
)
from tests.conftest import run


@pytest.fixture
def detector(config):
    """A wake-word detector with dummy audio plumbing."""
    microphone = Microphone(config)
    stt = SpeechToText(config)
    return WakeWordDetector(config, microphone, stt)


# ------------------------------------------------------------------ wake word
def test_the_configured_wake_word_is_accepted(detector):
    assert detector.match_wake_word("jarvis") is not None


@pytest.mark.parametrize(
    "heard",
    ["jarvas", "jervis", "charvis", "harvis", "javis", "yarvis", "jarv"],
)
def test_common_mishearings_still_wake_him(detector, heard):
    # Whisper rarely spells the name right; refusing to wake would feel broken.
    assert detector.match_wake_word(heard) is not None


def test_unrelated_speech_does_not_wake_him(detector):
    assert detector.match_wake_word("what a lovely afternoon") is None
    assert detector.match_wake_word("") is None


def test_a_command_said_in_the_same_breath_is_kept(detector):
    match = detector.match_wake_word("Jarvis, what time is it?")
    assert match is not None
    assert match[1] == "what time is it"


def test_the_wake_word_alone_leaves_no_pending_command(detector):
    match = detector.match_wake_word("jarvis")
    assert match is not None
    assert match[1] == ""


def test_punctuation_and_case_are_ignored(detector):
    assert detector.match_wake_word("JARVIS!!!") is not None


def test_a_custom_wake_word_replaces_the_variants(config):
    config.set("voice.wake_word", "computer")
    detector = WakeWordDetector(config, Microphone(config), SpeechToText(config))
    assert detector.match_wake_word("computer, lights on") is not None
    assert detector.match_wake_word("jarvis") is None


# ----------------------------------------------------------------- streaming
def test_the_streaming_speaker_waits_for_a_sentence(config):
    speaker = StreamingSpeaker(TextToSpeech(config), min_chars=20)
    for token in ["Good", "evening"]:
        speaker.feed(token + " ")
    assert speaker.spoken == [], "half a sentence should not be spoken yet"


def test_the_streaming_speaker_emits_at_a_sentence_boundary(config):
    speaker = StreamingSpeaker(TextToSpeech(config), min_chars=10)
    speaker.feed("Good evening, sir. And how are you?")
    assert speaker.spoken, "a complete sentence should have been queued"
    assert speaker.spoken[0].endswith(".")


def test_code_blocks_are_not_read_aloud_mid_fence(config):
    speaker = StreamingSpeaker(TextToSpeech(config), min_chars=5)
    speaker.feed("Here you go: ```python\nprint('hi')\n")
    assert not any("print" in chunk for chunk in speaker.spoken)


def test_the_speaker_reports_what_it_actually_said(config):
    speaker = StreamingSpeaker(TextToSpeech(config), min_chars=10)
    speaker.feed("Good evening, sir. ")
    speaker.feed("The kettle is on.")
    # `text` is what was handed to the speaker, not what is still buffered —
    # after an interruption it has to reflect what the user really heard.
    assert "Good evening" in speaker.text
    assert speaker.buffer not in speaker.spoken


def test_cancelling_the_speaker_is_safe(config):
    speaker = StreamingSpeaker(TextToSpeech(config))
    speaker.feed("Something long enough to matter, sir.")
    speaker.cancel()


# ----------------------------------------------------------------------- tts
def test_tts_cache_paths_are_stable_and_filesystem_safe(config):
    tts = TextToSpeech(config)
    first = tts._cache_path("Good evening, sir.")
    assert first == tts._cache_path("Good evening, sir.")
    assert first != tts._cache_path("Good morning, sir.")
    assert first.suffix in {".mp3", ".wav"}


def test_speaking_without_an_audio_stack_returns_false_instead_of_raising(config):
    tts = TextToSpeech(config)
    assert run(tts.speak("")) is False


def test_listing_voices_never_raises(config):
    assert isinstance(run(TextToSpeech(config).list_voices("en")), list)


# --------------------------------------------------------------- microphone
def test_a_microphone_reports_failure_rather_than_crashing(config):
    microphone = Microphone(config)
    assert microphone.initialize() in (True, False)


def test_recording_without_a_device_returns_nothing(config):
    microphone = Microphone(config)
    if not microphone.initialize():
        assert microphone.record_seconds(0.1) is None


# --------------------------------------------------------------- interface
def test_the_voice_interface_assembles_from_config(config):
    voice = VoiceInterface(config)
    assert voice.tts is not None
    assert voice.stt is not None
    assert voice.microphone is not None


def test_the_voice_interface_reports_what_is_missing(config):
    voice = VoiceInterface(config)
    ready = run(voice.initialize())
    assert isinstance(ready, bool)


# ------------------------------------------------------- switching it off
def test_the_wake_word_can_be_switched_off(config):
    """`voice.engine: none` is a choice, not a failure to find an engine."""
    config.set("voice.engine", "none")
    detector = WakeWordDetector(config, Microphone(config), SpeechToText(config))
    assert run(detector.initialize()) == "none"


def test_a_blank_wake_word_means_no_wake_word(config):
    config.set("voice.wake_word", "")
    detector = WakeWordDetector(config, Microphone(config), SpeechToText(config))
    assert run(detector.initialize()) == "none"


@pytest.mark.parametrize("spelling", ["none", "off", "OFF", "disabled", "false"])
def test_every_way_of_saying_off_is_understood(config, spelling):
    config.set("voice.engine", spelling)
    detector = WakeWordDetector(config, Microphone(config), SpeechToText(config))
    assert run(detector.initialize()) == "none"


def test_the_doctor_calls_a_disabled_wake_word_healthy(config, tmp_path):
    from utils.doctor import diagnose

    config.set("voice.enabled", True)   # the audio checks are skipped otherwise
    config.set("voice.engine", "none")
    report = run(diagnose(config, root=tmp_path))
    wake = [item for item in report.findings if item.name == "Wake word"]
    assert wake, "the doctor should mention the wake word"
    assert wake[0].state != "fail"
    assert "choice" in wake[0].detail
