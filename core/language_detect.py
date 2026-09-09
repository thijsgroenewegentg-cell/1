# /core/language_detect.py
"""Fast, offline detection of the language the user is writing in.

Deterministic stopword scoring over the languages JARVIS supports (see
:data:`utils.language.LANGUAGES`). Enough to answer the one question that
matters for multilingual use: "is this Dutch or English or German …?" so the
reply language can follow the user without a model. Detecting nothing is a
valid answer — callers keep their previous/configured language then.
"""

from __future__ import annotations

import re
from typing import Dict, List

#: Common words per language, strongest signal first within each set.
_STOPWORDS: Dict[str, List[str]] = {
    "nl": [
        "ik", "je", "jij", "de", "het", "een", "en", "van", "dat", "wat",
        "niet", "voor", "met", "ben", "zijn", "heb", "hebt", "heeft", "we",
        "jullie", "mijn", "jouw", "waar", "hoe", "waarom", "welke", "maar",
        "ook", "aan", "op", "in", "dan", "als", "geen", "wel", "die", "is",
        "was", "waren", "kan", "kunnen", "moet", "moeten", "wil", "willen",
        "graag", "even", "nog", "nu", "straks", "vandaag", "gisteren",
        "morgen", "al", "alleen", "maar", "er", "naar", "bij", "uit",
        "om", "of", "toen", "later", "zeg", "zeggen", "bedoel", "doe",
        "doen", "geef", "maak", "zoek", "vind", "zet", "herinner", "voeg",
        "wie", "wiens", "hem", "haar", "hun", "ons", "onze", "jou",
        "waarom", "wilt", "zou", "zouden", "kunt", "geen",
    ],
    "en": [
        "the", "a", "an", "and", "of", "to", "you", "your", "that", "what",
        "is", "are", "was", "were", "not", "for", "with", "have", "has",
        "had", "do", "does", "did", "can", "could", "should", "would",
        "will", "want", "need", "please", "just", "me", "my", "this",
        "it", "on", "in", "at", "but", "also", "there", "they", "we",
        "tell", "make", "find", "set", "remind", "add", "show", "open",
        "search", "today", "yesterday", "tomorrow", "now", "then", "later",
    ],
    "de": [
        "ich", "du", "der", "die", "das", "und", "von", "mit", "nicht",
        "ein", "eine", "ist", "sind", "war", "waren", "habe", "hast", "hat",
        "wir", "ihr", "mein", "dein", "was", "wie", "wo", "warum", "welche",
        "kann", "können", "muss", "müssen", "will", "wollen", "bitte",
        "heute", "gestern", "morgen", "jetzt", "noch", "schon", "mach",
        "suche", "finde", "erinnere", "füge",
    ],
    "fr": [
        "je", "tu", "le", "la", "les", "et", "de", "des", "du", "un", "une",
        "est", "sont", "était", "étaient", "j'ai", "tu as", "il", "elle",
        "nous", "vous", "mon", "ma", "mes", "ton", "ta", "tes", "pas",
        "pour", "avec", "quoi", "comment", "où", "pourquoi", "quel",
        "peux", "peut", "dois", "doit", "veux", "veut", "s'il te plaît",
        "aujourd'hui", "hier", "demain", "maintenant", "encore", "fais",
        "cherche", "trouve", "rappelle", "ajoute",
    ],
    "es": [
        "yo", "tú", "el", "la", "los", "las", "y", "de", "un", "una",
        "es", "son", "era", "eran", "tengo", "tienes", "tiene", "nosotros",
        "vosotros", "mi", "mis", "tu", "tus", "no", "para", "con", "qué",
        "cómo", "dónde", "por qué", "cuál", "puedo", "puedes", "puede",
        "debo", "debes", "quiero", "quieres", "por favor", "hoy", "ayer",
        "mañana", "ahora", "todavía", "haz", "busca", "encuentra",
        "recuérdame", "añade",
    ],
    "it": [
        "io", "tu", "il", "lo", "la", "i", "gli", "le", "e", "di", "del",
        "un", "uno", "una", "è", "sono", "era", "erano", "ho", "hai", "ha",
        "noi", "voi", "mio", "mia", "tuo", "tua", "non", "per", "con",
        "cosa", "come", "dove", "perché", "quale", "posso", "puoi", "può",
        "devo", "devi", "voglio", "vuoi", "per favore", "oggi", "ieri",
        "domani", "adesso", "ancora", "fai", "cerca", "trova", "ricorda",
        "aggiungi",
    ],
}

#: Languages we ship stopwords for; others default to the caller's fallback.
_SUPPORTED = set(_STOPWORDS)

#: Words that are near-universal and must not count for anyone.
_AMBIGUOUS = {"de", "la", "en", "el", "il", "mi", "tu", "te", "me", "un",
              "una", "no", "ai"}


def _tokens(text: str) -> List[str]:
    return re.findall(r"[a-zà-ÿ']+", (text or "").lower())


def detect_language(text: str, fallback: str = "en") -> str:
    """Guess the language of ``text`` from stopword frequencies.

    Args:
        text: The user's utterance (needs a few real words to be reliable).
        fallback: The code to return when nothing is detected confidently.

    Returns:
        A language code from :data:`_SUPPORTED` (or ``fallback``).
    """
    tokens = _tokens(text)
    if len(tokens) < 3:
        return fallback
    scores: Dict[str, int] = {}
    for token in tokens:
        if token in _AMBIGUOUS:
            continue
        for code in _SUPPORTED:
            if token in _STOPWORDS[code]:
                scores[code] = scores.get(code, 0) + 1
    if not scores:
        return fallback
    ordered = sorted(scores.items(), key=lambda pair: pair[1], reverse=True)
    best, best_score = ordered[0]
    if best_score < 2:
        return fallback
    # A strong second language beats a weak first (a few German words in an
    # English sentence must not flip the reply language).
    second = ordered[1][1] if len(ordered) > 1 else 0
    if best_score < second + 1 and second >= 2:
        return fallback
    return best


def user_language(history: List[str], fallback: str = "en") -> str:
    """The language of a short conversation window (last non-empty turns).

    Args:
        history: Recent user texts, newest last.
        fallback: Code used when nothing is detected.

    Returns:
        The most frequent confident detection across the window.
    """
    counts: Dict[str, int] = {}
    for item in history[-6:]:
        item = (item or "").strip()
        if len(item) < 4:
            continue
        code = detect_language(item)
        if code in _SUPPORTED:
            counts[code] = counts.get(code, 0) + 1
    if not counts:
        return fallback
    return max(counts, key=lambda code: counts[code])


__all__ = ["detect_language", "user_language"]
