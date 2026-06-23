# SpeakWell Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a local single-page web app where a user records speech in the browser and gets back per-dimension scores, a highlighted transcript, and written coaching feedback from Gemini 2.0 Flash.

**Architecture:** A FastAPI backend serves a vanilla HTML/CSS/JS frontend and exposes two endpoints: `GET /api/prompt` (random speaking prompt) and `POST /api/analyze` (audio in, analysis JSON out). The backend transcodes the browser recording to WAV with ffmpeg, then sends it to Gemini 2.0 Flash requesting structured JSON. The app is stateless — nothing is persisted.

**Tech Stack:** Python 3.11+, FastAPI, Uvicorn, `google-genai` SDK, python-dotenv, ffmpeg (system), pytest. Frontend: vanilla HTML/CSS/JS with the browser MediaRecorder API.

## Global Constraints

- Model id: `gemini-2.0-flash` (exact).
- API key source: `GEMINI_API_KEY` from `.env` / environment — never in frontend.
- Four scoring dimensions, exact JSON keys: `filler_words`, `pace_pauses`, `clarity_structure`, `confidence_tone`. Scores are integers 0–100.
- Analysis response JSON shape: `{ "scores": {<4 keys>}, "transcript": str, "filler_words": [str], "feedback": str }`.
- Stateless: no database, no history, no auth.
- Audio input: browser mic recording only (no file upload).
- Tests must not make real Gemini API calls or require a real key.

---

### Task 1: Project scaffold + configuration

**Files:**
- Create: `requirements.txt`
- Create: `config.py`
- Create: `.env.example`
- Test: `tests/test_config.py`
- Create: `tests/__init__.py`

**Interfaces:**
- Produces: `config.get_api_key() -> str` (raises `RuntimeError` with a clear message if `GEMINI_API_KEY` is missing/empty). `config.GEMINI_MODEL = "gemini-2.0-flash"`.

- [ ] **Step 1: Write requirements.txt**

```
fastapi==0.115.6
uvicorn[standard]==0.34.0
google-genai==0.8.0
python-dotenv==1.0.1
python-multipart==0.0.20
pytest==8.3.4
httpx==0.28.1
```

- [ ] **Step 2: Write the failing test**

```python
# tests/test_config.py
import pytest
import config


def test_get_api_key_returns_value(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "test-key-123")
    assert config.get_api_key() == "test-key-123"


def test_get_api_key_missing_raises(monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    with pytest.raises(RuntimeError, match="GEMINI_API_KEY"):
        config.get_api_key()


def test_model_constant():
    assert config.GEMINI_MODEL == "gemini-2.0-flash"
```

- [ ] **Step 3: Run test to verify it fails**

Run: `pip install -r requirements.txt && python -m pytest tests/test_config.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'config'`.

- [ ] **Step 4: Write config.py and .env.example**

```python
# config.py
import os
from dotenv import load_dotenv

load_dotenv()

GEMINI_MODEL = "gemini-2.0-flash"


def get_api_key() -> str:
    key = os.environ.get("GEMINI_API_KEY", "").strip()
    if not key:
        raise RuntimeError(
            "GEMINI_API_KEY is not set. Add it to your .env file: "
            "GEMINI_API_KEY=your_key_here"
        )
    return key
```

```
# .env.example
GEMINI_API_KEY=your_key_here
```

Also create an empty `tests/__init__.py`.

- [ ] **Step 5: Run test to verify it passes**

Run: `python -m pytest tests/test_config.py -v`
Expected: PASS (3 passed).

- [ ] **Step 6: Commit**

```bash
git add requirements.txt config.py .env.example tests/__init__.py tests/test_config.py
git commit -m "feat: project scaffold and config loading"
```

---

### Task 2: Audio transcoding helper

**Files:**
- Create: `audio.py`
- Test: `tests/test_audio.py`

**Interfaces:**
- Produces: `audio.transcode_to_wav(data: bytes) -> bytes` — converts arbitrary input audio bytes to WAV bytes via ffmpeg. Raises `RuntimeError` if ffmpeg is missing (`FileNotFoundError`) or fails (non-zero exit).

- [ ] **Step 1: Write the failing test**

