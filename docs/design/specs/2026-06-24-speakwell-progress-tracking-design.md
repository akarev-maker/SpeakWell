# SpeakWell — Progress Tracking

## Summary

Persist every analyzed recording locally so the user can see their speaking
improve over time. After each `/api/analyze`, the backend saves the four scores
plus metadata to a local SQLite file. A new Progress view shows per-dimension
trend sparklines, summary stats, and a session history. Local and personal — no
accounts, no audio/transcript stored, no deployment.

## Goals

- Auto-save every analyzed recording (practice + interview answers).
- Show score trends over time per dimension (sparklines), summary, and history.
- Keep it lightweight, local, and private (scores + metadata only).

## Non-Goals

- No accounts, multi-user, or sync.
- No storing of audio or transcripts.
- No charting library or framework.

## Storage

A local SQLite database file `speakwell.db` (git-ignored) accessed via Python's
stdlib `sqlite3` — no new dependency. One table:

```sql
CREATE TABLE IF NOT EXISTS sessions (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  created_at TEXT NOT NULL,        -- ISO 8601 UTC
  mode TEXT NOT NULL,              -- 'practice' | 'interview'
  label TEXT,                      -- short prompt/question text
  filler_words INTEGER,
  pace_pauses INTEGER,
  clarity_structure INTEGER,
  confidence_tone INTEGER
);
```

### `storage.py` (new, isolated)
- `DB_PATH` — module-level path (override in tests).
- `init_db()` — create the table if absent (called lazily by the others).
- `save_session(mode: str, label: str, scores: dict) -> None` — insert one row
  (created_at = now UTC). Reads the four score keys from `scores`.
- `recent_sessions(limit: int = 50) -> list[dict]` — rows newest-first as dicts.

Nothing else in the app touches the database directly.

## Backend wiring (`main.py`)

- After a successful `/api/analyze`, best-effort `storage.save_session(...)`:
  `mode` = 'interview' if the interview flag was set else 'practice';
  `label` = the question/prompt (truncated ~120 chars); `scores` = the analysis
  `scores`. Any storage error is swallowed so it never breaks analysis.
- `GET /api/progress` → `{"sessions": storage.recent_sessions(50)}`.

## Frontend (`static/`)

- A subtle **"📈 Progress"** link in the header opens a dedicated Progress view
  and hides the main app area; a **"← Back"** returns. (The main interactive
  area is wrapped in `#appMain`; the Progress view is `#progressView`.)
- **Progress view** (`renderProgress(sessions)`):
  - **Summary:** session count; per dimension the average plus a ▲/▼/– trend
    (latest vs earliest).
  - **Trends:** four hand-drawn **SVG sparklines** (score over time per
    dimension), no library, Soft Sage styling.
  - **History:** recent sessions as `date · mode · label · the four scores`
    (label rendered via escaped text — XSS-safe).
  - **Empty state:** "No sessions yet — record something to start tracking."
- Sparkline helper maps scores (0–100) to a `<polyline>` in a fixed-size SVG.

## Error Handling

- Saving is best-effort; a DB failure never affects the analysis response.
- `/api/progress` failure shows a clean message in the Progress view.
- Empty history shows the empty state rather than blank charts.

## Testing

- `storage.py`: against a temp SQLite path (monkeypatched `DB_PATH`) — save then
  `recent_sessions` returns rows newest-first; `limit` is respected.
- `main`: an autouse fixture points `storage.DB_PATH` at a temp file so tests
  never touch the real DB; `/api/analyze` writes a row with the right
  mode/scores; `/api/progress` returns `{sessions: [...]}`.
- Existing 55 tests stay green.
- Manual: record a few clips, open Progress, confirm sparklines/history.

## Privacy

`speakwell.db` is local and git-ignored. Only scores + a short label + timestamp
are stored — never audio or transcripts.
