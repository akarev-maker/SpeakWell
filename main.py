# main.py
import json

from fastapi import FastAPI, UploadFile, File, Form
from fastapi.responses import JSONResponse, FileResponse
from fastapi.staticfiles import StaticFiles

import audio
import gemini_client
import prompts

app = FastAPI(title="SpeakWell")

MIN_AUDIO_BYTES = 1000  # reject trivially short/empty recordings
MAX_AUDIO_BYTES = 25 * 1024 * 1024  # 25 MB cap to bound memory use


@app.post("/api/prompt")
def get_prompt(context: str = Form("")):
    context = context.strip()
    if context:
        try:
            return {"prompt": gemini_client.generate_prompt(context)}
        except Exception:
            pass  # fall back to a generic prompt below
    return {"prompt": prompts.random_prompt()}


@app.post("/api/interview/start")
def interview_start(jd: str = Form(""), context: str = Form("")):
    ctx = jd.strip() or context.strip()
    if ctx:
        try:
            return {"questions": gemini_client.generate_interview_questions(ctx)}
        except Exception:
            pass  # fall back to a built-in set below
    return {"questions": prompts.interview_question_set()}


@app.post("/api/interview/followup")
def interview_followup(
    context: str = Form(""), question: str = Form(""), answer: str = Form("")
):
    try:
        return {"followup": gemini_client.generate_followup(context, question, answer)}
    except Exception:
        return {"followup": ""}  # empty -> frontend simply skips the follow-up


@app.post("/api/interview/summary")
def interview_summary(
    jd: str = Form(""), context: str = Form(""), answers: str = Form("[]")
):
    ctx = jd.strip() or context.strip() or "a job interview"
    try:
        qa_pairs = json.loads(answers)
        result = gemini_client.summarize_interview(ctx, qa_pairs)
    except Exception as exc:
        return JSONResponse(status_code=500, content={"error": str(exc)})
    return result


@app.post("/api/analyze")
async def analyze(
    audio_file: UploadFile = File(..., alias="audio"),
    prompt: str = Form(""),
    context: str = Form(""),
    interview: str = Form(""),
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
    is_interview = interview.strip().lower() in ("1", "true", "on", "yes")
    question = prompt if is_interview else None
    speech_prompt = None if is_interview else prompt
    try:
        wav = audio.transcode_to_wav(raw)
        result = gemini_client.analyze_speech(
            wav, prompt=speech_prompt, context=context, question=question
        )
    except Exception as exc:  # covers ffmpeg/config RuntimeError and google-genai APIError
        return JSONResponse(status_code=500, content={"error": str(exc)})
    return result


@app.get("/")
def index():
    return FileResponse("static/index.html")


app.mount("/static", StaticFiles(directory="static"), name="static")
