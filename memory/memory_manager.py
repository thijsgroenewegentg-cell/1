import hashlib
import json
import re
from datetime import datetime
from threading import Lock
from pathlib import Path
import sys


def get_base_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    return Path(__file__).resolve().parent.parent


BASE_DIR         = get_base_dir()
MEMORY_PATH      = BASE_DIR / "memory" / "long_term.json"
PROJECT_MEMORY_DIR = BASE_DIR / "memory" / "projects"
_lock            = Lock()
MAX_VALUE_LENGTH = 380


def _project_id(project_root: str | Path) -> tuple[Path, str]:
    """Return a stable, non-secret filename for a local project directory."""
    root = Path(project_root or ".").expanduser()
    try:
        root = root.resolve()
    except OSError:
        root = root.absolute()
    digest = hashlib.sha256(str(root).encode("utf-8", errors="replace")).hexdigest()[:16]
    label = re.sub(r"[^A-Za-z0-9._-]+", "-", root.name or "project").strip("-")[:48] or "project"
    return root, f"{label}-{digest}.json"


def load_project_context(project_root: str | Path) -> dict:
    """Load bounded context for one project without putting it in global memory."""
    root, filename = _project_id(project_root)
    path = PROJECT_MEMORY_DIR / filename
    default = {"root": str(root), "updated": "", "summary": "", "events": []}
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(value, dict):
            return default
        events = value.get("events", [])
        default.update({
            "root": str(value.get("root") or root),
            "updated": str(value.get("updated") or ""),
            "summary": str(value.get("summary") or "")[:700],
            "events": [item for item in events[-8:] if isinstance(item, dict)],
        })
    except (OSError, ValueError, TypeError):
        pass
    return default


def project_context_prompt(project_root: str | Path, limit: int = 1100) -> str:
    """Format project memory for the prompt; paths and entries stay bounded."""
    context = load_project_context(project_root)
    lines = [f"Project memory root: {context.get('root', '')}"]
    if context.get("summary"):
        lines.append(f"Summary: {context['summary']}")
    for event in context.get("events", [])[-5:]:
        if not isinstance(event, dict):
            continue
        label = str(event.get("label") or "task")[:80]
        status = str(event.get("status") or "note")[:30]
        detail = str(event.get("detail") or "")[:180]
        lines.append(f"- {label} [{status}]: {detail}")
    return "\n".join(lines)[:max(200, int(limit))]


def _safe_project_text(value: str, limit: int) -> str:
    text = re.sub(r"\s+", " ", str(value or ""))
    text = re.sub(
        r"(?i)\b(password|passcode|token|api[_ -]?key|secret|private[_ -]?key)\b\s*[:=]\s*\S+",
        r"\1=<redacted>",
        text,
    )
    return text[:limit]


def record_project_event(project_root: str | Path, label: str, status: str,
                          detail: str = "", summary: str = "") -> None:
    """Persist bounded task metadata, excluding source text and credentials."""
    root, filename = _project_id(project_root)
    now = datetime.now().isoformat(timespec="seconds")
    current = load_project_context(root)
    event = {
        "time": now,
        "label": _safe_project_text(label, 80),
        "status": _safe_project_text(status, 30),
        "detail": _safe_project_text(detail, 220),
    }
    current["root"] = str(root)
    current["updated"] = now
    if summary:
        current["summary"] = _safe_project_text(summary, 700)
    current["events"] = (current.get("events", []) + [event])[-8:]
    try:
        PROJECT_MEMORY_DIR.mkdir(parents=True, exist_ok=True)
        (PROJECT_MEMORY_DIR / filename).write_text(
            json.dumps(current, indent=2, ensure_ascii=False), encoding="utf-8"
        )
    except OSError as exc:
        print(f"[Memory] project context unavailable: {exc}")

