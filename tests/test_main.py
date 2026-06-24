# tests/test_main.py
import io
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


def test_analyze_success(client, monkeypatch):
    monkeypatch.setattr(main.audio, "transcode_to_wav", lambda b: b"WAV")
    fake = {
        "scores": {"filler_words": 70, "pace_pauses": 80,
                   "clarity_structure": 75, "confidence_tone": 78},
        "transcript": "hello world", "filler_words": [], "feedback": "Nice.",
    }
    monkeypatch.setattr(
        main.gemini_client, "analyze_speech", lambda b, prompt=None, context=None: fake
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

    def fake_analyze(b, prompt=None, context=None):
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

    def fake_analyze(b, prompt=None, context=None):
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

    def fake_analyze(b, prompt=None, context=None):
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
    def boom(b, prompt=None, context=None):
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
    def boom(b, prompt=None, context=None):
        raise ValueError("api boom")
    monkeypatch.setattr(main.gemini_client, "analyze_speech", boom)
    resp = client.post(
        "/api/analyze",
        files={"audio": ("rec.webm", io.BytesIO(b"x" * 1500), "audio/webm")},
    )
    assert resp.status_code == 500
    assert "api boom" in resp.json()["error"]
