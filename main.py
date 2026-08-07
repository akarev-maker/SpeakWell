# main.py
import json
import logging
from pathlib import Path

from fastapi import FastAPI, Request, UploadFile, File, Form
from fastapi.responses import JSONResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from starlette.concurrency import run_in_threadpool
from starlette.formparsers import MultiPartParser

import audio
import gemini_client
import prompts
import storage

log = logging.getLogger(__name__)

app = FastAPI(title="SpeakWell")

# Anchored to this file so the server works from any working directory.
STATIC_DIR = Path(__file__).resolve().parent / "static"

MIN_AUDIO_BYTES = 1000  # reject trivially short/empty recordings
MAX_AUDIO_BYTES = 25 * 1024 * 1024  # 25 MB cap to bound memory use
_READ_CHUNK = 64 * 1024

# Whole-request ceiling, checked before the body is read. The audio cap alone
# can't bound memory: by the time a handler runs, the body is already buffered.
MAX_REQUEST_BYTES = MAX_AUDIO_BYTES + 1024 * 1024

# Starlette spools multipart uploads to a temp file past 1 MB by default, which
# would put recordings on disk and break the promise that audio only ever lives
# in memory. Raising the threshold above the request ceiling keeps every upload
# in RAM; the ceiling above is what bounds how much that can be.
MultiPartParser.spool_max_size = MAX_REQUEST_BYTES

# Ceiling on any single free-text field forwarded to Gemini — roomy enough for
# a full job description, tight enough that one request can't run up the bill.
MAX_TEXT_CHARS = 20_000
MAX_ANSWERS = 40

# Returned in place of an unexpected exception's text, which can carry
# subprocess output and SDK internals that the browser has no business seeing.
GENERIC_ERROR = "Something went wrong on the server. Check the server logs for details."


@app.middleware("http")
async def guard_request(request: Request, call_next):
    """Block cross-site writes and oversized bodies before anything reads them."""
    if request.method not in ("GET", "HEAD", "OPTIONS"):
        origin = request.headers.get("origin")
        # The API takes multipart forms, which browsers send cross-origin with
        # no CORS preflight — so any site the user visits could POST here and
        # spend their Gemini quota. Browsers always attach Origin to those
        # requests. A missing Origin means a non-browser client (curl, tests),
        # which was never the thing at risk of being tricked.
        if origin is not None and origin != f"{request.url.scheme}://{request.url.netloc}":
            return JSONResponse(
                status_code=403, content={"error": "Cross-site request blocked."}
            )
        declared = request.headers.get("content-length")
        if declared and declared.isdigit() and int(declared) > MAX_REQUEST_BYTES:
            return JSONResponse(
                status_code=413, content={"error": "Request body is too large."}
            )
    return await call_next(request)


def _clean(text: str) -> str:
    return text.strip()[:MAX_TEXT_CHARS]


async def _read_capped(upload: UploadFile, limit: int) -> bytes | None:
    """Read an upload, bailing out as soon as it exceeds `limit` bytes."""
    parts: list[bytes] = []
    total = 0
    while chunk := await upload.read(_READ_CHUNK):
        total += len(chunk)
        if total > limit:
            return None
        parts.append(chunk)
    return b"".join(parts)


def _parse_answers(raw: str) -> list[dict]:
    """Parse and bound the Q/A payload posted by the browser."""
    try:
        data = json.loads(raw)
    except (json.JSONDecodeError, ValueError) as exc:
        raise ValueError("Could not read the interview answers.") from exc
    if not isinstance(data, list):
        raise ValueError("Interview answers must be a list.")
    return [
        {
            "question": _clean(str(p.get("question", ""))),
            "answer": _clean(str(p.get("answer", ""))),
        }
        for p in data[:MAX_ANSWERS]
        if isinstance(p, dict)
    ]


