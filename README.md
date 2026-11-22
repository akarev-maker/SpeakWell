# SpeakWell

A local mock-interview simulator you do out loud. An AI interviewer runs a
structured interview: it leads, probes your answers, cuts you off when you
ramble, and keeps its opinion to itself. You press to talk, so you can pause and
think as long as you need. When it's over you get a graded report with feedback
pinned to the exact moment you said something.

**Interviews**

| Interview | Length | What you do |
|---|---|---|
| Coding | 45 min | Solve a problem in a Python editor while talking it through. Hints are available and cost a little. |
| System design | 45 min | Design a system out loud, with a notes box. Ask for requirements; numbers are only given if you ask. |
| Behavioral | 30 min | Tell real stories; expect follow-ups on what *you* did. |
| Resume deep dive | 30 min | Explain the projects on your saved resume, then get drilled on them. |

Tracks: Software Engineering, AI/ML Engineering, Cybersecurity. Levels: Intern,
New grad. Interviewer styles: Warm, Neutral, Tough, or random.

**The report** has an overall score and rubric scores (0–100, so you can track
progress), moment-by-moment feedback (timestamp, your exact words, what was
wrong, what to say instead), filler words counted from a verbatim transcript,
pace, engagement and confidence from your voice, a review of your code or
design, a grade for your questions to the interviewer, and what the interviewer
was looking for. Click a timestamp to hear that moment.

## Setup

1. Install ffmpeg: `brew install ffmpeg` (macOS), `sudo apt install ffmpeg`
   (Debian/Ubuntu), or `winget install Gyan.FFmpeg` (Windows).
2. Python 3.11+:
   ```
   python3 -m venv .venv && source .venv/bin/activate
   pip install -r requirements.txt
   ```
3. Copy `.env.example` to `.env` and set `GEMINI_API_KEY`. Use a key from a
   project with billing linked (see [Cost](#cost)); free-tier keys can't use
   the default models and let Google use your data for training.
4. Run it and open http://127.0.0.1:8000 in **Chrome**:
   ```
   python -m uvicorn main:app
   ```
   Press **Start answer** (or Space, or ⌘↵ while typing code) to talk, and again
   when you're done. The interviewer's voice is Chrome's built-in speech, with
   captions. You can also type an answer.

## How it works

```
Setup ─► Planner (Gemini 4 Argon) writes a hidden plan from a curated topic
      ─► Each turn: you answer ─► verbatim transcript (English, word timestamps)
           ─► director (code) works out phase, clock, answer length
           ─► interviewer model (Gemini 3.8 Flash) writes the reply ─► checked ─► spoken by Chrome
      ─► Grading: voice analysis + rubric grading (Argon) ─► report ─► SQLite
```

- **The server owns the structure, the model writes the words.** Phases and
  time budgets are fixed per interview type (`catalog.py`). Every reply is
  checked before you hear it (`interviewer.py`): English only, phases only
  move forward one step, the "your questions" slot can't start too early, and
  the interview only ends at the end.
- **The director** adds private instructions each turn: move on when a phase
  overruns, protect time for your questions, react when you were cut off at
  the answer time limit, and only answer questions in the final phase.
- **Grading** (`grading.py`) reuses the per-answer transcripts, so filler
  counts and timestamps are exact, and only keeps feedback whose quote
  actually appears in what you said.

A deeper walkthrough is in [`docs/LEARN.md`](docs/LEARN.md), and the design
history in [`docs/design/specs/2026-11-20-speakwell-interview-revamp-design.md`](docs/design/specs/2026-11-20-speakwell-interview-revamp-design.md).

## Cost

Google AI Pro includes $10/month of Gemini API credits, which apply to a paid
API key ([how to claim them](https://aistudio.google.com/docs/google-ai-plans)).
Credits are used before your $5 prepaid balance.

Measured on test runs: an interviewer reply costs about $0.002 early in the
interview and $0.008 near the end of a long one; planning is about $0.06 and
grading $0.06–0.25. A full 45-minute interview should land around
**$0.50–0.70**, most of it transcription and grading.

- The header shows **estimated** spend this month. New interviews are refused
  once it reaches `SPEAKWELL_MONTHLY_BUDGET_USD` (default $10).
- Each report and history row shows that interview's estimated cost.
- Estimates use the higher of current and announced prices (`pricing.py`).
  Google's bill is the source of truth: check [AI Studio usage](https://aistudio.google.com/usage)
  and set a [spend cap](https://aistudio.google.com/spend) as a backstop.

What keeps it cheap: Argon (the strongest, most expensive model) runs only
twice, to plan and to grade. Replies use Gemini 3.8 Flash, and the intro and
closing small talk use Flash-Lite. The ~4k-token interviewer brief is stored
once in a Google-side cache and billed at a tenth of the price on later turns.
Silence is never sent anywhere, and the interviewer's voice is free (Chrome).

## Privacy

- **Audio:** each answer is sent to Google for transcription (with
  `store=false`, so Google doesn't keep the request) and, at the end, for voice
  analysis. On the server it lives only in memory, never on disk. A full-session
  copy stays in your browser tab for the report's player.
- **Stored locally** in `speakwell.db` (git-ignored): scores, feedback (which
  quotes short phrases you said), interview metadata, estimated cost, and your
  saved resume. No transcripts, recordings or code.
- **API key:** only in your git-ignored `.env`. The browser never sees it.
- On a paid key, Google doesn't use your prompts to improve its products. On
  the free tier it may, and human reviewers may read them.
- **No authentication.** It listens on `127.0.0.1` and rejects cross-site
  requests. Don't expose it to a network without adding auth.

## Tests

```
python -m pytest
```

Tests mock Gemini, so they need no API key and make no network calls.
