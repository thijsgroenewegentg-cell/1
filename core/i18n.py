"""Localisation and language policy for MARK.

MARK keeps tool names and safety contracts language-neutral, while user-facing
text, speech recognition, prompts and speech output follow the selected
language.  The default ``auto`` mode detects the language of the latest user
turn and currently supports English and Dutch without a cloud service.
"""
from __future__ import annotations

import re
from datetime import datetime
from typing import Any

LANGUAGE_OPTIONS = {
    "auto": "Automatic / Automatisch",
    "en": "English",
    "nl": "Nederlands",
}
LANGUAGE_NAMES = {"auto": "automatic", "en": "English", "nl": "Nederlands"}

# UI strings are deliberately keyed by their existing English source text. This
# lets the Qt shell be translated after construction without changing callbacks
# or action names. Unknown strings remain in English rather than disappearing.
_NL = {
    "◈  VISUAL INPUT": "◈  VISUELE INVOER",
    "◈  OLLAMA INITIALISATION": "◈  OLLAMA INITIALISATIE",
    "Local AI. No API key. No cloud account.": "Lokale AI. Geen API-sleutel. Geen cloudaccount.",
    "Install Ollama from ollama.com, then pull a model.": "Installeer Ollama via ollama.com en download daarna een model.",
    "OPERATING SYSTEM": "BESTURINGSSYSTEEM",
    "CONNECT TO OLLAMA": "VERBINDEN MET OLLAMA",
    "⚙  CUSTOMISE ASSISTANT": "⚙  ASSISTENT AANPASSEN",
    "ASSISTANT NAME": "NAAM VAN ASSISTENT",
    "YOUR NAME  (leave blank for default sir / efendim)": "JOUW NAAM  (leeg laten voor de standaard aanspreekvorm)",
    "ASSISTANT VOICE": "STEM VAN ASSISTENT",
    "PERSONALITY PROFILE": "PERSOONLIJKHEIDSPROFIEL",
    "UI COLOUR  —  drag the handle": "UI-KLEUR  —  versleep de knop",
    "DEFAULT": "STANDAARD",
    "▸  APPLY CHANGES": "▸  WIJZIGINGEN TOEPASSEN",
    "CANCEL": "ANNULEREN",
    "CLOSE": "SLUITEN",
    "SAVE": "OPSLAAN",
    "▸  SAVE": "▸  OPSLAAN",
    "LANGUAGE": "TAAL",
    "AUTOMATIC / AUTOMATISCH": "AUTOMATISCH / AUTOMATISCH",
    "PLUGIN MANAGER": "PLUGINBEHEER",
    "Changes take effect after the next MARK launch.": "Wijzigingen gelden na de volgende start van MARK.",
    "No plugins found in /plugins.": "Geen plugins gevonden in /plugins.",
    "＋  INSTALL LOCAL PLUGIN": "＋  LOKALE PLUGIN INSTALLEREN",
    "⚠  CONFIRMATION REQUIRED": "⚠  BEVESTIGING VEREIST",
    "Connect MARK to Blender MCP": "MARK met Blender MCP verbinden",
    "Install local plugin": "Lokale plugin installeren",
    "Restore file checkpoint": "Bestandscheckpoint herstellen",
    "Apply reviewed MARK patch": "Beoordeelde MARK-patch toepassen",
    "Clear session memory": "Sessiegeheugen wissen",
    "Approve": "Goedkeuren",
    "NO CHANGE HAS BEEN MADE YET  ·  ONE HUMAN CONFIRMATION REQUIRED": "ER IS NOG NIETS GEWIJZIGD  ·  ÉÉN MENSELIJKE BEVESTIGING VEREIST",
    "▸  CONFIRM": "▸  BEVESTIGEN",
    "🎧  AUDIO DEVICES": "🎧  AUDIOAPPARATEN",
    "LIVE DIAGNOSTICS": "LIVE DIAGNOSTIEK",
    "◉  TEST MICROPHONE": "◉  MICROFOON TESTEN",
    "●  RECORD 5s + PLAYBACK": "●  5 SEC OPNEMEN + AFSPELEN",
    "▸  APPLY": "▸  TOEPASSEN",
    "🧠  WHAT JARVIS REMEMBERS": "🧠  WAT MARK ONTHOUDT",
    "Nothing stored yet.": "Nog niets opgeslagen.",
    "◈  MARK CONTROL CENTER": "◈  MARK CONTROLECENTRUM",
    "LIVE STATE": "LIVE STATUS",
    "TASK PLAN": "TAKENSPLAN",
    "TIMELINE": "TIJDLIJN",
    "MEMORY": "GEHEUGEN",
    "WORKFLOWS": "WERKSTROMEN",
    "RUNTIME": "UITVOERING",
    "BLENDER": "BLENDER",
    "REFRESH": "VERVERSEN",
    "SHOW": "TONEN",
    "REPLAY — CONFIRM": "OPNIEUW — BEVESTIG",
    "DELETE": "VERWIJDEREN",
    "EDIT STEP": "STAP BEWERKEN",
    "TASK TRACE": "TAKENSPOOR",
    "ALERTS": "MELDINGEN",
    "POLICY": "BELEID",
    "SET PROFILE — CONFIRM": "PROFIEL INSTELLEN — BEVESTIG",
    "STATUS": "STATUS",
    "PLAN": "PLAN",
    "VISUAL REVIEW": "VISUELE CONTROLE",
    "OBJECTS": "OBJECTEN",
    "UNDO": "ONGEDAAN MAKEN",
    "CHECKPOINT": "CHECKPOINT",
    "RENDER PREVIEW": "RENDERVOORBEELD",
    "BROWSE": "BLADEREN",
    "RECORDING": "OPNAME",
    "LISTENING": "LUISTEREN",
    "PROCESSING": "VERWERKEN",
    "THINKING": "DENKEN",
    "SPEAKING": "SPREKEN",
    "SLEEPING": "SLAPEN",
    "MICROPHONE ACTIVE": "MICROFOON ACTIEF",
    "MICROPHONE MUTED": "MICROFOON GEDEMPT",
    "TRANSLATE": "VERTALEN",
    "SUMMARISE": "SAMENVATTEN",
    "EXPLAIN": "UITLEGGEN",
    "FIX": "REPAREREN",
    "REMOTE SESSION": "EXTERNE SESSIE",
    "CONNECTED": "VERBONDEN",
    "OFFLINE": "OFFLINE",
    "READY": "GEREED",
    "DEGRADED": "BEPERKT",
    "No active task plan.": "Geen actief takenplan.",
    "No task is currently running.": "Er wordt momenteel geen taak uitgevoerd.",
    "No task events recorded.": "Geen taakgebeurtenissen geregistreerd.",
    "No unread proactive alerts.": "Geen ongelezen proactieve meldingen.",
    "Speech and microphone enabled.": "Spraak en microfoon ingeschakeld.",
    "Microphone and speech muted.": "Microfoon en spraak gedempt.",
    "Response interrupted.": "Antwoord onderbroken.",
    "Ollama is offline, so I did not send that request. Start Ollama and try again.": "Ollama is offline, dus ik heb dat verzoek niet verstuurd. Start Ollama en probeer het opnieuw.",
}