# ── Why there are two very different numbers here ────────────────────────────
#
# There used to be one: MEMORY_MAX_CHARS = 2200, applied to the whole store. It
# was a *storage* limit, and it existed only because the entire memory was
# pasted into the system prompt on every connect — so growing the memory grew
# every single request. When it filled, _trim_to_limit() deleted the oldest
# entries and printed one line to a console nobody reads. A memory described as
# "deeply remembers projects, preferences and personal context" was in practice
# two pages long, and quietly forgot your sister's name after a few weeks.
#
# Storage and prompt budget are now separate concerns:
#
#   MEMORY_MAX_CHARS  — a runaway guard, not a feature limit. Nothing normal
#                       reaches it; a bug writing in a loop does.
#   PROMPT_CORE_CHARS — what actually rides in the system prompt every session.
#                       Smaller than the old whole-memory dump, so sessions
#                       start *faster* than before, not slower.
#
# Everything above the core stays on disk and is fetched on demand by the
# recall_memory tool — see search_memory() and format_memory_for_prompt().
MEMORY_MAX_CHARS  = 200_000
PROMPT_CORE_CHARS = 900
PROMPT_INDEX_CHARS = 420
# Most entries any one category may contribute to the core block, so a person
# with forty stored preferences still gets their sister into the prompt.
PROMPT_MAX_PER_CATEGORY = 6
_SECRET_VALUE_RE = re.compile(r"(?i)\b(password|passcode|token|api[_ -]?key|secret|private[_ -]?key|cookie)\b\s*[:=]\s*\S+")


def _expired(entry, today: str | None = None) -> bool:
    """Return whether an entry has an explicit expiry before today.

    Expired entries stay on disk for user inspection and possible correction,
    but are excluded from prompt influence and ordinary retrieval.
    """
    if not isinstance(entry, dict):
        return False
    expires = str(entry.get("expires", "") or "").strip()
    if not expires:
        return False
    today = today or datetime.now().strftime("%Y-%m-%d")
    return expires < today


def _entry_meta(entry, category: str = "") -> dict:
    if not isinstance(entry, dict):
        return {"scope": category, "source": "legacy", "confidence": "", "updated": "", "expires": "", "stale": False}
    return {
        "scope": str(entry.get("scope") or category),
        "source": str(entry.get("source") or "unknown"),
        "confidence": str(entry.get("confidence") or ""),
        "updated": str(entry.get("updated") or ""),
        "expires": str(entry.get("expires") or ""),
        "stale": _expired(entry),
    }


def preference_profile(include_stale: bool = False) -> list[dict]:
    """Return explicit user preferences with provenance and influence metadata."""
    memory = load_memory()
    rows = []
    for key, entry in (memory.get("preferences", {}) or {}).items():
        value = _entry_value(entry)
        if not value:
            continue
        meta = _entry_meta(entry, "preferences")
        if meta["stale"] and not include_stale:
            continue
        rows.append({"category": "preferences", "key": str(key), "value": value, **meta, "influence": "explicit preference"})
    rows.sort(key=lambda row: row.get("updated", ""), reverse=True)
    return rows


def _empty_memory() -> dict:
    return {
        "identity":      {},
        "preferences":   {},
        "projects":      {},
        "relationships": {},
        "wishes":        {},
        "notes":         {},
        "temporary":     {},
    }

