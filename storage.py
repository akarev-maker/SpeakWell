# storage.py — local SQLite persistence for session history.
import sqlite3
from datetime import datetime, timezone

DB_PATH = "speakwell.db"

SCORE_KEYS = ["filler_words", "pace_pauses", "clarity_structure", "confidence_tone"]


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


def save_session(mode: str, label: str, scores: dict) -> None:
    init_db()
    conn = sqlite3.connect(DB_PATH)
    try:
        conn.execute(
            "INSERT INTO sessions (created_at, mode, label, filler_words, "
            "pace_pauses, clarity_structure, confidence_tone) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                datetime.now(timezone.utc).isoformat(),
                mode,
                label,
                *(scores.get(k) for k in SCORE_KEYS),
            ),
        )
        conn.commit()
    finally:
        conn.close()


def recent_sessions(limit: int = 50) -> list[dict]:
    init_db()
    conn = sqlite3.connect(DB_PATH)
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