```python
# tests/test_audio.py
import subprocess
import pytest
import audio


def test_transcode_calls_ffmpeg_and_returns_stdout(monkeypatch):
    captured = {}

    class FakeCompleted:
        returncode = 0
        stdout = b"RIFFWAVEDATA"
        stderr = b""

    def fake_run(cmd, input, stdout, stderr):
        captured["cmd"] = cmd
        captured["input"] = input
        return FakeCompleted()

    monkeypatch.setattr(subprocess, "run", fake_run)
    out = audio.transcode_to_wav(b"rawbytes")
    assert out == b"RIFFWAVEDATA"
    assert captured["cmd"][0] == "ffmpeg"
    assert captured["input"] == b"rawbytes"


def test_transcode_missing_ffmpeg_raises(monkeypatch):
    def fake_run(*a, **k):
        raise FileNotFoundError()

    monkeypatch.setattr(subprocess, "run", fake_run)
    with pytest.raises(RuntimeError, match="ffmpeg"):
        audio.transcode_to_wav(b"x")


def test_transcode_nonzero_exit_raises(monkeypatch):
    class FakeCompleted:
        returncode = 1
        stdout = b""
        stderr = b"boom"

    monkeypatch.setattr(subprocess, "run", lambda *a, **k: FakeCompleted())
    with pytest.raises(RuntimeError, match="transcode"):
        audio.transcode_to_wav(b"x")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_audio.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'audio'`.

- [ ] **Step 3: Write audio.py**

```python
# audio.py
import subprocess

WAV_MIME = "audio/wav"


def transcode_to_wav(data: bytes) -> bytes:
    """Convert arbitrary input audio bytes to WAV bytes using ffmpeg."""
    cmd = ["ffmpeg", "-hide_banner", "-loglevel", "error",
           "-i", "pipe:0", "-f", "wav", "pipe:1"]
    try:
        result = subprocess.run(
            cmd, input=data,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        )
    except FileNotFoundError as exc:
        raise RuntimeError(
            "ffmpeg is not installed. Install it (e.g. `brew install ffmpeg`)."
        ) from exc
    if result.returncode != 0:
        raise RuntimeError(
            f"ffmpeg failed to transcode audio: {result.stderr.decode(errors='ignore')}"
        )
    return result.stdout
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_audio.py -v`
Expected: PASS (3 passed).

- [ ] **Step 5: Commit**

```bash
git add audio.py tests/test_audio.py
git commit -m "feat: ffmpeg audio transcoding helper"
```

---

### Task 3: Gemini client

**Files:**
- Create: `gemini_client.py`
- Test: `tests/test_gemini_client.py`

**Interfaces:**
- Consumes: `config.get_api_key()`, `config.GEMINI_MODEL`.
- Produces: `gemini_client.analyze_speech(wav_bytes: bytes) -> dict` — returns the validated analysis dict with keys `scores` (dict of 4 int keys), `transcript` (str), `filler_words` (list[str]), `feedback` (str). Raises `RuntimeError` on malformed/unparseable responses.
- Produces (for testability): `gemini_client.parse_response(text: str) -> dict` — parses+validates a JSON string into the analysis dict, raising `RuntimeError` if shape is wrong. `analyze_speech` builds the Gemini client, calls the model, and delegates to `parse_response(response.text)`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_gemini_client.py
import json
import pytest
import gemini_client

VALID = {
    "scores": {
        "filler_words": 72, "pace_pauses": 85,
        "clarity_structure": 78, "confidence_tone": 80,
    },
    "transcript": "So um, I think...",
    "filler_words": ["um"],
    "feedback": "Good clarity. You said 'um' a few times.",
}


def test_parse_valid_response():
    out = gemini_client.parse_response(json.dumps(VALID))
    assert out["scores"]["pace_pauses"] == 85
    assert out["filler_words"] == ["um"]
    assert out["transcript"].startswith("So um")


def test_parse_strips_code_fence():
    fenced = "```json\n" + json.dumps(VALID) + "\n```"
    out = gemini_client.parse_response(fenced)
    assert out["feedback"].startswith("Good clarity")


def test_parse_invalid_json_raises():
    with pytest.raises(RuntimeError, match="parse"):
        gemini_client.parse_response("not json at all")


def test_parse_missing_score_key_raises():
    bad = json.loads(json.dumps(VALID))
    del bad["scores"]["pace_pauses"]
    with pytest.raises(RuntimeError, match="scores"):
        gemini_client.parse_response(json.dumps(bad))


