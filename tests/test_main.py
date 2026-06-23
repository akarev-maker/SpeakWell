# tests/test_main.py
import io
import pytest
from fastapi.testclient import TestClient

import main


@pytest.fixture
def client():
    return TestClient(main.app)


def test_prompt_endpoint(client):
    resp = client.get("/api/prompt")
    assert resp.status_code == 200
    assert isinstance(resp.json()["prompt"], str)
    assert resp.json()["prompt"]


def test_analyze_success(client, monkeypatch):
    monkeypatch.setattr(main.audio, "transcode_to_wav", lambda b: b"WAV")
    fake = {
        "scores": {"filler_words": 70, "pace_pauses": 80,
                   "clarity_structure": 75, "confidence_tone": 78},
        "transcript": "hello world", "filler_words": [], "feedback": "Nice.",
    }
    monkeypatch.setattr(main.gemini_client, "analyze_speech", lambda b: fake)
    resp = client.post(
        "/api/analyze",
        files={"audio": ("rec.webm", io.BytesIO(b"rawaudio"), "audio/webm")},
    )
    assert resp.status_code == 200
    assert resp.json()["scores"]["pace_pauses"] == 80


def test_analyze_empty_audio_rejected(client):
    resp = client.post(
        "/api/analyze",
        files={"audio": ("rec.webm", io.BytesIO(b""), "audio/webm")},
    )
    assert resp.status_code == 400
    assert "error" in resp.json()


def test_analyze_handles_backend_error(client, monkeypatch):
    monkeypatch.setattr(main.audio, "transcode_to_wav", lambda b: b"WAV")
    def boom(b):
        raise RuntimeError("gemini down")
    monkeypatch.setattr(main.gemini_client, "analyze_speech", boom)
    resp = client.post(
        "/api/analyze",
        files={"audio": ("rec.webm", io.BytesIO(b"rawaudio"), "audio/webm")},
    )
    assert resp.status_code == 500
    assert "gemini down" in resp.json()["error"]
