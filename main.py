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
