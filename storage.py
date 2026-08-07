# storage.py — local SQLite persistence for session history.
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

# Anchored to this file, not the process CWD, so the history DB is always the
# same file no matter where the server was started from.
DB_PATH = str(Path(__file__).resolve().parent / "speakwell.db")

SCORE_KEYS = ["filler_words", "pace_pauses", "clarity_structure", "confidence_tone"]

SCORE_MIN, SCORE_MAX = 0, 100

# Database files whose schema we have already ensured this process.
_initialized: set[str] = set()


def init_db() -> None:
    conn = sqlite3.connect(DB_PATH)
    try:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS sessions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                created_at TEXT NOT NULL,
                mode TEXT NOT NULL,
                label TEXT,
                filler_words INTEGER,
                pace_pauses INTEGER,
                clarity_structure INTEGER,
                confidence_tone INTEGER
            )
            """
        )
        conn.commit()
    finally:
        conn.close()


def _connect() -> sqlite3.Connection:
    """Open the history DB, creating the schema once per database file."""
    if DB_PATH not in _initialized:
        init_db()
        _initialized.add(DB_PATH)
    return sqlite3.connect(DB_PATH)


def _score(value) -> int | None:
    """Coerce a model-supplied score into an int in 0-100, or None."""
    try:
        return max(SCORE_MIN, min(SCORE_MAX, int(value)))
    except (TypeError, ValueError):
        return None


def save_session(mode: str, label: str, scores: dict) -> None:
    conn = _connect()
    try:
        conn.execute(
            "INSERT INTO sessions (created_at, mode, label, filler_words, "
            "pace_pauses, clarity_structure, confidence_tone) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                datetime.now(timezone.utc).isoformat(),
                mode,
                label,
                *(_score(scores.get(k)) for k in SCORE_KEYS),
            ),
        )
        conn.commit()
    finally:
        conn.close()


def recent_sessions(limit: int = 50) -> list[dict]:
    conn = _connect()
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute(
            "SELECT created_at, mode, label, filler_words, pace_pauses, "
            "clarity_structure, confidence_tone FROM sessions "
            "ORDER BY id DESC LIMIT ?",
            (limit,),
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()