def test_analyze_speech_uses_client(monkeypatch):
    class FakeResp:
        text = json.dumps(VALID)

    class FakeModels:
        def generate_content(self, **kwargs):
            assert kwargs["model"] == "gemini-2.0-flash"
            return FakeResp()

    class FakeClient:
        models = FakeModels()

    monkeypatch.setattr(gemini_client, "_build_client", lambda: FakeClient())
    out = gemini_client.analyze_speech(b"RIFFWAVE")
    assert out["scores"]["filler_words"] == 72
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_gemini_client.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'gemini_client'`.

- [ ] **Step 3: Write gemini_client.py**

```python
# gemini_client.py
import json
from google import genai
from google.genai import types

import config

SCORE_KEYS = ["filler_words", "pace_pauses", "clarity_structure", "confidence_tone"]

INSTRUCTION = (
    "You are SpeakWell, a speech coach. Listen to the attached audio of a "
    "person speaking and evaluate their delivery. Return ONLY a JSON object "
    "with this exact shape:\n"
    '{"scores": {"filler_words": int, "pace_pauses": int, '
    '"clarity_structure": int, "confidence_tone": int}, '
    '"transcript": string, "filler_words": [string], "feedback": string}\n'
    "Each score is an integer 0-100 (higher is better). "
    "'transcript' is a faithful transcript of the speech. "
    "'filler_words' lists the distinct filler words actually used "
    "(e.g. um, uh, like, you know); empty list if none. "
    "'feedback' is 2-4 sentences of specific, encouraging, actionable coaching "
    "covering filler words, pace & pauses, clarity & structure, and confidence "
    "& tone. Do not wrap the JSON in markdown."
)

RESPONSE_SCHEMA = {
    "type": "object",
    "properties": {
        "scores": {
            "type": "object",
            "properties": {k: {"type": "integer"} for k in SCORE_KEYS},
            "required": SCORE_KEYS,
        },
        "transcript": {"type": "string"},
        "filler_words": {"type": "array", "items": {"type": "string"}},
        "feedback": {"type": "string"},
    },
    "required": ["scores", "transcript", "filler_words", "feedback"],
}


def _build_client() -> genai.Client:
    return genai.Client(api_key=config.get_api_key())


def parse_response(text: str) -> dict:
    cleaned = text.strip()
    if cleaned.startswith("```"):
        # strip leading ```json / ``` and trailing ```
        cleaned = cleaned.split("```", 2)
        cleaned = cleaned[1] if len(cleaned) >= 2 else text
        if cleaned.startswith("json"):
            cleaned = cleaned[len("json"):]
        cleaned = cleaned.strip().rstrip("`").strip()
    try:
        data = json.loads(cleaned)
    except (json.JSONDecodeError, ValueError) as exc:
        raise RuntimeError(f"Could not parse Gemini response: {exc}") from exc

    if not isinstance(data.get("scores"), dict):
        raise RuntimeError("Gemini response missing 'scores' object")
    for key in SCORE_KEYS:
        if key not in data["scores"]:
            raise RuntimeError(f"Gemini response missing scores.{key}")
    for field in ("transcript", "filler_words", "feedback"):
        if field not in data:
            raise RuntimeError(f"Gemini response missing '{field}'")
    return data


def analyze_speech(wav_bytes: bytes) -> dict:
    client = _build_client()
    response = client.models.generate_content(
        model=config.GEMINI_MODEL,
        contents=[
            types.Part.from_bytes(data=wav_bytes, mime_type="audio/wav"),
            INSTRUCTION,
        ],
        config=types.GenerateContentConfig(
            response_mime_type="application/json",
            response_schema=RESPONSE_SCHEMA,
        ),
    )
    return parse_response(response.text)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_gemini_client.py -v`
Expected: PASS (5 passed).

- [ ] **Step 5: Commit**

```bash
git add gemini_client.py tests/test_gemini_client.py
git commit -m "feat: Gemini 2.0 Flash speech analysis client"
```

---

### Task 4: FastAPI backend (endpoints + static serving)

**Files:**
- Create: `main.py`
- Create: `prompts.py`
- Test: `tests/test_main.py`

**Interfaces:**
- Consumes: `audio.transcode_to_wav`, `gemini_client.analyze_speech`, `prompts.random_prompt`.
- Produces: FastAPI `app`. `GET /api/prompt` -> `{"prompt": str}`. `POST /api/analyze` (multipart field `audio`) -> analysis dict, or `{"error": str}` with status 400/500. `GET /` serves `static/index.html`; static assets served under `/static`.

- [ ] **Step 1: Write prompts.py**

```python
# prompts.py
import random

