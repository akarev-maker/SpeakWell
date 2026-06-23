# SpeakWell — Design

## Summary

SpeakWell is a local single-page web app that coaches users on how well they
speak. A user optionally requests a speaking prompt, records themselves in the
browser, and receives per-dimension scores, a transcript with filler words
highlighted, and written coaching feedback. Analysis is performed by Google
Gemini 2.0 Flash. The app is stateless: nothing is persisted between sessions.

## Goals

- Let a user record speech directly in the browser and get actionable coaching.
- Coach on four dimensions: filler words, pace & pauses, clarity & structure,
  confidence & tone.
- Present results as numeric scores (0–100) plus a transcript with filler words
  highlighted plus a written summary.
- Run entirely locally with a single Gemini API key.

## Non-Goals

- No session history or persistence (stateless).
- No user accounts or authentication.
- No file upload (browser mic recording only).
- No mobile-native app; a responsive web page is sufficient.

## Stack

- **Backend:** Python + FastAPI (also serves the static frontend).
- **Frontend:** Single-page vanilla HTML / CSS / JS (no framework).
- **AI:** Google Gemini 2.0 Flash (`gemini-2.0-flash`) for audio analysis.
- **Audio transcoding:** `ffmpeg` (system dependency) to convert browser
  recordings to a Gemini-supported audio format.

## Architecture

```
Browser (index.html + app.js + style.css)
   │  MediaRecorder captures mic → audio blob
   │  GET /api/prompt      → random speaking prompt
   │  POST /api/analyze    → multipart audio
   ▼
FastAPI backend (main.py)
   │  → transcode audio to Gemini-supported format (ffmpeg)
   │  → call Gemini 2.0 Flash with audio + structured-output prompt
   ▼
Gemini 2.0 Flash → returns JSON {scores, transcript, filler_words, feedback}
   ▼  back to browser → render score cards, highlighted transcript, feedback
```

## Components

### `main.py` — FastAPI application
- `GET /api/prompt` — returns a random prompt from a small built-in list:
  `{ "prompt": "Describe your ideal weekend." }`
- `POST /api/analyze` — accepts a multipart audio upload, transcodes it, calls
  the Gemini client, and returns the analysis JSON. Validates that audio is
  present and non-trivial in length.
- Serves the static frontend (`index.html`, `style.css`, `app.js`).
- Reads `GEMINI_API_KEY` from environment / `.env` at startup.

### `gemini_client.py` — Gemini integration (isolated)
- Single responsibility: given audio bytes + mime type, call Gemini 2.0 Flash
  with a fixed instruction prompt requesting structured JSON, then parse and
  validate the response into a known shape.
- Depends on: the Gemini SDK and the API key. Nothing else in the app depends on
  the Gemini SDK directly — this keeps the integration testable with a mock.

### `audio.py` — transcoding helper
- Single responsibility: take raw uploaded audio bytes and return bytes in a
  Gemini-supported format (e.g. WAV) by shelling out to `ffmpeg`.
- Surfaces a clear error if `ffmpeg` is not installed.

### Frontend (`index.html`, `style.css`, `app.js`)
- Record button with elapsed-time indicator; stop to finish.
- "Give me a prompt" button → fetches and displays a prompt (optional to use).
- Results view:
  - Four score cards: Filler words, Pace & pauses, Clarity & structure,
    Confidence & tone (each 0–100).
  - Transcript with filler-word occurrences highlighted inline.
  - Written coaching summary.
- Inline status/error messages (recording, analyzing, errors).

## Data Flow / Output Shape

Gemini is instructed to return strictly this JSON shape:

```json
{
  "scores": {
    "filler_words": 72,
    "pace_pauses": 85,
    "clarity_structure": 78,
    "confidence_tone": 80
  },
  "transcript": "So um, I think the most important thing is...",
  "filler_words": ["um", "like", "you know"],
  "feedback": "You spoke clearly and stayed on topic. You used 'um' 6 times..."
}
```

- `scores`: integers 0–100 for each of the four dimensions.
- `transcript`: full text of what was said.
- `filler_words`: distinct filler tokens detected (used by the frontend to
  highlight matches in the transcript).
- `feedback`: a short written coaching summary with specific, actionable tips.

The frontend renders score cards from `scores`, highlights any `filler_words`
matches within `transcript`, and shows `feedback` as prose.

## Error Handling

Each of these surfaces a clear, inline message rather than failing silently:

- **Mic permission denied** — prompt the user to allow microphone access.
- **Empty / too-short recording** — ask the user to record a longer clip.
- **Missing `GEMINI_API_KEY`** — backend returns a clear error; UI shows it.
- **`ffmpeg` not installed** — backend returns a clear setup error.
- **Gemini API error / malformed response** — UI shows that analysis failed and
  invites a retry.

## Testing

- `gemini_client.py`: parsing and validation tested against a mocked Gemini
  response (no real API calls in tests), including a malformed-response case.
- `audio.py`: transcoding helper tested with a small fixture (or ffmpeg mocked).
- Endpoints: FastAPI `TestClient` tests for `/api/prompt` and `/api/analyze`
  with the Gemini client mocked, covering success and validation-error paths.

## Setup / Run

- `pip install -r requirements.txt`
- Install `ffmpeg` (system package).
- Create `.env` with `GEMINI_API_KEY=...`.
- Run `uvicorn main:app --reload` and open the served page in a browser.
