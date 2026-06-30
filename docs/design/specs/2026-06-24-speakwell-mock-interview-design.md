# SpeakWell — Mock Interview MVP

## Summary

Add a "Mock interview mode" toggle. When on, the app generates a realistic
interview question tailored to the user's goal; the user records their answer;
and the results add an **Interview answer** section — a critique of the answer's
content plus a stronger **model answer** — on top of the existing delivery
scores, transcript, feedback, tips, playback, and WPM.

## Goals

- Generate an interview question tailored to the user's context.
- Evaluate the *content* of the spoken answer (relevance, specificity,
  structure, what was missing), not just delivery.
- Show a concise model answer to compare against.
- Reuse the entire existing flow; the interview layer is additive and optional.

## Non-Goals

- No multi-turn interview / follow-up questions (deferred to a later version).
- No accounts, history, or persistence.
- No change to the existing non-interview behavior.

## Backend

### `gemini_client.py`
- `generate_interview_question(context: str) -> str` — generates one realistic
  interview question tailored to `context` (behavioral/role-appropriate).
  Mirrors `generate_prompt`: text-only call, strips quotes, raises `RuntimeError`
  on empty output.
- `analyze_speech(wav_bytes, prompt=None, context=None, question=None) -> dict`
  — extended with an optional `question`. When `question` is provided
  (interview mode):
  - The instruction additionally tells the model the question being answered and
    asks it to (a) judge how well the spoken answer addresses it and (b) provide
    a stronger model answer.
  - The response schema gains two **required** fields: `answer_critique`
    (string, 2-3 sentences) and `model_answer` (string, concise).
  - `parse_response` validates these two fields **only when expected**. To keep
    `parse_response` simple, it takes an optional `require_interview: bool`
    argument; when true it also requires `answer_critique` and `model_answer`.
  - When `question` is None, behavior and output are exactly as today.

### `prompts.py`
- Add `INTERVIEW_QUESTIONS` list and `random_interview_question() -> str` for
  the fallback path when generation fails.

### `main.py`
- `POST /api/interview-question` — `Form("context")`; returns
  `{"question": ...}`. Tailored via `generate_interview_question` when context is
  present, else (or on error) a random built-in interview question.
- `POST /api/analyze` — gains `interview: str = Form("")`. When truthy, the
  submitted `prompt` field carries the interview question and is passed as
  `question=` to `analyze_speech`, so the result includes `answer_critique` and
  `model_answer`. When falsy, unchanged.

## Frontend (`static/`)

- **`index.html`**: a "🎤 Mock interview mode" checkbox near the prompt area; an
  **Interview answer** card in `#results` (hidden by default) containing a
  critique paragraph and a model-answer block.
- **`app.js`**:
  - Track interview mode from the checkbox.
  - In interview mode, the prompt button label becomes "Give me an interview
    question" and calls `POST /api/interview-question` (instead of
    `/api/prompt`), filling the prompt box with the question.
  - `analyze()` appends `interview` = "1" when the checkbox is on.
  - `render()` shows the Interview answer card (critique + model answer) when
    `answer_critique`/`model_answer` are present; hides it otherwise. All text
    rendered via `textContent` (no XSS).
- **`style.css`**: style the Interview answer card to match Soft Sage.

## Data Shapes

Interview-mode analysis response (superset of the normal one):

```json
{
  "scores": { ...four keys... },
  "transcript": "...",
  "filler_words": ["..."],
  "feedback": "...",
  "tips": ["..."],
  "answer_critique": "Your answer was relevant but lacked a concrete example...",
  "model_answer": "A stronger version: 'In my last role, I...'"
}
```

## Error Handling

- Interview-question generation failure → fall back to a random built-in
  interview question (button always works).
- If interview-mode analysis is missing the extra fields, `parse_response`
  raises `RuntimeError` (surfaced as a clean 500), consistent with existing
  validation.
- Frontend hides the Interview answer card when the fields are absent.

## Testing

- `gemini_client`: `generate_interview_question` embeds context and strips
  quotes; interview-mode `analyze_speech` requires/returns `answer_critique` and
  `model_answer`; missing-field case raises.
- `main`: `/api/interview-question` returns a question (tailored + fallback
  paths); `/api/analyze` interview path forwards the question and returns the
  extra fields.
- Python suite stays green. Live verification with synthesized audio in
  interview mode.