_DUTCH_WORDS = {
    " de ", " het ", " een ", " en ", " niet ", " met ", " voor ", " van ", " naar ",
    " dat ", " dit ", " kan ", " graag ", " waarom ", " hoe ", " hallo ", " verbind ",
    " blender ", " maak ", " open ", " wil ", " mijn ", " jou ", " alsjeblieft ",
}
_ENGLISH_WORDS = {
    " the ", " and ", " with ", " this ", " that ", " please ", " what ", " why ",
    " how ", " open ", " connect ", " blender ", " make ", " my ", " can ",
}


def normalize_language(value: str | None) -> str:
    raw = str(value or "").strip().lower().replace("_", "-")
    if raw in {"nl", "nl-nl", "dutch", "nederlands", "hollands"}:
        return "nl"
    if raw in {"en", "en-us", "en-gb", "english", "engels"}:
        return "en"
    return "auto"


def language_name(value: str | None) -> str:
    return LANGUAGE_NAMES.get(normalize_language(value), LANGUAGE_NAMES["auto"])


def detect_language(text: str | None) -> str:
    """Small offline detector for the languages MARK currently ships with."""
    cleaned = re.sub(r"[^a-zA-ZÀ-ÿ\s]", " ", str(text or "").lower())
    value = f" {cleaned} "
    nl = sum(1 for word in _DUTCH_WORDS if word in value)
    en = sum(1 for word in _ENGLISH_WORDS if word in value)
    # Strong Dutch markers help with short commands such as "open Blender".
    if any(marker in value for marker in (" verbind ", " nederlands ", " alsjeblieft ", " graag ", " maak ")):
        nl += 2
    if nl >= max(2, en + 1):
        return "nl"
    return "en"


