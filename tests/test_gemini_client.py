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
            assert kwargs["model"] == "gemini-2.5-flash"
            return FakeResp()

    class FakeClient:
        models = FakeModels()

    monkeypatch.setattr(gemini_client, "_build_client", lambda: FakeClient())
    out = gemini_client.analyze_speech(b"RIFFWAVE")
    assert out["scores"]["filler_words"] == 72


def test_build_instruction_without_prompt_is_base():
    assert gemini_client.build_instruction(None) == gemini_client.INSTRUCTION
    assert gemini_client.build_instruction("") == gemini_client.INSTRUCTION


def test_build_instruction_with_prompt_includes_it():
    text = gemini_client.build_instruction("Describe your ideal weekend.")
    assert "Describe your ideal weekend." in text
    # base instruction is preserved
    assert "You are SpeakWell" in text
    # the model is told to consider how well the prompt was addressed
    assert "address" in text.lower()


def test_analyze_speech_passes_prompt_into_contents(monkeypatch):
    captured = {}

    class FakeResp:
        text = json.dumps(VALID)

    class FakeModels:
        def generate_content(self, **kwargs):
            captured["contents"] = kwargs["contents"]
            return FakeResp()

    class FakeClient:
        models = FakeModels()

    monkeypatch.setattr(gemini_client, "_build_client", lambda: FakeClient())
    gemini_client.analyze_speech(b"RIFFWAVE", prompt="Pitch your favorite app.")
    instruction_text = captured["contents"][-1]
    assert "Pitch your favorite app." in instruction_text
