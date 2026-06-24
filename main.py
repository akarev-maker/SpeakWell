# main.py
from fastapi import FastAPI, UploadFile, File, Form
from fastapi.responses import JSONResponse, FileResponse
from fastapi.staticfiles import StaticFiles

import audio
import gemini_client
import prompts

app = FastAPI(title="SpeakWell")

MIN_AUDIO_BYTES = 1000  # reject trivially short/empty recordings
MAX_AUDIO_BYTES = 25 * 1024 * 1024  # 25 MB cap to bound memory use


@app.get("/api/prompt")
def get_prompt():
    return {"prompt": prompts.random_prompt()}


@app.post("/api/analyze")
async def analyze(
    audio_file: UploadFile = File(..., alias="audio"),
    prompt: str = Form(""),
    context: str = Form(""),
):
    raw = await audio_file.read()
    if len(raw) < MIN_AUDIO_BYTES:
        return JSONResponse(
            status_code=400,
            content={"error": "Recording is too short. Please speak for a few seconds."},
        )
    if len(raw) > MAX_AUDIO_BYTES:
        return JSONResponse(
            status_code=413,
            content={"error": "Recording is too large. Please keep it under 25 MB."},
        )
    prompt = prompt.strip() or None
    context = context.strip() or None
    try:
        wav = audio.transcode_to_wav(raw)
        result = gemini_client.analyze_speech(wav, prompt=prompt, context=context)
    except Exception as exc:  # covers ffmpeg/config RuntimeError and google-genai APIError
        return JSONResponse(status_code=500, content={"error": str(exc)})
    return result


@app.get("/")
def index():
    return FileResponse("static/index.html")


app.mount("/static", StaticFiles(directory="static"), name="static")