def effective_language(text: str | None = "", configured: str | None = "auto") -> str:
    selected = normalize_language(configured)
    return detect_language(text) if selected == "auto" else selected


def whisper_language(configured: str | None) -> str | None:
    selected = normalize_language(configured)
    return None if selected == "auto" else selected


def language_instruction(language: str | None) -> str:
    selected = normalize_language(language)
    if selected == "nl":
        return (
            "The active response language is Dutch (Nederlands). Respond naturally in Dutch, "
            "use Dutch number/date conventions, and do not switch to English unless the user asks."
        )
    if selected == "en":
        return "The active response language is English. Respond naturally in English unless the user asks for another language."
    return "Detect the language of the user's latest message and answer in that language. Dutch and English are fully supported."


def edge_voice(language: str | None, preferred: str | None = "") -> str:
    """Return a Microsoft Edge voice name or friendly voice label."""
    selected = normalize_language(language)
    voice = str(preferred or "").strip()
    if "-" in voice and voice.lower().endswith("neural"):
        return voice
    if selected == "nl":
        return {
            "Fenna": "nl-NL-FennaNeural", "Colette": "nl-NL-ColetteNeural", "Maarten": "nl-NL-MaartenNeural",
            "Jenny": "nl-NL-ColetteNeural", "Aria": "nl-NL-FennaNeural", "Ryan": "nl-NL-MaartenNeural",
        }.get(voice, "nl-NL-MaartenNeural")
    return {"Sonia": "en-GB-SoniaNeural", "Ryan": "en-GB-RyanNeural", "Jenny": "en-US-JennyNeural", "Aria": "en-US-AriaNeural"}.get(voice, "en-US-GuyNeural")


def tr(text: Any, language: str | None = None, **values: Any) -> str:
    source = str(text)
    selected = normalize_language(language)
    if selected == "auto":
        selected = "en"
    result = _NL.get(source, source) if selected == "nl" else source
    if values:
        try:
            return result.format(**values)
        except (KeyError, IndexError, ValueError):
            return result
    return result


def translate_widget_tree(root: Any, language: str | None = None) -> int:
    """Translate exact Qt labels while preserving source text for live switching."""
    selected = normalize_language(language)
    if selected == "auto":
        selected = "en"
    changed = 0
    try:
        from PyQt6.QtWidgets import QLabel, QPushButton, QLineEdit, QTabWidget, QWidget
        widgets = [root] + list(root.findChildren(QWidget))
        for widget in widgets:
            if isinstance(widget, (QLabel, QPushButton)):
                source = widget.property("mark_source_text")
                if source is None:
                    source = widget.text()
                    widget.setProperty("mark_source_text", source)
                value = tr(source, selected)
                if widget.text() != value:
                    widget.setText(value)
                    changed += 1
            elif isinstance(widget, QLineEdit):
                source = widget.property("mark_source_placeholder")
                if source is None:
                    source = widget.placeholderText()
                    widget.setProperty("mark_source_placeholder", source)
                value = tr(source, selected)
                if widget.placeholderText() != value:
                    widget.setPlaceholderText(value)
                    changed += 1
            if isinstance(widget, QTabWidget):
                for index in range(widget.count()):
                    source = widget.tabBar().tabData(index)
                    if source is None:
                        source = widget.tabText(index)
                        widget.tabBar().setTabData(index, source)
                    value = tr(source, selected)
                    if widget.tabText(index) != value:
                        widget.setTabText(index, value)
                        changed += 1
    except Exception:
        return changed
    return changed


def localized_day_part(language: str | None, hour: int | None = None) -> str:
    selected = normalize_language(language)
    h = datetime.now().hour if hour is None else int(hour)
    if selected == "nl":
        return "ochtend" if h < 12 else "middag" if h < 18 else "avond"
    return "morning" if h < 12 else "afternoon" if h < 18 else "evening"
