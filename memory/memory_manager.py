import json
import re
from datetime import datetime
from pathlib import Path
import sys
from core.data_paths import data_dir
from core.atomic_storage import write_json
from core.store_lock import StoreLock


def get_base_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    return Path(__file__).resolve().parent.parent


BASE_DIR         = get_base_dir()
LEGACY_MEMORY_PATH = BASE_DIR / "memory" / "long_term.json"
MEMORY_PATH = data_dir() / "memory" / "long_term.json"
_lock = StoreLock(lambda: MEMORY_PATH.with_suffix(".lock"))
MAX_VALUE_LENGTH = 380

# Storage is not trimmed to fit model context. Prompt budgets remain bounded;
# full facts and session summaries stay on disk and are searched on demand.
MEMORY_MAX_CHARS = 200_000  # compatibility only; no automatic deletion
PROMPT_CORE_CHARS = 900
PROMPT_INDEX_CHARS = 420
# Most entries any one category may contribute to the core block, so a person
# with forty stored preferences still gets their sister into the prompt.
PROMPT_MAX_PER_CATEGORY = 6

def _empty_memory() -> dict:
    return {
        "identity":      {},
        "preferences":   {},
        "projects":      {},
        "relationships": {},
        "wishes":        {},
        "notes":         {},
    }

def load_memory() -> dict:
    with _lock:
        backup = MEMORY_PATH.with_suffix(".json.bak")
        if not MEMORY_PATH.exists() and not backup.exists() and LEGACY_MEMORY_PATH.exists():
            # Copy once. Leave the old file intact and never overwrite an existing store.
            legacy = json.loads(LEGACY_MEMORY_PATH.read_text(encoding="utf-8"))
            if not isinstance(legacy, dict):
                raise ValueError("Formato de memória antiga inválido; arquivo original preservado.")
            write_json(MEMORY_PATH, legacy)
        if not MEMORY_PATH.exists() and not backup.exists():
            return _empty_memory()
        try:
            data = json.loads(MEMORY_PATH.read_text(encoding="utf-8"))
            if not isinstance(data, dict):
                raise ValueError("Memória inválida")
        except (ValueError, OSError) as error:
            backup = MEMORY_PATH.with_suffix('.json.bak')
            if not backup.exists():
                raise RuntimeError("Memória danificada; não será substituída por uma memória vazia.") from error
            data = json.loads(backup.read_text(encoding="utf-8"))
            if not isinstance(data, dict):
                raise RuntimeError("Memória e backup inválidos; arquivos preservados.")
            print("[Memory] Recuperada a cópia de segurança; arquivo danificado preservado até a próxima gravação.")
        for key, value in _empty_memory().items():
            data.setdefault(key, value)
        return data


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
    # Prompt budget is enforced separately. Never delete old facts to fit it.
    return memory


def save_memory(memory: dict) -> None:
    if not isinstance(memory, dict):
        raise ValueError("A memória precisa ser um objeto JSON.")
    with _lock:
        if MEMORY_PATH.exists():
            try:
                previous = json.loads(MEMORY_PATH.read_text(encoding="utf-8"))
                if isinstance(previous, dict):
                    write_json(MEMORY_PATH.with_suffix('.json.bak'), previous)
            except (ValueError, OSError):
                # Keep the last good backup instead of replacing it with corruption.
                pass
        write_json(MEMORY_PATH, memory)


def _truncate_value(val: str) -> str:
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
            entry    = {"value": new_val, "updated": datetime.now().strftime("%Y-%m-%d")}
            existing = target.get(key, {})
            if not isinstance(existing, dict) or existing.get("value") != new_val:
                target[key] = entry
                changed = True
    return changed


def update_memory(memory_update: dict) -> dict:
    with _lock:
        memory = load_memory()
        if isinstance(memory_update, dict) and _recursive_update(memory, memory_update):
            save_memory(memory)
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
        val = _entry_value(identity.get(field))
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
        val = _entry_value(entry)
        if val:
            core_lines.append(f"{_pretty(key).title()}: {val}")

    # 2. Everything else, most recently updated first
    rest: list[tuple[str, str, str, str]] = []   # (updated, cat, key, value)
    for cat in _CATEGORY_LABELS:
        for key, entry in (memory.get(cat, {}) or {}).items():
            val = _entry_value(entry)
            if not val:
                continue
            updated = (entry.get("updated", "") if isinstance(entry, dict) else "") or "0000-00-00"
            rest.append((updated, cat, key, val))
    rest.sort(key=lambda t: t[0], reverse=True)

    used    = sum(len(l) + 1 for l in core_lines)
    shown: dict[str, list[str]] = {}
    overflow: dict[str, list[str]] = {}

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

    return ("\n".join(out) + "\n")[:2200]


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
        if w in cat:
            score += 1
    return score