PROMPTS = [
    "Describe your ideal weekend.",
    "Explain a topic you know well to someone new to it.",
    "Tell me about a challenge you overcame recently.",
    "Pitch your favorite product or app in 30 seconds.",
    "Describe a place you would love to travel to and why.",
    "Talk about a book, film, or show that influenced you.",
    "Explain what you do for work as if to a 10-year-old.",
    "Argue for or against working from home.",
]


def random_prompt() -> str:
    return random.choice(PROMPTS)
```

- [ ] **Step 2: Write the failing test**

```python
# tests/test_main.py
import io
import pytest
from fastapi.testclient import TestClient

import main


@pytest.fixture
def client():
    return TestClient(main.app)


def test_prompt_endpoint(client):
    resp = client.get("/api/prompt")
    assert resp.status_code == 200
    assert isinstance(resp.json()["prompt"], str)
    assert resp.json()["prompt"]


def test_analyze_success(client, monkeypatch):
    monkeypatch.setattr(main.audio, "transcode_to_wav", lambda b: b"WAV")
    fake = {
        "scores": {"filler_words": 70, "pace_pauses": 80,
                   "clarity_structure": 75, "confidence_tone": 78},
        "transcript": "hello world", "filler_words": [], "feedback": "Nice.",
    }
    monkeypatch.setattr(main.gemini_client, "analyze_speech", lambda b: fake)
    resp = client.post(
        "/api/analyze",
        files={"audio": ("rec.webm", io.BytesIO(b"rawaudio"), "audio/webm")},
    )
    assert resp.status_code == 200
    assert resp.json()["scores"]["pace_pauses"] == 80


def test_analyze_empty_audio_rejected(client):
    resp = client.post(
        "/api/analyze",
        files={"audio": ("rec.webm", io.BytesIO(b""), "audio/webm")},
    )
    assert resp.status_code == 400
    assert "error" in resp.json()


def test_analyze_handles_backend_error(client, monkeypatch):
    monkeypatch.setattr(main.audio, "transcode_to_wav", lambda b: b"WAV")
    def boom(b):
        raise RuntimeError("gemini down")
    monkeypatch.setattr(main.gemini_client, "analyze_speech", boom)
    resp = client.post(
        "/api/analyze",
        files={"audio": ("rec.webm", io.BytesIO(b"rawaudio"), "audio/webm")},
    )
    assert resp.status_code == 500
    assert "gemini down" in resp.json()["error"]
```

- [ ] **Step 3: Run test to verify it fails**

Run: `python -m pytest tests/test_main.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'main'`.

- [ ] **Step 4: Write main.py**

```python
# main.py
from fastapi import FastAPI, UploadFile, File
from fastapi.responses import JSONResponse, FileResponse
from fastapi.staticfiles import StaticFiles

import audio
import gemini_client
import prompts

app = FastAPI(title="SpeakWell")

MIN_AUDIO_BYTES = 1000  # reject trivially short/empty recordings


@app.get("/api/prompt")
def get_prompt():
    return {"prompt": prompts.random_prompt()}


@app.post("/api/analyze")
async def analyze(audio: UploadFile = File(...)):  # noqa: F811 - see import below
    raw = await audio.read()
    if len(raw) < MIN_AUDIO_BYTES:
        return JSONResponse(
            status_code=400,
            content={"error": "Recording is too short. Please speak for a few seconds."},
        )
    try:
        wav = _audio_mod.transcode_to_wav(raw)
        result = _gemini_mod.analyze_speech(wav)
    except RuntimeError as exc:
        return JSONResponse(status_code=500, content={"error": str(exc)})
    return result


@app.get("/")
def index():
    return FileResponse("static/index.html")


