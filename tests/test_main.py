# tests/test_main.py
import asyncio
import io
import json
import time

import httpx
import pytest
from fastapi.testclient import TestClient

import main
import storage


@pytest.fixture(autouse=True)
def temp_db(tmp_path, monkeypatch):
    # Point the history DB at a throwaway file so tests never touch speakwell.db.
    monkeypatch.setattr(storage, "DB_PATH", str(tmp_path / "test.db"))


@pytest.fixture
def client():
    return TestClient(main.app)


def test_prompt_endpoint_no_context_is_random(client):
    resp = client.post("/api/prompt")
    assert resp.status_code == 200
    assert isinstance(resp.json()["prompt"], str)
    assert resp.json()["prompt"]


def test_prompt_tailored_to_context(client, monkeypatch):
    monkeypatch.setattr(
        main.gemini_client, "generate_prompt", lambda c: f"Tailored for: {c}"
    )
    resp = client.post("/api/prompt", data={"context": "Sales pitching"})
    assert resp.status_code == 200
    assert resp.json()["prompt"] == "Tailored for: Sales pitching"


def test_prompt_falls_back_when_generation_fails(client, monkeypatch):
    def boom(c):
        raise RuntimeError("gemini down")
    monkeypatch.setattr(main.gemini_client, "generate_prompt", boom)
    resp = client.post("/api/prompt", data={"context": "Sales pitching"})
    assert resp.status_code == 200
    assert resp.json()["prompt"]  # a fallback random prompt


def test_interview_start_from_jd(client, monkeypatch):
    captured = {}

    def fake_gen(ctx):
        captured["ctx"] = ctx
        return ["Q1?", "Q2?"]

    monkeypatch.setattr(main.gemini_client, "generate_interview_questions", fake_gen)
    resp = client.post(
        "/api/interview/start",
        data={"jd": "Backend engineer at a payments company"},
    )
    assert resp.status_code == 200
    assert resp.json()["questions"] == ["Q1?", "Q2?"]
    assert "payments" in captured["ctx"]


def test_interview_start_falls_back(client, monkeypatch):
    def boom(ctx):
        raise RuntimeError("down")

    monkeypatch.setattr(main.gemini_client, "generate_interview_questions", boom)
    resp = client.post("/api/interview/start", data={"jd": "anything"})
    assert resp.status_code == 200
    assert len(resp.json()["questions"]) >= 1  # built-in fallback set


def test_interview_followup(client, monkeypatch):
    monkeypatch.setattr(
        main.gemini_client, "generate_followup", lambda c, q, a: f"FU:{a}"
    )
    resp = client.post(
        "/api/interview/followup",
        data={"context": "x", "question": "q", "answer": "my answer"},
    )
    assert resp.status_code == 200
    assert resp.json()["followup"] == "FU:my answer"


def test_interview_followup_empty_on_error(client, monkeypatch):
    def boom(c, q, a):
        raise RuntimeError("down")

    monkeypatch.setattr(main.gemini_client, "generate_followup", boom)
    resp = client.post(
        "/api/interview/followup",
        data={"context": "x", "question": "q", "answer": "a"},
    )
    assert resp.status_code == 200
    assert resp.json()["followup"] == ""


def test_interview_summary(client, monkeypatch):
    captured = {}

    def fake_sum(ctx, qa):
        captured["qa"] = qa
        return {"level": "Getting there", "summary": "ok",
                "strengths": ["a"], "improvements": ["b"]}

    monkeypatch.setattr(main.gemini_client, "summarize_interview", fake_sum)
    resp = client.post(
        "/api/interview/summary",
        data={
            "jd": "SWE role",
            "answers": json.dumps([{"question": "Q1?", "answer": "my answer"}]),
        },
    )
    assert resp.status_code == 200
    assert resp.json()["level"] == "Getting there"
    assert captured["qa"] == [{"question": "Q1?", "answer": "my answer"}]


def test_interview_summary_handles_error(client, monkeypatch):
    def boom(ctx, qa):
        raise RuntimeError("summary down")

    monkeypatch.setattr(main.gemini_client, "summarize_interview", boom)
    resp = client.post(
        "/api/interview/summary",
        data={"answers": json.dumps([{"question": "q", "answer": "a"}])},
    )
    assert resp.status_code == 500
    assert "error" in resp.json()


