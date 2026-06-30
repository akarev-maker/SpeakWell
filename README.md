# SpeakWell

A local web app that coaches you on how well you speak. Record yourself in the
browser and get per-dimension scores, a transcript with filler words
highlighted, and written coaching feedback — powered by Google Gemini.

It coaches on four dimensions: **filler words**, **pace & pauses**,
**clarity & structure**, and **confidence & tone**.

> **Bring your own API key.** SpeakWell is self-hosted and ships with no key of
> its own. You run it locally and supply your own [Google Gemini API
> key](https://aistudio.google.com/apikey) (free tier works). Your key lives only
> in a local `.env` file that is git-ignored and never leaves your machine; audio
> is sent straight from your server to Google and nothing is stored between
> sessions.

## Setup

1. Install ffmpeg (used to transcode your browser recording):
   - **macOS** (Homebrew): `brew install ffmpeg`
   - **Windows** (winget): `winget install Gyan.FFmpeg` — or with Chocolatey:
     `choco install ffmpeg`
   - **Debian/Ubuntu**: `sudo apt install ffmpeg`
   - **Fedora/RHEL**: `sudo dnf install ffmpeg`
   - **Arch**: `sudo pacman -S ffmpeg`
   - **Anything else**: grab a static build from
     [ffmpeg.org/download](https://ffmpeg.org/download.html) and put `ffmpeg` on
     your `PATH`.

   Verify it's installed and on your `PATH`:
   ```
   ffmpeg -version
   ```
2. Install Python deps (Python 3.11+). A virtual environment is recommended:
   ```
   # macOS / Linux
   python3 -m venv .venv && source .venv/bin/activate

   # Windows (PowerShell)
   py -m venv .venv; .venv\Scripts\Activate.ps1

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
- The backend transcodes the audio to WAV with ffmpeg and sends it to Gemini,
  which returns scores, a transcript, detected filler words, and coaching
  feedback as JSON. The model defaults to `gemini-3.1-flash-lite` and is
  configurable via `GEMINI_MODEL` in `.env` — but it **must be an audio-capable
  Gemini model** (e.g. `gemini-3.1-flash-lite` or `gemini-2.5-flash`). Retired
  models like `gemini-2.0-flash` will not work.
- `GET /api/prompt` returns an optional speaking prompt if you want one.
- The app is stateless — nothing is saved between sessions.

## Tests

```
python -m pytest
```

Tests mock Gemini and ffmpeg, so they need neither an API key nor ffmpeg
installed.