app.mount("/static", StaticFiles(directory="static"), name="static")
```

NOTE: the `audio` parameter name shadows the `audio` module. To keep the tests' `main.audio` / `main.gemini_client` references working, rename the module-level handles. Replace the handler and imports with this final version instead:

```python
# main.py
from fastapi import FastAPI, UploadFile, File
from fastapi.responses import JSONResponse, FileResponse
from fastapi.staticfiles import StaticFiles

import audio
import gemini_client
import prompts

app = FastAPI(title="SpeakWell")

MIN_AUDIO_BYTES = 1000


@app.get("/api/prompt")
def get_prompt():
    return {"prompt": prompts.random_prompt()}


@app.post("/api/analyze")
async def analyze(audio_file: UploadFile = File(..., alias="audio")):
    raw = await audio_file.read()
    if len(raw) < MIN_AUDIO_BYTES:
        return JSONResponse(
            status_code=400,
            content={"error": "Recording is too short. Please speak for a few seconds."},
        )
    try:
        wav = audio.transcode_to_wav(raw)
        result = gemini_client.analyze_speech(wav)
    except RuntimeError as exc:
        return JSONResponse(status_code=500, content={"error": str(exc)})
    return result


@app.get("/")
def index():
    return FileResponse("static/index.html")


app.mount("/static", StaticFiles(directory="static"), name="static")
```

Create a placeholder `static/index.html` (real content in Task 5) so `StaticFiles(directory="static")` mounts:

```bash
mkdir -p static && printf '<!doctype html><title>SpeakWell</title>\n' > static/index.html
```

- [ ] **Step 5: Run test to verify it passes**

Run: `python -m pytest tests/test_main.py -v`
Expected: PASS (4 passed).

- [ ] **Step 6: Run the full suite**

Run: `python -m pytest -v`
Expected: all tests pass.

- [ ] **Step 7: Commit**

```bash
git add main.py prompts.py tests/test_main.py static/index.html
git commit -m "feat: FastAPI endpoints for prompt and analyze"
```

---

### Task 5: Frontend (record, prompt, results)

**Files:**
- Create: `static/index.html`
- Create: `static/style.css`
- Create: `static/app.js`

**Interfaces:**
- Consumes: `GET /api/prompt`, `POST /api/analyze` (multipart field `audio`).
- Produces: the user-facing single page. No automated tests (manual verification in Step 5).

- [ ] **Step 1: Write static/index.html**

```html
<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>SpeakWell — Speech Coach</title>
  <link rel="stylesheet" href="/static/style.css" />
</head>
<body>
  <main class="container">
    <header>
      <h1>SpeakWell</h1>
      <p class="tagline">Record yourself. Get coached on how you speak.</p>
    </header>

    <section class="prompt-bar">
      <button id="promptBtn" class="secondary">Give me a prompt</button>
      <p id="promptText" class="prompt-text" hidden></p>
    </section>

    <section class="recorder">
      <button id="recordBtn" class="record">● Record</button>
      <span id="timer" class="timer">0:00</span>
    </section>

    <p id="status" class="status" role="status"></p>

    <section id="results" class="results" hidden>
      <div class="scores" id="scores"></div>
      <h2>Transcript</h2>
      <p id="transcript" class="transcript"></p>
      <h2>Coaching feedback</h2>
      <p id="feedback" class="feedback"></p>
    </section>
  </main>
  <script src="/static/app.js"></script>
