# SpeakWell

A local web app that coaches you on how well you speak. Record yourself in the
browser and get per-dimension scores, a transcript with filler words
highlighted, and written coaching feedback — powered by Google Gemini 2.0 Flash.

It coaches on four dimensions: **filler words**, **pace & pauses**,
**clarity & structure**, and **confidence & tone**.

## Setup

1. Install ffmpeg (used to transcode your browser recording):
   - macOS: `brew install ffmpeg`
   - Debian/Ubuntu: `sudo apt install ffmpeg`
2. Install Python deps (Python 3.11+):
   ```
   pip install -r requirements.txt
   ```
3. Copy `.env.example` to `.env` and add your Gemini API key:
   ```
   GEMINI_API_KEY=your_key_here
   ```
4. Run the server from the project root:
   ```
   python -m uvicorn main:app --reload
   ```
5. Open http://127.0.0.1:8000 and click **Record**.

## How it works

- The browser captures your microphone with the MediaRecorder API and POSTs the
  audio to `POST /api/analyze`.
- The backend transcodes the audio to WAV with ffmpeg and sends it to Gemini
  2.0 Flash, which returns scores, a transcript, detected filler words, and
  coaching feedback as JSON.
- `GET /api/prompt` returns an optional speaking prompt if you want one.
- The app is stateless — nothing is saved between sessions.

## Tests

```
python -m pytest
```

Tests mock Gemini and ffmpeg, so they need neither an API key nor ffmpeg
installed.
