# /utils/language.py
"""One setting for the language JARVIS speaks, listens in and thinks in.

``assistant.language`` in ``config.yaml`` is the single knob. It drives three
things that would otherwise have to be configured separately and consistently:

* which Whisper model transcribes you — the ``.en`` models are English-only
  and silently mistranscribe everything else, so a non-English language must
  switch to the multilingual build;
* which free Edge-TTS neural voice answers you;
* the instruction in the system prompt that tells the model which language to
  reply in.

Anything explicitly set in ``voice.stt`` or ``voice.tts`` still wins — this
only fills in what you have not chosen yourself.
"""

from __future__ import annotations

from typing import Dict, List, NamedTuple, Optional


class Language(NamedTuple):
    """A supported language and its free voice defaults.

    Attributes:
        code: The two-letter code, e.g. ``nl``.
        english_name: The name in English, used in prompts.
        native_name: The name as its speakers write it.
        voices: Free Edge-TTS neural voices, masculine first.
    """

    code: str
    english_name: str
    native_name: str
    voices: List[str]

    @property
    def voice(self) -> str:
        """The default voice for this language."""
        return self.voices[0]


#: Every language with a free Edge-TTS voice that Whisper also handles well.
LANGUAGES: Dict[str, Language] = {
    "en": Language("en", "English", "English",
                   ["en-GB-RyanNeural", "en-GB-SoniaNeural", "en-US-GuyNeural"]),
    "nl": Language("nl", "Dutch", "Nederlands",
                   ["nl-NL-MaartenNeural", "nl-NL-ColetteNeural", "nl-BE-ArnaudNeural"]),
    "de": Language("de", "German", "Deutsch",
                   ["de-DE-ConradNeural", "de-DE-KatjaNeural"]),
    "fr": Language("fr", "French", "Français",
                   ["fr-FR-HenriNeural", "fr-FR-DeniseNeural"]),
    "es": Language("es", "Spanish", "Español",
                   ["es-ES-AlvaroNeural", "es-ES-ElviraNeural"]),
    "it": Language("it", "Italian", "Italiano",
                   ["it-IT-DiegoNeural", "it-IT-ElsaNeural"]),
    "pt": Language("pt", "Portuguese", "Português",
                   ["pt-PT-DuarteNeural", "pt-BR-AntonioNeural"]),
    "pl": Language("pl", "Polish", "Polski",
                   ["pl-PL-MarekNeural", "pl-PL-ZofiaNeural"]),
    "sv": Language("sv", "Swedish", "Svenska",
                   ["sv-SE-MattiasNeural", "sv-SE-SofieNeural"]),
    "da": Language("da", "Danish", "Dansk",
                   ["da-DK-JeppeNeural", "da-DK-ChristelNeural"]),
    "no": Language("no", "Norwegian", "Norsk",
                   ["nb-NO-FinnNeural", "nb-NO-PernilleNeural"]),
    "fi": Language("fi", "Finnish", "Suomi",
                   ["fi-FI-HarriNeural", "fi-FI-NooraNeural"]),
    "tr": Language("tr", "Turkish", "Türkçe",
                   ["tr-TR-AhmetNeural", "tr-TR-EmelNeural"]),
    "ru": Language("ru", "Russian", "Русский",
                   ["ru-RU-DmitryNeural", "ru-RU-SvetlanaNeural"]),
    "uk": Language("uk", "Ukrainian", "Українська",
                   ["uk-UA-OstapNeural", "uk-UA-PolinaNeural"]),
    "cs": Language("cs", "Czech", "Čeština",
                   ["cs-CZ-AntoninNeural", "cs-CZ-VlastaNeural"]),
    "ar": Language("ar", "Arabic", "العربية",
                   ["ar-EG-ShakirNeural", "ar-EG-SalmaNeural"]),
    "hi": Language("hi", "Hindi", "हिन्दी",
                   ["hi-IN-MadhurNeural", "hi-IN-SwaraNeural"]),
    "zh": Language("zh", "Chinese", "中文",
                   ["zh-CN-YunxiNeural", "zh-CN-XiaoxiaoNeural"]),
    "ja": Language("ja", "Japanese", "日本語",
                   ["ja-JP-KeitaNeural", "ja-JP-NanamiNeural"]),
    "ko": Language("ko", "Korean", "한국어",
                   ["ko-KR-InJoonNeural", "ko-KR-SunHiNeural"]),
}

