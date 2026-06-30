# SpeakWell — JD-Driven Interview Session (Phase 1)

## Summary

Turn Mock interview mode into a multi-question interview session. The user pastes
a job description (or falls back to the role picker), the app generates a set of
questions, asks them one at a time (recording each answer and showing the full
existing analysis per answer), and ends with an overall **interview readiness**
debrief. Phase 1 has no per-answer follow-ups (that is Phase 2).

## Goals

- Start from a pasted job description (primary) or the role picker (fallback).
- Generate a JD-tailored question set; the model decides the count (capped 3–8).
- Walk through questions one at a time with progress ("Question 2 of 5").
- Reuse the existing analysis UI per answer (scores, transcript, feedback, tips,
  answer critique, model answer).
- End with an overall readiness summary across all answers.

## Non-Goals (Phase 1)

- No per-answer follow-up questions (Phase 2).
- No accounts, database, or persistence — the session lives in the browser.
- No change to Practice mode.

## Architecture

Client-orchestrated, backend stays stateless. The browser holds the session
state (question list, current index, collected answers) and calls small
stateless endpoints. No server-side session storage, no database.

### Backend

**`gemini_client.py`**
- `generate_interview_questions(context: str) -> list[str]` — returns a JD/role
  tailored list of questions. Uses a JSON-array response schema; instruction asks
  the model to choose an appropriate number for the role. The result is capped to
  8 and must be non-empty (raises `RuntimeError` on empty).
- `summarize_interview(context: str, qa_pairs: list[dict]) -> dict` — input is the
  JD/role context plus a list of `{"question": str, "answer": str}` (answer =
  transcript). Returns a dict validated to this shape:
  `{"level": str, "summary": str, "strengths": [str], "improvements": [str]}`.
  `level` is a short readiness label (e.g. "Almost ready", "Getting there",
  "Needs work"). Raises `RuntimeError` on malformed output.

**`prompts.py`**
- Reuse `INTERVIEW_QUESTIONS`; add `interview_question_set(n=4) -> list[str]` for
  the fallback path when generation fails.

**`main.py`**
- `POST /api/interview/start` — form fields `jd` and `context` (role fallback).
  Builds a context string (JD if present, else role context), calls
  `generate_interview_questions`, returns `{"questions": [...]}`. Falls back to
  `prompts.interview_question_set()` if generation fails or input is empty.
- `POST /api/interview/summary` — form fields `jd`, `context`, and `answers`
  (a JSON string of `[{"question","answer"}]`). Calls `summarize_interview`,
  returns the debrief dict. On error returns `{"error": ...}` with status 500.
- `/api/analyze` is reused unchanged for per-answer analysis (interview mode,
  `prompt` = the current question).

### Frontend (`static/`)

Mock interview mode replaces its single-question UI with a three-screen session:

1. **Start screen:** a "Paste the job description" textarea (`#jdInput`), the
   existing role picker as fallback, and a **"Start interview"** button.
2. **Question screen:** "Question X of N" + the question text, the existing
   record button, and after analysis the existing results UI plus a
   **"Next question →"** button (or **"Finish & see summary"** on the last one).
3. **Summary screen:** the readiness `level`, `summary`, `strengths`, and
   `improvements`, plus a **"Start over"** button.

A small session controller in `app.js` holds `{questions, index, answers}`,
advances through questions, calls `/api/analyze` per answer (storing
`{question, transcript}`), and calls `/api/interview/summary` at the end. The
record/analyze/render code is reused; the controller only manages flow and
screen visibility. Practice mode is unchanged.

`style.css` adds styling for the JD box, the question/progress header, the
session navigation buttons, and the summary screen — all in the Soft Sage theme.

## Data Shapes

`generate_interview_questions` response schema:
```json
{ "questions": ["...", "..."] }
```

`summarize_interview` response schema:
```json
{
  "level": "Getting there",
  "summary": "You communicated clearly but answers lacked specifics...",
  "strengths": ["Clear structure", "Calm delivery"],
  "improvements": ["Add concrete metrics", "Cut filler words"]
}
```

## Error Handling

- Question generation failure or empty input → fall back to a built-in question
  set so a session can always start.
- Summary generation failure → 500 with `{"error": ...}`; the UI shows a clean
  message and still lets the user review per-question results.
- Per-answer analysis failures use the existing `/api/analyze` error handling.

## Testing

- `gemini_client`: `generate_interview_questions` returns a list / caps to 8 /
  raises on empty; `summarize_interview` validates the shape and raises on
  missing fields. Gemini mocked.
- `main`: `/api/interview/start` returns questions (tailored + fallback paths);
  `/api/interview/summary` returns the debrief and handles errors. Gemini mocked.
- Existing 42 tests stay green; Python suite is the regression guard.
- Manual: run a full session live with synthesized audio end to end.

## Phasing

Phase 2 (separate spec) adds a follow-up question on each answer before advancing
to the next question — per-question conversation state layered on this spine.
