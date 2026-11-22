"""SpeakWell web server: setup -> plan -> turn-by-turn interview -> grading -> history."""
import logging
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

from fastapi import FastAPI, File, Form, Request, UploadFile
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from starlette.concurrency import run_in_threadpool
from starlette.formparsers import MultiPartParser

import audio
import catalog
import config
import grading
import interviewer
import models
import planner
import session as sessions
import storage
from pricing import CostMeter

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logging.getLogger("httpx").setLevel(logging.WARNING)
log = logging.getLogger("speakwell")

app = FastAPI(title="SpeakWell")
STATIC_DIR = Path(__file__).resolve().parent / "static"

MAX_ANSWER_BYTES = 8 * 1024 * 1024  # one answer; 5 min of 32 kbps Opus is ~1.2 MB
MIN_ANSWER_BYTES = 1500  # anything smaller is a click, not speech
MAX_REQUEST_BYTES = MAX_ANSWER_BYTES + 1024 * 1024
MAX_TYPED_CHARS = 4_000
MAX_WORK_CHARS = 20_000
MAX_RESUME_CHARS = planner.MAX_RESUME_CHARS
_READ_CHUNK = 64 * 1024

# Starlette spools uploads to a temp file past 1 MB by default, which would put
# recordings on disk. Raising the threshold above the request ceiling keeps
# every upload in RAM; the ceiling is what bounds how much that can be.
MultiPartParser.spool_max_size = MAX_REQUEST_BYTES

GENERIC_ERROR = "Something went wrong on the server. Check the server logs for details."


def _same_origin(origin: str | None, scheme: str, netloc: str) -> bool:
    # A missing Origin means a non-browser client (curl, tests), which was never
    # the thing at risk of being tricked by another website.
    if origin is None:
        return True
    scheme = {"ws": "http", "wss": "https"}.get(scheme, scheme)
    return origin == f"{scheme}://{netloc}"


@app.middleware("http")
async def guard_request(request: Request, call_next):
    """Block cross-site writes and oversized bodies before anything reads them."""
    if request.method not in ("GET", "HEAD", "OPTIONS"):
        # Multipart forms are sent cross-origin with no CORS preflight, so any
        # site you visit could otherwise POST here and spend your API budget.
        if not _same_origin(request.headers.get("origin"), request.url.scheme, request.url.netloc):
            return JSONResponse(status_code=403, content={"error": "Cross-site request blocked."})
        declared = request.headers.get("content-length")
        if declared and declared.isdigit() and int(declared) > MAX_REQUEST_BYTES:
            return JSONResponse(status_code=413, content={"error": "Request body is too large."})
    return await call_next(request)


def _error(status: int, message: str) -> JSONResponse:
    return JSONResponse(status_code=status, content={"error": message})


# --- setup ---------------------------------------------------------------------
@app.get("/api/meta")
def meta():
    resume = storage.get_resume()
    return {
        **catalog.options(),
        "budget": {"month_usd": round(storage.month_spend_usd(), 2), "limit_usd": config.MONTHLY_BUDGET_USD},
        "has_resume": bool(resume and resume["text"].strip()),
    }


class StartRequest(BaseModel):
    kind: str
    track: str
    level: str
    persona: str = "random"


@app.post("/api/interviews")
def start_interview(req: StartRequest):
    spent = storage.month_spend_usd()
    if spent >= config.MONTHLY_BUDGET_USD:
        return _error(402, (
            f"This month's estimated spend (${spent:.2f}) has reached your "
            f"${config.MONTHLY_BUDGET_USD:.2f} budget, so new interviews are paused until "
            "next month. To change the limit, set SPEAKWELL_MONTHLY_BUDGET_USD in .env."))
    resume = storage.get_resume()
    meter = CostMeter()
    try:
        planned = planner.build_plan(
            req.kind, req.track, req.level, req.persona,
            recent_seeds=storage.recent_seeds(req.kind, req.track),
            resume=resume["text"] if resume else None, meter=meter,
        )
    except ValueError as exc:
        return _error(400, str(exc))
    except models.ModelError as exc:
        storage.record_spend(meter.total, "interview plan (failed)")
        return _error(503, str(exc))
    except Exception:
        log.exception("Planning failed")
        return _error(500, GENERIC_ERROR)
    s = sessions.InterviewSession(planned, meter)
    s.flush_spend("interview plan")
    sessions.add(s)
    log.info("Interview %s planned by %s: %s, seeds=%s, persona=%s",
             s.id, s.planner_model, s.kind, s.seed_titles, s.persona.id)
    return s.public_info()


