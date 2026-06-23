import json
import pytest
import gemini_client

VALID = {
    "scores": {
        "filler_words": 72, "pace_pauses": 85,
        "clarity_structure": 78, "confidence_tone": 80,
    },
    "transcript": "So um, I think...",
    "filler_words": ["um"],
    "feedback": "Good clarity. You said 'um' a few times.",
}


def test_parse_valid_response():
    out = gemini_client.parse_response(json.dumps(VALID))
    assert out["scores"]["pace_pauses"] == 85
    assert out["filler_words"] == ["um"]
    assert out["transcript"].startswith("So um")


def test_parse_strips_code_fence():
    fenced = "```json\n" + json.dumps(VALID) + "\n```"
    out = gemini_client.parse_response(fenced)
    assert out["feedback"].startswith("Good clarity")


def test_parse_invalid_json_raises():
    with pytest.raises(RuntimeError, match="parse"):
        gemini_client.parse_response("not json at all")


def test_parse_missing_score_key_raises():
    bad = json.loads(json.dumps(VALID))
    del bad["scores"]["pace_pauses"]
    with pytest.raises(RuntimeError, match="scores"):
        gemini_client.parse_response(json.dumps(bad))


def test_parse_empty_text_raises():
    with pytest.raises(RuntimeError, match="empty"):
        gemini_client.parse_response("")


def test_parse_none_text_raises():
    with pytest.raises(RuntimeError, match="empty"):
        gemini_client.parse_response(None)


def test_analyze_speech_uses_client(monkeypatch):
    class FakeResp:
        text = json.dumps(VALID)

    class FakeModels:
        def generate_content(self, **kwargs):
            assert kwargs["model"] == "gemini-2.0-flash"
            return FakeResp()

    class FakeClient:
        models = FakeModels()

    monkeypatch.setattr(gemini_client, "_build_client", lambda: FakeClient())
    out = gemini_client.analyze_speech(b"RIFFWAVE")
    assert out["scores"]["filler_words"] == 72
