# tests/test_main.py
import io
import json
import pytest
from fastapi.testclient import TestClient

import main


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


def test_analyze_handles_non_runtime_error(client, monkeypatch):
    monkeypatch.setattr(main.audio, "transcode_to_wav", lambda b: b"WAV")
    def boom(b, prompt=None, context=None, question=None):
        raise ValueError("api boom")
    monkeypatch.setattr(main.gemini_client, "analyze_speech", boom)
    resp = client.post(
        "/api/analyze",
        files={"audio": ("rec.webm", io.BytesIO(b"x" * 1500), "audio/webm")},
    )
    assert resp.status_code == 500
    assert "api boom" in resp.json()["error"]