def test_analyze_interview_forwards_question_and_returns_extra(client, monkeypatch):
    captured = {}
    monkeypatch.setattr(main.audio, "transcode_to_wav", lambda b: b"WAV")
    fake = {
        "scores": {"filler_words": 70, "pace_pauses": 80,
                   "clarity_structure": 75, "confidence_tone": 78},
        "transcript": "hi", "filler_words": [], "feedback": "Nice.", "tips": ["x"],
        "answer_critique": "Decent.", "model_answer": "Better answer here.",
    }

    def fake_analyze(b, prompt=None, context=None, question=None):
        captured["question"] = question
        captured["prompt"] = prompt
        return fake

    monkeypatch.setattr(main.gemini_client, "analyze_speech", fake_analyze)
    resp = client.post(
        "/api/analyze",
        files={"audio": ("rec.webm", io.BytesIO(b"x" * 1500), "audio/webm")},
        data={"prompt": "Why do you want this job?", "interview": "1"},
    )
    assert resp.status_code == 200
    assert captured["question"] == "Why do you want this job?"
    assert captured["prompt"] is None  # not double-passed as a speech prompt
    assert resp.json()["model_answer"] == "Better answer here."


def test_analyze_success(client, monkeypatch):
    monkeypatch.setattr(main.audio, "transcode_to_wav", lambda b: b"WAV")
    fake = {
        "scores": {"filler_words": 70, "pace_pauses": 80,
                   "clarity_structure": 75, "confidence_tone": 78},
        "transcript": "hello world", "filler_words": [], "feedback": "Nice.",
    }
    monkeypatch.setattr(
        main.gemini_client, "analyze_speech", lambda b, prompt=None, context=None, question=None: fake
    )
    resp = client.post(
        "/api/analyze",
        files={"audio": ("rec.webm", io.BytesIO(b"x" * 1500), "audio/webm")},
    )
    assert resp.status_code == 200
    assert resp.json()["scores"]["pace_pauses"] == 80


def test_analyze_forwards_prompt(client, monkeypatch):
    captured = {}
    monkeypatch.setattr(main.audio, "transcode_to_wav", lambda b: b"WAV")
    fake = {
        "scores": {"filler_words": 70, "pace_pauses": 80,
                   "clarity_structure": 75, "confidence_tone": 78},
        "transcript": "hello", "filler_words": [], "feedback": "Nice.",
    }

    def fake_analyze(b, prompt=None, context=None, question=None):
        captured["prompt"] = prompt
        return fake

    monkeypatch.setattr(main.gemini_client, "analyze_speech", fake_analyze)
    resp = client.post(
        "/api/analyze",
        files={"audio": ("rec.webm", io.BytesIO(b"x" * 1500), "audio/webm")},
        data={"prompt": "Describe your ideal weekend."},
    )
    assert resp.status_code == 200
    assert captured["prompt"] == "Describe your ideal weekend."


def test_analyze_forwards_context(client, monkeypatch):
    captured = {}
    monkeypatch.setattr(main.audio, "transcode_to_wav", lambda b: b"WAV")
    fake = {
        "scores": {"filler_words": 70, "pace_pauses": 80,
                   "clarity_structure": 75, "confidence_tone": 78},
        "transcript": "hi", "filler_words": [], "feedback": "Nice.", "tips": ["x"],
    }

    def fake_analyze(b, prompt=None, context=None, question=None):
        captured["context"] = context
        return fake

    monkeypatch.setattr(main.gemini_client, "analyze_speech", fake_analyze)
    resp = client.post(
        "/api/analyze",
        files={"audio": ("rec.webm", io.BytesIO(b"x" * 1500), "audio/webm")},
        data={"context": "Junior developer, interview prep"},
    )
    assert resp.status_code == 200
    assert captured["context"] == "Junior developer, interview prep"