def search_memory(query: str, limit: int = 8) -> str:
    """Find stored facts matching `query`. Backs the recall_memory tool.

    An empty query is treated as "show me everything you know", capped - the
    model asks that when the user says "what do you remember about me?"."""
    memory = load_memory()
    words  = [w for w in re.split(r"[^\w]+", (query or "").lower()) if len(w) > 1]

    rows: list[tuple[int, str, str, str]] = []
    for cat, items in memory.items():
        if not isinstance(items, dict):
            continue                     # skip 'sessions', which is a list
        for key, entry in items.items():
            val = _entry_value(entry)
            if not val:
                continue
            s = _score(words, cat, key, val) if words else 1
            if s > 0:
                rows.append((s, cat, key, val))

    for index, entry in enumerate(memory.get("sessions", [])):
        if isinstance(entry, dict):
            value = str(entry.get('summary', ''))
            score = _score(words, 'sessions', str(entry.get('date', '')), value) if words else 1
            if score > 0:
                rows.append((score, 'sessions', str(entry.get('date', index)), value))
    from memory.conversation_store import find_turns
    for at, role, text in find_turns(words, limit=limit):
        rows.append((1, 'conversation', at, role + ': ' + text[:1800]))
    if not rows:
        return (f"Nothing stored about '{query}'." if query
                else "I have not stored anything about this person yet.")

    rows.sort(key=lambda r: (-r[0], r[2]))
    lines = [f"{cat}/{_pretty(key)}: {val}" for _s, cat, key, val in rows[:max(1, limit)]]
    head  = (f"Stored facts matching '{query}':" if query
             else "Everything currently stored:")
    more  = (f"\n(+{len(rows) - len(lines)} more — search with a narrower keyword)"
             if len(rows) > len(lines) else "")
    return head + "\n" + "\n".join(lines) + more


def all_entries_for_ui() -> list[dict]:
    """Flat list for the memory panel: what JARVIS knows, and when it learned it.
    Sorted newest first so the panel opens on what changed most recently."""
    memory = load_memory()
    rows = []
    for cat, items in memory.items():
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
            })
    rows.sort(key=lambda r: (r["updated"] or "0000-00-00"), reverse=True)
    return rows

def remember(key: str, value: str, category: str = "notes") -> str:
    valid = {"identity", "preferences", "projects", "relationships", "wishes", "notes"}
    if category not in valid:
        category = "notes"
    update_memory({category: {key: {"value": value}}})
    return f"Remembered: {category}/{key} = {value}"


def forget(key: str, category: str = "notes") -> str:
    with _lock:
        memory = load_memory()
        cat = memory.get(category, {})
        if key in cat:
            del cat[key]
            save_memory(memory)
            return f"Forgotten: {category}/{key}"
        return f"Not found: {category}/{key}"


forget_memory = forget


# ── Session memory ─────────────────────────────────────────────────────────────

# Session summaries are retained; presented flags only control the briefing.


def save_session_summary(summary: str, language: str = "") -> None:
    if not (summary or "").strip():
        return
    with _lock:
        memory = load_memory()
        sessions = memory.get("sessions", [])
        if not isinstance(sessions, list):
            sessions = []
        sessions.append({"date": datetime.now().isoformat(timespec='seconds'),
                         "summary": summary, "language": language, "presented": False})
        memory["sessions"] = sessions
        save_memory(memory)


def pop_last_session() -> dict | None:
    # Preserve history; presented marks a briefing as consumed without deleting it.
    with _lock:
        memory = load_memory()
        sessions = memory.get("sessions", [])
        if not isinstance(sessions, list):
            return None
        pending = [item for item in sessions if isinstance(item, dict) and not item.get('presented')]
        if not pending:
            return None
        result = dict(pending[-1])
        for item in pending:
            item['presented'] = True
        save_memory(memory)
        return result