# --- the interview, one turn at a time -----------------------------------------
def _live_session(sid: str):
    s = sessions.get(sid)
    if s is None:
        return None, _error(404, "That interview has expired. Start a new one.")
    if s.state != "live":
        return None, _error(409, "This interview isn't running.")
    return s, None


def _turn_payload(s: sessions.InterviewSession, reply: dict, heard: str = "") -> dict:
    if reply.get("ended"):
        s.state, s.ended_at = "ended", time.monotonic()
    s.flush_spend("interview turns")
    return {"heard": heard, "say": reply["say"], "reveal": reply.get("reveal"), "ended": bool(reply.get("ended")),
            "answer_limit_s": interviewer.answer_limit(s), "elapsed_s": round(s.now(), 1)}


@app.post("/api/interviews/{sid}/begin")
def begin_interview(sid: str):
    s = sessions.get(sid)
    if s is None:
        return _error(404, "That interview has expired. Start a new one.")
    if s.state != "ready":
        return _error(409, "This interview has already started.")
    s.t0 = time.monotonic()
    s.state = "live"
    s.log("event", f"Phase: {s.phase['name']}", t=0)
    say = interviewer.opening(s)
    s.log("interviewer", say, t=0)
    return {"say": say, "voice_hint": s.persona.id, "answer_limit_s": interviewer.answer_limit(s),
            "minutes": s.minutes}


@app.post("/api/interviews/{sid}/turn")
async def interview_turn(
    sid: str,
    answer: UploadFile | None = File(None),
    text: str = Form(""),
    started_at: float = Form(0.0),
    duration: float = Form(0.0),
    auto_stopped: bool = Form(False),
    work: str = Form(""),
    event: str = Form(""),
):
    s, err = _live_session(sid)
    if err:
        return err
    if s.busy:
        return _error(409, "Still working on your last answer.")
    s.busy = True
    try:
        s.latest_work = work[:MAX_WORK_CHARS] if work else s.latest_work
        started_at = max(0.0, min(float(started_at), s.now()))
        heard = ""
        if event == "time_up":
            pass
        elif answer is not None:
            raw = await _read_capped(answer, MAX_ANSWER_BYTES)
            if raw is None:
                return _error(413, "That answer is too long to upload.")
            if len(raw) < MIN_ANSWER_BYTES:
                return {"heard": "", "say": None, "message": "I didn't catch that. Try again."}
            mp3 = await run_in_threadpool(audio.to_mp3, raw)
            words = await run_in_threadpool(grading.transcribe_turn, mp3, s.meter)
            if not words:
                s.flush_spend("interview turns")
                return {"heard": "", "say": None, "message": "I didn't hear any words. Check your mic and try again."}
            for w in words:
                s.words.append({"text": w["text"], "start": w["start"] + started_at, "end": w["end"] + started_at})
            s.audio.append(mp3)
            heard = " ".join(w["text"] for w in words)
            s.log("candidate", heard, t=started_at)
        elif text.strip():
            heard = text.strip()[:MAX_TYPED_CHARS]
            s.log("candidate", heard, t=started_at)
            s.timeline[-1]["typed"] = True
        else:
            return _error(400, "Send an answer.")
        reply = await run_in_threadpool(interviewer.respond, s, float(duration), bool(auto_stopped), event)
        return _turn_payload(s, reply, heard)
    except models.ModelError as exc:
        s.flush_spend("interview turns")
        return _error(503, f"{exc} Your answer was saved; press Retry to get the reply.")
    except RuntimeError as exc:
        return _error(400, str(exc))
    except Exception:
        log.exception("Turn failed")
        return _error(500, GENERIC_ERROR)
    finally:
        s.busy = False


@app.post("/api/interviews/{sid}/retry")
async def interview_retry(sid: str):
    """Ask for the interviewer's reply again, after a failed turn (no re-upload)."""
    s, err = _live_session(sid)
    if err:
        return err
    if s.busy:
        return _error(409, "Still working on your last answer.")
    s.busy = True
    try:
        reply = await run_in_threadpool(interviewer.respond, s)
        return _turn_payload(s, reply)
    except models.ModelError as exc:
        return _error(503, str(exc))
    finally:
        s.busy = False