</body>
</html>
```

- [ ] **Step 2: Write static/style.css**

```css
:root {
  --bg: #0f1220; --panel: #1a1f33; --text: #e8ebf5; --muted: #9aa3c0;
  --accent: #6c8cff; --good: #4ade80; --mid: #fbbf24; --bad: #f87171;
}
* { box-sizing: border-box; }
body {
  margin: 0; font-family: system-ui, -apple-system, Segoe UI, Roboto, sans-serif;
  background: radial-gradient(1200px 600px at 50% -10%, #1c2342, var(--bg));
  color: var(--text); min-height: 100vh;
}
.container { max-width: 760px; margin: 0 auto; padding: 2.5rem 1.25rem 4rem; }
header h1 { font-size: 2.5rem; margin: 0; letter-spacing: -0.02em; }
.tagline { color: var(--muted); margin-top: 0.25rem; }
.prompt-bar { margin: 2rem 0 1rem; }
.prompt-text {
  background: var(--panel); border-left: 3px solid var(--accent);
  padding: 0.85rem 1rem; border-radius: 8px; font-size: 1.1rem;
}
.recorder { display: flex; align-items: center; gap: 1rem; margin: 1.5rem 0; }
button { cursor: pointer; border: none; border-radius: 999px; font-size: 1rem;
  padding: 0.7rem 1.4rem; color: var(--text); transition: transform .05s ease; }
button:active { transform: scale(0.97); }
button.record { background: var(--accent); font-weight: 600; }
button.record.recording { background: var(--bad); }
button.secondary { background: var(--panel); color: var(--text); }
button:disabled { opacity: .5; cursor: not-allowed; }
.timer { font-variant-numeric: tabular-nums; color: var(--muted); font-size: 1.1rem; }
.status { min-height: 1.4rem; color: var(--muted); }
.status.error { color: var(--bad); }
.results { margin-top: 1.5rem; }
.scores { display: grid; grid-template-columns: repeat(2, 1fr); gap: 0.9rem; }
.score-card { background: var(--panel); border-radius: 12px; padding: 1rem 1.1rem; }
.score-card .label { color: var(--muted); font-size: 0.85rem; }
.score-card .value { font-size: 2rem; font-weight: 700; }
.score-bar { height: 6px; border-radius: 999px; background: #2a3150; margin-top: .5rem; overflow: hidden; }
.score-bar > span { display: block; height: 100%; }
.transcript, .feedback { background: var(--panel); border-radius: 12px; padding: 1rem 1.1rem; line-height: 1.6; }
.filler { background: rgba(248,113,113,.25); color: #fecaca; border-radius: 4px; padding: 0 3px; }
@media (max-width: 520px) { .scores { grid-template-columns: 1fr; } }
```

- [ ] **Step 3: Write static/app.js**

```javascript
const recordBtn = document.getElementById("recordBtn");
const promptBtn = document.getElementById("promptBtn");
const promptText = document.getElementById("promptText");
const timerEl = document.getElementById("timer");
const statusEl = document.getElementById("status");
const results = document.getElementById("results");
const scoresEl = document.getElementById("scores");
const transcriptEl = document.getElementById("transcript");
const feedbackEl = document.getElementById("feedback");

const SCORE_LABELS = {
  filler_words: "Filler words",
  pace_pauses: "Pace & pauses",
  clarity_structure: "Clarity & structure",
  confidence_tone: "Confidence & tone",
};

let mediaRecorder = null;
let chunks = [];
let timerId = null;
let seconds = 0;

function setStatus(msg, isError = false) {
  statusEl.textContent = msg;
  statusEl.classList.toggle("error", isError);
}

function fmt(t) {
  const m = Math.floor(t / 60);
  const s = String(t % 60).padStart(2, "0");
  return `${m}:${s}`;
}

promptBtn.addEventListener("click", async () => {
  try {
    const r = await fetch("/api/prompt");
    const data = await r.json();
    promptText.textContent = data.prompt;
    promptText.hidden = false;
  } catch {
    setStatus("Could not load a prompt.", true);
  }
});

recordBtn.addEventListener("click", async () => {
  if (mediaRecorder && mediaRecorder.state === "recording") {
    mediaRecorder.stop();
    return;
  }
  try {
    const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
    mediaRecorder = new MediaRecorder(stream);
    chunks = [];
    mediaRecorder.ondataavailable = (e) => { if (e.data.size) chunks.push(e.data); };
    mediaRecorder.onstop = () => {
      stream.getTracks().forEach((t) => t.stop());
      stopTimer();
      const blob = new Blob(chunks, { type: mediaRecorder.mimeType || "audio/webm" });
      analyze(blob);
    };
    mediaRecorder.start();
    startTimer();
    recordBtn.textContent = "■ Stop";
    recordBtn.classList.add("recording");
    results.hidden = true;
    setStatus("Recording… click Stop when you're done.");
  } catch {
    setStatus("Microphone access was denied. Please allow it and try again.", true);
  }
});

function startTimer() {
  seconds = 0;
  timerEl.textContent = fmt(0);
  timerId = setInterval(() => { seconds += 1; timerEl.textContent = fmt(seconds); }, 1000);
}
function stopTimer() {
  clearInterval(timerId);
  recordBtn.textContent = "● Record";
  recordBtn.classList.remove("recording");
}

async function analyze(blob) {
  setStatus("Analyzing your speech…");
  recordBtn.disabled = true;
  const fd = new FormData();
  fd.append("audio", blob, "recording.webm");
  try {
    const r = await fetch("/api/analyze", { method: "POST", body: fd });
    const data = await r.json();
    if (!r.ok) { setStatus(data.error || "Analysis failed.", true); return; }
    render(data);
    setStatus("");
  } catch {
    setStatus("Something went wrong contacting the server.", true);
  } finally {
    recordBtn.disabled = false;
  }
}

function colorFor(v) {
  return v >= 75 ? "var(--good)" : v >= 50 ? "var(--mid)" : "var(--bad)";
}

function render(data) {
  scoresEl.innerHTML = "";
  for (const [key, label] of Object.entries(SCORE_LABELS)) {
    const v = data.scores[key];
    const card = document.createElement("div");
    card.className = "score-card";
    card.innerHTML =
      `<div class="label">${label}</div>` +
      `<div class="value">${v}</div>` +
      `<div class="score-bar"><span style="width:${v}%;background:${colorFor(v)}"></span></div>`;
    scoresEl.appendChild(card);
  }
  transcriptEl.innerHTML = highlight(data.transcript, data.filler_words || []);
  feedbackEl.textContent = data.feedback;
  results.hidden = false;
}

function escapeHtml(s) {
  return s.replace(/[&<>"']/g, (c) =>
    ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
}

function highlight(transcript, fillers) {
  let html = escapeHtml(transcript);
  const uniq = [...new Set(fillers.filter(Boolean))];
  for (const f of uniq) {
    const esc = escapeHtml(f).replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
    html = html.replace(new RegExp(`\\b${esc}\\b`, "gi"),
      (m) => `<span class="filler">${m}</span>`);
  }
  return html;
}
```

- [ ] **Step 4: Replace the placeholder static/index.html**

The full `index.html` from Step 1 replaces the placeholder created in Task 4.

- [ ] **Step 5: Manual verification**

Ensure `.env` has a real `GEMINI_API_KEY`, then run:

```bash
python -m uvicorn main:app --reload
```

Open `http://127.0.0.1:8000`. Verify:
1. "Give me a prompt" shows a prompt.
2. "Record" requests mic permission, timer counts up, "Stop" ends it.
3. After a few seconds of speech, four score cards, a transcript (with any filler words highlighted), and feedback appear.
4. Recording under ~1s shows the "too short" error.

- [ ] **Step 6: Commit**

```bash
git add static/index.html static/style.css static/app.js
git commit -m "feat: SpeakWell frontend (record, prompt, results)"
```

---

### Task 6: README

**Files:**
- Create: `README.md`

- [ ] **Step 1: Write README.md**

````markdown
# SpeakWell

A local web app that coaches you on how well you speak. Record yourself in the
browser and get scores, a transcript, and coaching feedback powered by Google
Gemini 2.0 Flash.

## Setup

1. Install ffmpeg: `brew install ffmpeg` (macOS) or your platform's equivalent.
2. Install Python deps: `pip install -r requirements.txt`
3. Copy `.env.example` to `.env` and add your key:
   ```
   GEMINI_API_KEY=your_key_here
   ```
4. Run: `python -m uvicorn main:app --reload`
5. Open http://127.0.0.1:8000

## Tests

`python -m pytest`
````

- [ ] **Step 2: Commit**

```bash
git add README.md
git commit -m "docs: add README"
```

---

## Self-Review Notes

- **Spec coverage:** browser recording (Task 5), four dimensions + 0–100 scores (Tasks 3/5), prompt optional (Tasks 4/5), scores+transcript+highlighted fillers+feedback (Tasks 3/5), env-var key (Task 1), ffmpeg transcode (Task 2), stateless (no persistence anywhere), error handling for mic/short/missing-key/ffmpeg/Gemini (Tasks 1/2/4/5), tests with Gemini mocked (Tasks 1–4). All covered.
- **Type consistency:** `transcode_to_wav(bytes)->bytes`, `analyze_speech(bytes)->dict`, `parse_response(str)->dict`, `random_prompt()->str`, score keys `filler_words/pace_pauses/clarity_structure/confidence_tone` used identically in backend and frontend.
- **Placeholder scan:** none — every step contains concrete code/commands.