def test_analyze_blank_prompt_becomes_none(client, monkeypatch):
    captured = {}
    monkeypatch.setattr(main.audio, "transcode_to_wav", lambda b: b"WAV")
    fake = {
        "scores": {"filler_words": 70, "pace_pauses": 80,
                   "clarity_structure": 75, "confidence_tone": 78},
        "transcript": "hello", "filler_words": [], "feedback": "Nice.",
    }

    def fake_analyze(b, prompt=None, context=None, question=None):
        captured["prompt"] = prompt
        return fake

    monkeypatch.setattr(main.gemini_client, "analyze_speech", fake_analyze)
    resp = client.post(
        "/api/analyze",
        files={"audio": ("rec.webm", io.BytesIO(b"x" * 1500), "audio/webm")},
        data={"prompt": "   "},
    )
    assert resp.status_code == 200
    assert captured["prompt"] is None


def test_analyze_rejects_oversized_audio(client, monkeypatch):
    monkeypatch.setattr(main, "MAX_AUDIO_BYTES", 2000)
    resp = client.post(
        "/api/analyze",
        files={"audio": ("rec.webm", io.BytesIO(b"x" * 3000), "audio/webm")},
    )
    assert resp.status_code == 413
    assert "error" in resp.json()


def test_analyze_saves_session(client, monkeypatch):
    monkeypatch.setattr(main.audio, "transcode_to_wav", lambda b: b"WAV")
    fake = {
        "scores": {"filler_words": 70, "pace_pauses": 80,
                   "clarity_structure": 75, "confidence_tone": 78},
        "transcript": "hi", "filler_words": [], "feedback": "ok", "tips": ["x"],
    }
    monkeypatch.setattr(
        main.gemini_client, "analyze_speech",
        lambda b, prompt=None, context=None, question=None: fake,
    )
    client.post(
        "/api/analyze",
        files={"audio": ("rec.webm", io.BytesIO(b"x" * 1500), "audio/webm")},
        data={"prompt": "Tell me about yourself"},
    )
    rows = storage.recent_sessions(10)
    assert len(rows) == 1
    assert rows[0]["mode"] == "practice"
    assert rows[0]["filler_words"] == 70
    assert rows[0]["label"] == "Tell me about yourself"


def test_analyze_does_not_block_the_event_loop(monkeypatch):
    # /api/analyze must be async to read the upload, so its blocking work
    # (ffmpeg, the Gemini call) has to be handed to a worker thread. Run
    # directly on the loop it would freeze every other request for its whole
    # duration — this asserts a concurrent request still gets served promptly.
    blocking_sec = 0.6

    def slow_transcode(raw):
        time.sleep(blocking_sec)  # stands in for ffmpeg
        return b"WAV"

    fake = {
        "scores": {"filler_words": 70, "pace_pauses": 80,
                   "clarity_structure": 75, "confidence_tone": 78},
        "transcript": "hi", "filler_words": [], "feedback": "ok", "tips": ["x"],
    }
    monkeypatch.setattr(main.audio, "transcode_to_wav", slow_transcode)
    monkeypatch.setattr(
        main.gemini_client, "analyze_speech",
        lambda b, prompt=None, context=None, question=None: fake,
    )

    async def scenario():
        transport = httpx.ASGITransport(app=main.app)
        async with httpx.AsyncClient(transport=transport, base_url="http://t") as ac:
            start = time.monotonic()
            done = {}

            async def run_analyze():
                r = await ac.post(
                    "/api/analyze",
                    files={"audio": ("rec.webm", io.BytesIO(b"x" * 1500), "audio/webm")},
                )
                done["analyze"] = time.monotonic() - start
                return r

            async def run_progress():
                await asyncio.sleep(0.05)  # queue up just after analyze begins
                r = await ac.get("/api/progress")
                done["progress"] = time.monotonic() - start
                return r

            # Timed from a fixed start, not from after the blocking call: a
            # blocked loop delays run_progress from even beginning, so only an
            # absolute clock catches it.
            analyzed, progressed = await asyncio.gather(run_analyze(), run_progress())
            return analyzed.status_code, progressed.status_code, done

    analyze_status, progress_status, done = asyncio.run(scenario())
    assert analyze_status == 200
    assert progress_status == 200
    assert done["progress"] < blocking_sec / 2, (
        f"/api/progress only finished at {done['progress']:.2f}s "
        f"(analysis took {done['analyze']:.2f}s) — the event loop is blocked"
    )


