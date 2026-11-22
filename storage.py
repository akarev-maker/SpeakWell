"""Local SQLite storage: graded interviews and your saved resume.

Only scores and feedback are kept. Transcripts, recordings and code are never
written here (feedback items do quote short snippets of what you said, since
that is what makes them precise).
"""
import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

# Anchored to this file, not the process CWD, so it's always the same file.
DB_PATH = str(Path(__file__).resolve().parent / "speakwell.db")

_initialized: set[str] = set()

SCHEMA = """
CREATE TABLE IF NOT EXISTS interviews (
    id TEXT PRIMARY KEY,
    created_at TEXT NOT NULL,
    kind TEXT NOT NULL,
    track TEXT NOT NULL,
    level TEXT NOT NULL,
    persona TEXT NOT NULL,
    seeds TEXT NOT NULL,          -- JSON list of catalog seed ids (for variety)
    title TEXT NOT NULL,
    duration_sec INTEGER NOT NULL,
    ended_early INTEGER NOT NULL,
    overall_score INTEGER,
    scores TEXT NOT NULL,         -- JSON {category_id: 0-100}
    report TEXT NOT NULL,         -- JSON full report shown on the report screen
    cost_usd REAL NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS interviews_created ON interviews (created_at);
-- Every billable step is logged as it happens (plan, live call, grading), so
-- the monthly meter also counts interviews you abandoned before grading.
CREATE TABLE IF NOT EXISTS spend (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at TEXT NOT NULL,
    usd REAL NOT NULL,
    what TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS resume (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    text TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
"""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _connect() -> sqlite3.Connection:
    """Open the DB, creating the schema once per database file."""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    if DB_PATH not in _initialized:
        conn.executescript(SCHEMA)
        conn.commit()
        _initialized.add(DB_PATH)
    return conn


def _clamp(value) -> int | None:
    try:
        return max(0, min(100, int(round(float(value)))))
    except (TypeError, ValueError):
        return None


def save_interview(rec: dict) -> None:
    conn = _connect()
    try:
        conn.execute(
            "INSERT INTO interviews (id, created_at, kind, track, level, persona, seeds, title, "
            "duration_sec, ended_early, overall_score, scores, report, cost_usd) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                rec["id"], rec.get("created_at") or _now(), rec["kind"], rec["track"], rec["level"],
                rec["persona"], json.dumps(rec.get("seeds", [])), rec.get("title", "")[:200],
                int(rec.get("duration_sec", 0)), 1 if rec.get("ended_early") else 0,
                _clamp(rec.get("overall_score")),
                json.dumps({k: _clamp(v) for k, v in (rec.get("scores") or {}).items()}),
                json.dumps(rec.get("report") or {}),
                float(rec.get("cost_usd") or 0),
            ),
        )
        conn.commit()
    finally:
        conn.close()


def _row(r: sqlite3.Row, full: bool) -> dict:
    out = {
        "id": r["id"], "created_at": r["created_at"], "kind": r["kind"], "track": r["track"],
        "level": r["level"], "persona": r["persona"], "title": r["title"],
        "duration_sec": r["duration_sec"], "ended_early": bool(r["ended_early"]),
        "overall_score": r["overall_score"], "scores": json.loads(r["scores"]),
        "cost_usd": r["cost_usd"],
    }
    if full:
        out["report"] = json.loads(r["report"])
    return out


def list_interviews(limit: int = 100) -> list[dict]:
    conn = _connect()
    try:
        rows = conn.execute(
            "SELECT * FROM interviews ORDER BY created_at DESC LIMIT ?", (limit,)
        ).fetchall()
        return [_row(r, full=False) for r in rows]
    finally:
        conn.close()


def get_interview(interview_id: str) -> dict | None:
    conn = _connect()
    try:
        r = conn.execute("SELECT * FROM interviews WHERE id = ?", (interview_id,)).fetchone()
        return _row(r, full=True) if r else None
    finally:
        conn.close()


def delete_interview(interview_id: str) -> bool:
    conn = _connect()
    try:
        cur = conn.execute("DELETE FROM interviews WHERE id = ?", (interview_id,))
        conn.commit()
        return cur.rowcount > 0
    finally:
        conn.close()


def recent_seeds(kind: str, track: str, limit: int = 10) -> list[str]:
    """Seed ids used in the last `limit` interviews of this kind+track, newest first."""
    conn = _connect()
    try:
        rows = conn.execute(
            "SELECT seeds FROM interviews WHERE kind = ? AND track = ? "
            "ORDER BY created_at DESC LIMIT ?",
            (kind, track, limit),
        ).fetchall()
    finally:
        conn.close()
    seen: list[str] = []
    for r in rows:
        for s in json.loads(r["seeds"]):
            if s not in seen:
                seen.append(s)
    return seen


def record_spend(usd: float, what: str) -> None:
    if usd <= 0:
        return
    conn = _connect()
    try:
        conn.execute("INSERT INTO spend (created_at, usd, what) VALUES (?, ?, ?)",
                     (_now(), float(usd), what[:80]))
        conn.commit()
    finally:
        conn.close()


def month_spend_usd(now: datetime | None = None) -> float:
    now = now or datetime.now(timezone.utc)
    start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0).isoformat()
    conn = _connect()
    try:
        r = conn.execute(
            "SELECT COALESCE(SUM(usd), 0) AS s FROM spend WHERE created_at >= ?", (start,)
        ).fetchone()
        return float(r["s"])
    finally:
        conn.close()


def get_resume() -> dict | None:
    conn = _connect()
    try:
        r = conn.execute("SELECT text, updated_at FROM resume WHERE id = 1").fetchone()
        return {"text": r["text"], "updated_at": r["updated_at"]} if r else None
    finally:
        conn.close()


def save_resume(text: str) -> None:
    conn = _connect()
    try:
        conn.execute(
            "INSERT INTO resume (id, text, updated_at) VALUES (1, ?, ?) "
            "ON CONFLICT(id) DO UPDATE SET text = excluded.text, updated_at = excluded.updated_at",
            (text, _now()),
        )
        conn.commit()
    finally:
        conn.close()


def clear_resume() -> None:
    conn = _connect()
    try:
        conn.execute("DELETE FROM resume WHERE id = 1")
        conn.commit()
    finally:
        conn.close()