#: Tags that mean the same language under a different name.
ALIASES: Dict[str, str] = {
    "nb": "no",      # Bokmål, the written form Edge-TTS labels its Norwegian voices with
    "nn": "no",      # Nynorsk
    "pt-br": "pt",
    "zh-tw": "zh",
    "zh-hk": "zh",
    "flemish": "nl",
    "mandarin": "zh",
    "castellano": "es",
}

#: Whisper models that only understand English.
ENGLISH_ONLY_SUFFIX = ".en"


def normalise(code: str) -> str:
    """Reduce any language tag to a supported two-letter code.

    ``nl-NL``, ``NL``, ``dutch`` and ``Nederlands`` all mean ``nl``.

    Args:
        code: Whatever the user put in the config file.

    Returns:
        A key of :data:`LANGUAGES`, defaulting to ``en``.
    """
    text = (code or "").strip().lower().replace("_", "-")
    if not text:
        return "en"
    for candidate in (ALIASES.get(text, ""), text.split("-")[0]):
        if candidate in LANGUAGES:
            return candidate
        if ALIASES.get(candidate, "") in LANGUAGES:
            return ALIASES[candidate]
    for language in LANGUAGES.values():
        if text in (language.english_name.lower(), language.native_name.lower()):
            return language.code
    return "en"


def resolve(code: str) -> Optional[Language]:
    """Look up a language, or ``None`` when the tag is not one we support.

    Unlike :func:`get` this never falls back to English, so callers can tell
    "the user asked for Klingon" apart from "the user asked for English".

    Args:
        code: Any language tag.

    Returns:
        The matching :class:`Language`, or ``None``.
    """
    text = (code or "").strip().lower().replace("_", "-")
    if not text:
        return None
    match = normalise(text)
    if match == "en" and text.split("-")[0] not in ("en",) and text not in (
        "english", ALIASES.get(text, "")
    ):
        return None
    return LANGUAGES[match]


def get(code: str) -> Language:
    """Look up a language, falling back to English.

    Args:
        code: Any language tag.

    Returns:
        The matching :class:`Language`.
    """
    return LANGUAGES[normalise(code)]


def is_supported(code: str) -> bool:
    """Report whether a tag names a language JARVIS has voices for."""
    return resolve(code) is not None


def voice_for(code: str, configured: str = "") -> str:
    """Choose the Edge-TTS voice to speak with.

    Args:
        code: The assistant's language.
        configured: An explicit ``voice.tts.voice``, which wins as long as it
            belongs to the same language.

    Returns:
        An Edge-TTS voice name.
    """
    language = get(code)
    chosen = (configured or "").strip()
    if chosen and normalise(chosen) == language.code:
        return chosen
    return language.voice


def whisper_model_for(code: str, configured: str = "") -> str:
    """Choose a Whisper model that can actually hear the language.

    ``base.en`` transcribes Dutch as gibberish rather than failing, which is
    the worst kind of wrong, so the English-only suffix is dropped whenever
    the language is not English.

    Args:
        code: The assistant's language.
        configured: The configured ``voice.stt.model``.

    Returns:
        A faster-whisper model name.
    """
    model = (configured or "base.en").strip() or "base.en"
    if normalise(code) == "en":
        return model
    if model.endswith(ENGLISH_ONLY_SUFFIX):
        return model[: -len(ENGLISH_ONLY_SUFFIX)]
    return model


def prompt_instruction(code: str) -> Optional[str]:
    """The system-prompt line that pins the reply language.

    Args:
        code: The assistant's language.

    Returns:
        An instruction, or ``None`` for English (the model's default).
    """
    language = get(code)
    if language.code == "en":
        return None
    return (
        f"Always reply in {language.english_name} ({language.native_name}), "
        "however the user writes to you, unless they explicitly ask for another "
        "language. Keep tool names, file paths and code exactly as they are."
    )


__all__ = [
    "ALIASES",
    "LANGUAGES",
    "Language",
    "get",
    "is_supported",
    "normalise",
    "prompt_instruction",
    "resolve",
    "voice_for",
    "whisper_model_for",
]