@app.post("/api/prompt")
def get_prompt(context: str = Form("")):
    context = _clean(context)
    if context:
        try:
            return {"prompt": gemini_client.generate_prompt(context)}
        except Exception:
            # Logged rather than silently swallowed: otherwise a missing API key
            # looks like success here and only surfaces at analysis time.
            log.exception("Prompt generation failed; falling back to a built-in prompt")
    return {"prompt": prompts.random_prompt()}


@app.post("/api/interview/start")
def interview_start(jd: str = Form(""), context: str = Form("")):
    ctx = _clean(jd) or _clean(context)
    if ctx:
        try:
            return {"questions": gemini_client.generate_interview_questions(ctx)}
        except Exception:
            log.exception("Question generation failed; falling back to the built-in set")
    return {"questions": prompts.interview_question_set()}


@app.post("/api/interview/followup")
def interview_followup(
    context: str = Form(""), question: str = Form(""), answer: str = Form("")
):
    try:
        return {
            "followup": gemini_client.generate_followup(
                _clean(context), _clean(question), _clean(answer)
            )
        }
    except Exception:
        log.exception("Follow-up generation failed")
        return {"followup": ""}  # empty -> frontend simply skips the follow-up


@app.post("/api/interview/summary")
def interview_summary(
    jd: str = Form(""), context: str = Form(""), answers: str = Form("[]")
):
    ctx = _clean(jd) or _clean(context) or "a job interview"
    try:
        qa_pairs = _parse_answers(answers)
    except ValueError as exc:
        return JSONResponse(status_code=400, content={"error": str(exc)})
    try:
        return gemini_client.summarize_interview(ctx, qa_pairs)
    except RuntimeError as exc:
        return JSONResponse(status_code=500, content={"error": str(exc)})
    except Exception:
        log.exception("Interview summary failed")
        return JSONResponse(status_code=500, content={"error": GENERIC_ERROR})


@app.post("/api/analyze")
async def analyze(
    audio_file: UploadFile = File(..., alias="audio"),
    prompt: str = Form(""),
    context: str = Form(""),
    interview: str = Form(""),
):
    raw = await _read_capped(audio_file, MAX_AUDIO_BYTES)
    if raw is None:
        return JSONResponse(
            status_code=413,
            content={"error": "Recording is too large. Please keep it under 25 MB."},
        )
    if len(raw) < MIN_AUDIO_BYTES:
        return JSONResponse(
            status_code=400,
            content={"error": "Recording is too short. Please speak for a few seconds."},
        )
    prompt = _clean(prompt) or None
    context = _clean(context) or None
    is_interview = interview.strip().lower() in ("1", "true", "on", "yes")
    question = prompt if is_interview else None
    speech_prompt = None if is_interview else prompt
    try:
        # ffmpeg and the Gemini call each block for seconds at a time. This
        # handler must be async to read the upload, so the blocking work goes
        # to a worker thread — otherwise it stalls the whole event loop and the
        # server can't answer anything else until the analysis finishes.
        wav = await run_in_threadpool(audio.transcode_to_wav, raw)
        result = await run_in_threadpool(
            gemini_client.analyze_speech,
            wav, prompt=speech_prompt, context=context, question=question,
        )
    except RuntimeError as exc:
        # RuntimeError is what this codebase raises for messages meant to be
        # read by the user ("ffmpeg is not installed", "GEMINI_API_KEY is not
        # set"). Anything else is an internal detail.
        return JSONResponse(status_code=500, content={"error": str(exc)})
    except Exception:
        log.exception("Speech analysis failed")
        return JSONResponse(status_code=500, content={"error": GENERIC_ERROR})
    try:
        storage.save_session(
            mode="interview" if is_interview else "practice",
            label=(question or speech_prompt or "")[:120],
            scores=result.get("scores", {}),
        )
    except Exception:
        log.exception("Could not save session history")  # best-effort; never break analysis
    return result


@app.get("/api/progress")
def progress():
    return {"sessions": storage.recent_sessions(50)}


@app.get("/")
def index():
    return FileResponse(STATIC_DIR / "index.html")


app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
