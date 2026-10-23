"""Durable transcripts of completed turns, independent of session summaries."""
import sqlite3
from datetime import datetime, timezone
from core.data_paths import data_dir


def _connect():
    db = sqlite3.connect(data_dir() / 'conversations.db', timeout=10)
    db.execute('PRAGMA journal_mode=WAL')
    db.execute('CREATE TABLE IF NOT EXISTS turns (id INTEGER PRIMARY KEY, at TEXT NOT NULL, role TEXT NOT NULL, content TEXT NOT NULL)')
    return db


def record_turn(role, text):
    if role not in ('user', 'assistant') or not str(text).strip():
        return
    db = _connect()
    try:
        with db:
            db.execute('INSERT INTO turns(at,role,content) VALUES (?,?,?)',
                       (datetime.now(timezone.utc).isoformat(), role, str(text)))
    finally:
        db.close()


def find_turns(words, limit=5):
    words = list(dict.fromkeys(words))[:10]
    db = _connect()
    try:
        if words:
            escaped = ['%' + w.replace('\\', '\\\\').replace('%', '\\%').replace('_', '\\_') + '%' for w in words]
            sql = ' OR '.join("content LIKE ? ESCAPE '\\'" for _ in escaped)
            return db.execute('SELECT at,role,content FROM turns WHERE (' + sql + ') ORDER BY id DESC LIMIT ?', (*escaped, min(10, limit))).fetchall()
        return db.execute('SELECT at,role,content FROM turns ORDER BY id DESC LIMIT ?', (min(10, limit),)).fetchall()
    finally:
        db.close()