def test_progress_endpoint(client):
    resp = client.get("/api/progress")
    assert resp.status_code == 200
    assert resp.json()["sessions"] == []


def test_analyze_empty_audio_rejected(client):
    resp = client.post(
        "/api/analyze",
        files={"audio": ("rec.webm", io.BytesIO(b""), "audio/webm")},
    )
    assert resp.status_code == 400
    assert "error" in resp.json()


def test_analyze_handles_backend_error(client, monkeypatch):
    monkeypatch.setattr(main.audio, "transcode_to_wav", lambda b: b"WAV")
    def boom(b, prompt=None, context=None, question=None):
        raise RuntimeError("gemini down")
    monkeypatch.setattr(main.gemini_client, "analyze_speech", boom)
    resp = client.post(
        "/api/analyze",
        files={"audio": ("rec.webm", io.BytesIO(b"x" * 1500), "audio/webm")},
    )
    assert resp.status_code == 500
    assert "gemini down" in resp.json()["error"]


def test_analyze_unexpected_error_is_not_leaked(client, monkeypatch):
    # RuntimeError carries messages this codebase wrote for the user; anything
    # else is an internal detail (SDK internals, subprocess output) and must not
    # reach the browser.
    monkeypatch.setattr(main.audio, "transcode_to_wav", lambda b: b"WAV")
    def boom(b, prompt=None, context=None, question=None):
        raise ValueError("api boom: key=sk-secret at /srv/app/internals.py")
    monkeypatch.setattr(main.gemini_client, "analyze_speech", boom)
    resp = client.post(
        "/api/analyze",
        files={"audio": ("rec.webm", io.BytesIO(b"x" * 1500), "audio/webm")},
    )
    assert resp.status_code == 500
    assert "sk-secret" not in resp.json()["error"]
    assert "internals.py" not in resp.json()["error"]
    assert resp.json()["error"] == main.GENERIC_ERROR


def test_cross_site_post_is_blocked(client):
    resp = client.post(
        "/api/prompt",
        data={"context": "x"},
        headers={"Origin": "https://evil.example"},
    )
    assert resp.status_code == 403


def test_same_origin_post_is_allowed(client):
    resp = client.post(
        "/api/prompt", headers={"Origin": "http://testserver"}
    )
    assert resp.status_code == 200


def test_oversized_content_length_rejected_before_read(client, monkeypatch):
    # The body is never parsed: the declared length alone is enough to refuse.
    monkeypatch.setattr(main.audio, "transcode_to_wav", lambda b: b"WAV")
    resp = client.post(
        "/api/analyze",
        content=b"x" * 100,
        headers={
            "Content-Type": "multipart/form-data; boundary=x",
            "Content-Length": str(main.MAX_REQUEST_BYTES + 1),
        },
    )
    assert resp.status_code == 413


def test_summary_rejects_malformed_answers(client):
    resp = client.post("/api/interview/summary", data={"answers": "not json"})
    assert resp.status_code == 400
    resp = client.post("/api/interview/summary", data={"answers": '{"a": 1}'})
    assert resp.status_code == 400


def test_summary_ignores_non_object_entries(client, monkeypatch):
    captured = {}

    def fake_sum(ctx, qa):
        captured["qa"] = qa
        return {"level": "ok", "summary": "s", "strengths": [], "improvements": []}

    monkeypatch.setattr(main.gemini_client, "summarize_interview", fake_sum)
    resp = client.post(
        "/api/interview/summary",
        data={"answers": json.dumps(["junk", {"question": "q", "answer": "a"}])},
    )
    assert resp.status_code == 200
    assert captured["qa"] == [{"question": "q", "answer": "a"}]


def test_long_text_fields_are_truncated(client, monkeypatch):
    captured = {}
    monkeypatch.setattr(
        main.gemini_client, "generate_prompt",
        lambda c: captured.setdefault("ctx", c) or "p",
    )
    client.post("/api/prompt", data={"context": "a" * (main.MAX_TEXT_CHARS + 500)})
    assert len(captured["ctx"]) == main.MAX_TEXT_CHARS