def load_memory() -> dict:
    if not MEMORY_PATH.exists():
        return _empty_memory()
    with _lock:
        try:
            data = json.loads(MEMORY_PATH.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                base = _empty_memory()
                for key in base:
                    if key not in data or not isinstance(data.get(key), (dict, list)):
                        data[key] = {} if key != "sessions" else []
                # Temporary context is useful during a task but should not
                # silently become permanent memory after its expiry date.
                today = datetime.now().strftime("%Y-%m-%d")
                temporary = data.get("temporary", {})
                if isinstance(temporary, dict):
                    for key, entry in list(temporary.items()):
                        if isinstance(entry, dict) and entry.get("expires", "") and str(entry["expires"]) < today:
                            del temporary[key]
                return data
            return _empty_memory()
        except Exception as e:
            print(f"[Memory] ⚠️ Load error: {e}")
            return _empty_memory()

def _all_entries(memory: dict) -> list[tuple]:
    entries = []
    for cat, items in memory.items():
        if not isinstance(items, dict):
            continue
        for key, entry in items.items():
            if isinstance(entry, dict) and "value" in entry:
                entries.append((cat, key, entry))
    return entries


# Set by main.py so a trim can reach the activity log. Deleting something a
# person told you and mentioning it only on stdout is how a memory loses trust.
_trim_notifier = None


def set_trim_notifier(fn) -> None:
    """Register a callable(str) that surfaces trims to the user."""
    global _trim_notifier
    _trim_notifier = fn


def _trim_to_limit(memory: dict) -> dict:
    if len(json.dumps(memory, ensure_ascii=False)) <= MEMORY_MAX_CHARS:
        return memory
    entries = _all_entries(memory)
    entries.sort(key=lambda t: t[2].get("updated", "0000-00-00"))
    dropped = []
    for cat, key, _ in entries:
        if len(json.dumps(memory, ensure_ascii=False)) <= MEMORY_MAX_CHARS:
            break
        del memory[cat][key]
        dropped.append(f"{cat}/{key}")
        print(f"[Memory] 🗑️  Trimmed {cat}/{key}")
    if dropped and _trim_notifier:
        try:
            _trim_notifier(
                f"SYS: Memory full — forgot {len(dropped)} oldest entries "
                f"({', '.join(dropped[:3])}{'…' if len(dropped) > 3 else ''})"
            )
        except Exception:
            pass
    return memory

def save_memory(memory: dict) -> None:
    if not isinstance(memory, dict):
        return
    memory = _trim_to_limit(memory)
    MEMORY_PATH.parent.mkdir(parents=True, exist_ok=True)
    with _lock:
        MEMORY_PATH.write_text(
            json.dumps(memory, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )


def _truncate_value(val: str) -> str:
    if isinstance(val, str) and len(val) > MAX_VALUE_LENGTH:
        return val[:MAX_VALUE_LENGTH].rstrip() + "…"
    return val


def _recursive_update(target: dict, updates: dict) -> bool:
    changed = False
    for key, value in updates.items():
        if value is None:
            continue
        if isinstance(value, str) and not value.strip():
            continue
        if isinstance(value, dict) and "value" not in value:
            if key not in target or not isinstance(target[key], dict):
                target[key] = {}
                changed = True
            if _recursive_update(target[key], value):
                changed = True
        else:
            new_val  = _truncate_value(str(value["value"] if isinstance(value, dict) else value))
            if _SECRET_VALUE_RE.search(new_val):
                # Never persist a credential even when a plugin calls the
                # memory API directly instead of going through main.py.
                continue
            entry    = {"value": new_val, "updated": datetime.now().strftime("%Y-%m-%d")}
            if isinstance(value, dict):
                for meta_key in ("scope", "source", "confidence", "expires"):
                    if value.get(meta_key) not in (None, ""):
                        entry[meta_key] = str(value[meta_key])[:80]
            existing = target.get(key, {})
            if not isinstance(existing, dict) or existing.get("value") != new_val:
                target[key] = entry
                changed = True
    return changed


def update_memory(memory_update: dict) -> dict:
    if not isinstance(memory_update, dict) or not memory_update:
        return load_memory()
    memory = load_memory()
    if _recursive_update(memory, memory_update):
        save_memory(memory)
        print(f"[Memory] 💾 Saved: {list(memory_update.keys())}")
    return memory

def _entry_value(entry) -> str:
    """Accept both the {'value': ..., 'updated': ...} shape and a bare string,
    because early versions of the store wrote plain strings."""
    if isinstance(entry, dict):
        return str(entry.get("value", "") or "").strip()
    return str(entry or "").strip()


def _pretty(key: str) -> str:
    return key.replace("_", " ").strip()


# Identity is always in the prompt; these categories compete for the remaining
# budget by recency.
_CATEGORY_LABELS = {
    "preferences":   "Preferences",
    "projects":      "Active projects / goals",
    "relationships": "People in their life",
    "wishes":        "Wishes / plans",
    "notes":         "Notes",
    "temporary":     "Temporary task context",
}

_IDENTITY_FIELDS = ["name", "age", "birthday", "city", "job",
                    "language", "school", "nationality"]


def format_memory_for_prompt(memory: dict | None) -> str:
    """Build the memory block that goes into the system prompt.

    This used to dump everything. It now sends three things:

      1. IDENTITY  - always, in full. It is small, and it is wrong for the
         assistant to have to look up your name.
      2. RECENT    - the most recently updated entries from every other
         category, up to PROMPT_CORE_CHARS. Recency is the cheapest useful
         relevance signal available without embeddings.
      3. AN INDEX  - the *keys* of everything else, values omitted.

    Point 3 is what makes recall work at all. A model cannot decide to look
    something up if it does not know the thing exists: with only points 1 and 2,
    "who is Ayse?" would get "I don't know" while ayse_sister sat on disk
    unread. The index costs a few hundred characters and turns recall from a
    gamble into a lookup.

    Net effect on latency: this block is SMALLER than the old full dump, so
    every session connects with fewer tokens. Occasionally the model spends one
    extra round trip on recall_memory - covered by the acknowledgment it
    already speaks before any slow step."""
    if not memory:
        return ""

    core_lines: list[str] = []

    # 1. Identity - always, in full
    identity = memory.get("identity", {}) or {}
    for field in _IDENTITY_FIELDS:
        entry = identity.get(field)
        if _expired(entry):
            continue
        val = _entry_value(entry)
        if not val:
            continue
        if field == "language":
            # Labelled as an observation, not a setting. A bare "Language:
            # English" line written months ago reads like a standing order and
            # was one of the reasons a Turkish question came back in English.
            core_lines.append(
                f"Has spoken to you in: {val} (an observation about the past — "
                f"always answer in the language of their CURRENT message)")
        else:
            core_lines.append(f"{field.title()}: {val}")
    for key, entry in identity.items():
        if key in _IDENTITY_FIELDS:
            continue
        if _expired(entry):
            continue
        val = _entry_value(entry)
        if val:
            core_lines.append(f"{_pretty(key).title()}: {val}")

    # Explicit preferences are separated from incidental notes so the model can
    # tell a standing user preference from a transient observation. Provenance
    # stays visible and makes influence inspectable in the prompt/debug UI.
    explicit = []
    for key, entry in (memory.get("preferences", {}) or {}).items():
        if _expired(entry):
            continue
        value = _entry_value(entry)
        if value:
            explicit.append({"key": str(key), "value": value, **_entry_meta(entry, "preferences")})
    explicit.sort(key=lambda item: item.get("updated", ""), reverse=True)
    if explicit:
        core_lines.append("")
        core_lines.append("Explicit user preferences (scope and provenance matter):")
        for item in explicit[:PROMPT_MAX_PER_CATEGORY]:
            provenance = f"scope={item['scope']}; source={item['source']}"
            if item.get("confidence"):
                provenance += f"; confidence={item['confidence']}"
            core_lines.append(f"  - {_pretty(item['key']).title()}: {item['value']} ({provenance})")

    # Episodic context is deliberately short and date-labelled. It helps MARK
    # resume a project without turning a previous conversation into a standing
    # instruction; users can clear it through memory_control.
    sessions = memory.get("sessions", [])
    if isinstance(sessions, list):
        for session in sessions[-2:]:
            if isinstance(session, dict) and session.get("summary"):
                date = str(session.get("date", "recent"))
                core_lines.append(f"Recent session ({date}): {str(session['summary'])[:280]}")

    # 2. Everything else, most recently updated first
    rest: list[tuple[str, str, str, str]] = []   # (updated, cat, key, value)
    for cat in _CATEGORY_LABELS:
        if cat == "preferences":
            continue
        for key, entry in (memory.get(cat, {}) or {}).items():
            if _expired(entry):
                continue
            val = _entry_value(entry)
            if not val:
                continue
            updated = (entry.get("updated", "") if isinstance(entry, dict) else "") or "0000-00-00"
            rest.append((updated, cat, key, val))
    rest.sort(key=lambda t: t[0], reverse=True)

    used    = sum(len(l) + 1 for l in core_lines)
    shown: dict[str, list[str]] = {}
    overflow: dict[str, list[str]] = {}
    if len(explicit) > PROMPT_MAX_PER_CATEGORY:
        overflow["preferences"] = [_pretty(item["key"]) for item in explicit[PROMPT_MAX_PER_CATEGORY:]]

    # Recency decides order, but no single category may take the whole budget.
    # Without the cap, someone with forty stored preferences gets a prompt that
    # is forty preferences and not one person's name — the categories that
    # matter most in conversation are also the ones that change least often, so
    # pure recency systematically buries them.
    per_cat_used: dict[str, int] = {}
    for _updated, cat, key, val in rest:
        line = f"  - {_pretty(key).title()}: {val}"
        if (per_cat_used.get(cat, 0) < PROMPT_MAX_PER_CATEGORY
                and used + len(line) + 1 <= PROMPT_CORE_CHARS):
            shown.setdefault(cat, []).append(line)
            per_cat_used[cat] = per_cat_used.get(cat, 0) + 1
            used += len(line) + 1
        else:
            overflow.setdefault(cat, []).append(_pretty(key))

    # The index is a table of contents, so it is interleaved across categories
    # rather than continuing in recency order. Sorted by recency it would list
    # twenty-four preferences before the first relationship, and the one entry
    # the index exists for — the old fact the model has no other way to know
    # about — would fall off the end.
    indexed: list[str] = []
    if overflow:
        cats  = [c for c in _CATEGORY_LABELS if overflow.get(c)]
        cursor = {c: 0 for c in cats}
        while cats:
            for cat in list(cats):
                i = cursor[cat]
                if i >= len(overflow[cat]):
                    cats.remove(cat)
                    continue
                indexed.append(overflow[cat][i])
                cursor[cat] = i + 1

    for cat, label in _CATEGORY_LABELS.items():
        if shown.get(cat):
            core_lines.append("")
            core_lines.append(f"{label}:")
            core_lines.extend(shown[cat])

    if not core_lines and not indexed:
        return ""

    out = [
        "[WHAT YOU KNOW ABOUT THIS PERSON — use naturally, never recite like a list]",
        *core_lines,
    ]

    # 3. The index of what is on disk but not in this prompt
    if indexed:
        budget, names = PROMPT_INDEX_CHARS, []
        for n in indexed:
            if budget - len(n) - 2 < 0:
                break
            names.append(n)
            budget -= len(n) + 2
        if names:
            out.append("")
            out.append(
                "[ALSO REMEMBERED — values not shown here. Call recall_memory "
                "with a keyword to read any of these before saying you do not know]"
            )
            out.append(", ".join(names)
                       + (f" (+{len(indexed) - len(names)} more)"
                          if len(indexed) > len(names) else ""))

    return "\n".join(out) + "\n"


# ── Recall ────────────────────────────────────────────────────────────────────

def _score(query_words: list[str], cat: str, key: str, value: str) -> int:
    """Cheap lexical relevance. No embeddings, no network, no model call - this
    runs in well under a millisecond, which is the entire point: recall must
    cost one model round trip, never two."""
    hay_key = _pretty(key).lower()
    hay_val = value.lower()
    score   = 0
    for w in query_words:
        if not w:
            continue
        if w == hay_key:
            score += 10
        elif w in hay_key:
            score += 6
        if w in hay_val:
            score += 3
        value_words = set(re.findall(r"[\w-]+", hay_val))
        if any(token.startswith(w) or w.startswith(token) for token in value_words if len(token) > 2):
            score += 1
        if w in cat:
            score += 1
    return score


def search_memory_details(query: str, limit: int = 8, include_stale: bool = False) -> list[dict]:
    """Return inspectable relevance, scope and provenance for memory matches."""
    memory = load_memory()
    words = [w for w in re.split(r"[^\w]+", (query or "").lower()) if len(w) > 1]
    rows: list[dict] = []
    for cat, items in memory.items():
        if cat == "sessions" and isinstance(items, list):
            for position, entry in enumerate(items):
                if not isinstance(entry, dict):
                    continue
                key = str(entry.get("date", f"session_{position}"))
                val = str(entry.get("summary", "")).strip()
                if not val:
                    continue
                score = _score(words, cat, key, val) if words else 1
                if score > 0:
                    rows.append({"score": score, "category": "episodic", "key": key, "value": val,
                                 "scope": "episodic", "source": "session_summary", "confidence": "", "updated": key, "expires": "", "stale": False})
            continue
        if not isinstance(items, dict):
            continue
        for key, entry in items.items():
            val = _entry_value(entry)
            if not val:
                continue
            meta = _entry_meta(entry, cat)
            if meta["stale"] and not include_stale:
                continue
            score = _score(words, cat, key, val) if words else 1
            if score > 0:
                rows.append({"score": score, "category": cat, "key": str(key), "value": val, **meta,
                             "influence": "explicit preference" if cat == "preferences" else "retrieved memory"})
    rows.sort(key=lambda row: (-int(row.get("score", 0)), str(row.get("updated", "")), str(row.get("key", ""))))
    return rows[:max(1, int(limit))] if limit else rows


def search_memory(query: str, limit: int = 8, include_stale: bool = False) -> str:
    """Find stored facts and show why each result influenced retrieval."""
    rows = search_memory_details(query, limit=max(1, int(limit)) * 4, include_stale=include_stale)
    if not rows:
        return (f"Nothing stored about '{query}'." if query else "I have not stored anything about this person yet.")
    shown = rows[:max(1, int(limit))]
    head = f"Stored facts matching '{query}':" if query else "Everything currently stored:"
    lines = [head]
    for row in shown:
        provenance = f"scope={row.get('scope', row.get('category', ''))}; source={row.get('source', 'unknown')}"
        if row.get("confidence"):
            provenance += f"; confidence={row['confidence']}"
        if row.get("stale"):
            provenance += "; stale — not used for prompt influence"
        lines.append(f"{row.get('category')}/{_pretty(str(row.get('key')))}: {row.get('value')} [{provenance}; relevance={row.get('score', 0)}]")
    total = len(rows)
    if total > len(shown):
        lines.append(f"(+{total - len(shown)} more — search with a narrower keyword)")
    return "\n".join(lines)


def all_entries_for_ui() -> list[dict]:
    """Flat list for the memory panel: what JARVIS knows, and when it learned it.
    Sorted newest first so the panel opens on what changed most recently."""
    memory = load_memory()
    rows = []
    for cat, items in memory.items():
        if cat == "sessions" and isinstance(items, list):
            for position, entry in enumerate(items):
                if isinstance(entry, dict) and entry.get("summary"):
                    rows.append({"category": "episodic", "key": str(entry.get("date", f"session_{position}")),
                                 "value": str(entry["summary"]), "updated": str(entry.get("date", "")),
                                 "scope": "episodic", "expires": ""})
            continue
        if not isinstance(items, dict):
            continue
        for key, entry in items.items():
            val = _entry_value(entry)
            if not val:
                continue
            rows.append({
                "category": cat,
                "key":      key,
                "value":    val,
                "updated":  (entry.get("updated", "") if isinstance(entry, dict) else ""),
                "scope":    (entry.get("scope", cat) if isinstance(entry, dict) else cat),
                "source":   (entry.get("source", "unknown") if isinstance(entry, dict) else "legacy"),
                "confidence": (entry.get("confidence", "") if isinstance(entry, dict) else ""),
                "expires":  (entry.get("expires", "") if isinstance(entry, dict) else ""),
                "stale":    _expired(entry),
            })
    rows.sort(key=lambda r: (r["updated"] or "0000-00-00"), reverse=True)
    return rows

def remember(key: str, value: str, category: str = "notes") -> str:
    valid = {"identity", "preferences", "projects", "relationships", "wishes", "notes", "temporary"}
    if category not in valid:
        category = "notes"
    update_memory({category: {key: {"value": value}}})
    return f"Remembered: {category}/{key} = {value}"


def forget(key: str, category: str = "notes") -> str:
    memory = load_memory()
    if category in {"episodic", "sessions"}:
        sessions = memory.get("sessions", [])
        kept = [entry for entry in sessions if not (isinstance(entry, dict) and str(entry.get("date", "")) == str(key))]
        if len(kept) != len(sessions):
            memory["sessions"] = kept
            save_memory(memory)
            return f"Forgotten: episodic/{key}"
        return f"Not found: episodic/{key}"
    cat    = memory.get(category, {})
    if isinstance(cat, dict) and key in cat:
        del cat[key]
        memory[category] = cat
        save_memory(memory)
        return f"Forgotten: {category}/{key}"
    return f"Not found: {category}/{key}"


forget_memory = forget


# ── Session memory ─────────────────────────────────────────────────────────────

_SESSION_MAX = 3   # safety cap — in practice 0-1 entries after pop


def save_session_summary(summary: str, language: str = "") -> None:
    """Append a 1-2 sentence session summary to long_term.json['sessions']."""
    summary = (summary or "").strip()
    if not summary:
        return
    memory   = load_memory()
    sessions = memory.get("sessions", [])
    if not isinstance(sessions, list):
        sessions = []
    entry: dict = {
        "date":    datetime.now().strftime("%Y-%m-%d"),
        "summary": summary[:280],
    }
    if language:
        entry["language"] = language
    sessions.append(entry)
    memory["sessions"] = sessions[-_SESSION_MAX:]
    with _lock:
        MEMORY_PATH.parent.mkdir(parents=True, exist_ok=True)
        MEMORY_PATH.write_text(
            json.dumps(memory, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
    print(f"[Memory] 📝 Session saved ({entry['date']}): {summary[:60]}…")


def pop_last_session() -> dict | None:
    """
    Return AND remove the most recent session entry.
    Calling this consumes the entry so it is never repeated in future briefings.
    """
    with _lock:
        if not MEMORY_PATH.exists():
            return None
        try:
            memory   = json.loads(MEMORY_PATH.read_text(encoding="utf-8"))
            sessions = memory.get("sessions", [])
            if not isinstance(sessions, list) or not sessions:
                return None
            entry = sessions.pop()          # remove the last entry
            memory["sessions"] = sessions
            MEMORY_PATH.write_text(
                json.dumps(memory, indent=2, ensure_ascii=False),
                encoding="utf-8",
            )
            return entry
        except Exception as e:
            print(f"[Memory] ⚠️ pop_last_session error: {e}")
            return None