@app.post("/api/interviews/{sid}/end")
def end_interview(sid: str, work: str = Form("")):
    s = sessions.get(sid)
    if s is None:
        return _error(404, "That interview has expired.")
    if s.state == "live":
        s.latest_work = work[:MAX_WORK_CHARS] if work else s.latest_work
        s.ended_early = s.now() < s.minutes * 60 - 90
        s.end_reason = "you ended it"
        s.state, s.ended_at = "ended", time.monotonic()
        s.log("event", "Candidate ended the interview")
        # Free the Google-side cache without making you wait on it.
        threading.Thread(target=interviewer.release_cache, args=(s,), daemon=True).start()
    return {"ok": True, "elapsed_s": round(s.elapsed_s)}


# --- grading ---------------------------------------------------------------------
async def _read_capped(upload: UploadFile, limit: int) -> bytes | None:
    parts, total = [], 0
    while chunk := await upload.read(_READ_CHUNK):
        total += len(chunk)
        if total > limit:
            return None
        parts.append(chunk)
    return b"".join(parts)


def _run_grading(s: sessions.InterviewSession, final_work: str) -> None:
    def progress(stage: str) -> None:
        s.grade_stage = stage

    try:
        report = grading.grade(s, final_work, progress)
        report["cost"] = s.meter.as_dict()
        s.flush_spend("grading")
        storage.save_interview({
            "id": s.id, "created_at": datetime.now(timezone.utc).isoformat(),
            "kind": s.kind, "track": s.track, "level": s.level, "persona": s.persona.id,
            "seeds": s.seeds, "title": s.title, "duration_sec": int(s.elapsed_s),
            "ended_early": s.ended_early, "overall_score": report.get("overall_score"),
            "scores": grading.scores_for_history(report), "report": report,
            "cost_usd": s.meter.total,
        })
        s.report = report
        s.state = "graded"
        s.grade_stage = "done"
    except models.ModelError as exc:
        s.flush_spend("grading (failed)")
        s.error, s.state, s.grade_stage = str(exc), "error", "error"
    except Exception:
        log.exception("Grading failed for %s", s.id)
        s.flush_spend("grading (failed)")
        s.error, s.state, s.grade_stage = GENERIC_ERROR, "error", "error"


@app.post("/api/interviews/{sid}/grade")
def grade_interview(sid: str, final_work: str = Form("")):
    s = sessions.get(sid)
    if s is None:
        return _error(404, "That interview has expired. Interviews must be graded within 3 hours.")
    if s.state not in ("ended", "error"):
        return _error(409, "The interview hasn't ended yet." if s.state in ("live", "connecting", "ready")
                      else "This interview is already being graded.")
    if s.t0 is None or not any(e["who"] == "candidate" for e in s.timeline):
        return _error(400, "The interview never got going, so there's nothing to grade.")
    final = (final_work or s.latest_work)[:MAX_WORK_CHARS]
    s.state, s.grade_stage, s.error = "grading", "starting", ""
    threading.Thread(target=_run_grading, args=(s, final), daemon=True).start()
    return {"ok": True}


@app.get("/api/interviews/{sid}/grade")
def grade_status(sid: str):
    s = sessions.get(sid)
    if s is None:
        saved = storage.get_interview(sid)
        if saved:
            return {"stage": "done", "report": saved["report"], "id": sid}
        return _error(404, "That interview has expired.")
    out = {"stage": s.grade_stage, "id": sid}
    if s.state == "graded":
        out["report"] = s.report
    elif s.state == "error":
        out["error"] = s.error
    return out


# --- history ---------------------------------------------------------------------
@app.get("/api/history")
def history():
    return {"interviews": storage.list_interviews(200)}


@app.get("/api/history/{sid}")
def history_item(sid: str):
    item = storage.get_interview(sid)
    return item if item else _error(404, "Not found.")


@app.delete("/api/history/{sid}")
def history_delete(sid: str):
    return {"ok": storage.delete_interview(sid)}


# --- resume ----------------------------------------------------------------------
class ResumeBody(BaseModel):
    text: str


@app.get("/api/resume")
def resume_get():
    return storage.get_resume() or {"text": "", "updated_at": None}


@app.put("/api/resume")
def resume_put(body: ResumeBody):
    text = body.text.strip()
    if len(text) > MAX_RESUME_CHARS:
        return _error(413, f"Resume is too long (max {MAX_RESUME_CHARS:,} characters).")
    if not text:
        return _error(400, "Paste your resume text first.")
    storage.save_resume(text)
    return storage.get_resume()


@app.delete("/api/resume")
def resume_delete():
    storage.clear_resume()
    return {"ok": True}


# --- static ----------------------------------------------------------------------
@app.get("/")
def index():
    return FileResponse(STATIC_DIR / "index.html")


app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
