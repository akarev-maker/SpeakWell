import json
import pytest
import config
import gemini_client

VALID = {
    "scores": {
        "filler_words": 72, "pace_pauses": 85,
        "clarity_structure": 78, "confidence_tone": 80,
    },
    "transcript": "So um, I think...",
    "filler_words": ["um"],
    "feedback": "Good clarity. You said 'um' a few times.",
    "tips": ["Pause instead of saying 'um'.", "Slow down the opening sentence."],
}


VALID_INTERVIEW = {
    **VALID,
    "answer_critique": "Relevant but lacked a concrete example.",
    "model_answer": "In my last role, I led a migration that cut costs 20%.",
}


def test_parse_interview_requires_extra_fields():
    # Without require_interview, the normal payload (no extra fields) is fine.
    gemini_client.parse_response(json.dumps(VALID))
    # With require_interview, missing answer_critique/model_answer raises.
    with pytest.raises(RuntimeError, match="answer_critique"):
        gemini_client.parse_response(json.dumps(VALID), require_interview=True)


def test_parse_interview_valid():
    out = gemini_client.parse_response(
        json.dumps(VALID_INTERVIEW), require_interview=True
    )
    assert out["answer_critique"].startswith("Relevant")
    assert out["model_answer"].startswith("In my last role")


def test_generate_interview_question_embeds_context(monkeypatch):
    class FakeResp:
        text = '"Tell me about a time you handled conflict."'

    class FakeModels:
        def generate_content(self, **kwargs):
            assert "Junior developer" in kwargs["contents"][0]
            return FakeResp()

    class FakeClient:
        models = FakeModels()

    monkeypatch.setattr(gemini_client, "_build_client", lambda: FakeClient())
    out = gemini_client.generate_interview_question("Junior developer interviews")
    assert out == "Tell me about a time you handled conflict."


def test_analyze_speech_interview_returns_extra_fields(monkeypatch):
    captured = {}

    class FakeResp:
        text = json.dumps(VALID_INTERVIEW)

    class FakeModels:
        def generate_content(self, **kwargs):
            captured["contents"] = kwargs["contents"]
            return FakeResp()

    class FakeClient:
        models = FakeModels()

    monkeypatch.setattr(gemini_client, "_build_client", lambda: FakeClient())
    out = gemini_client.analyze_speech(
        b"RIFFWAVE", question="Why do you want this job?"
    )
    assert out["model_answer"].startswith("In my last role")
    # The question is embedded in the instruction sent to the model.
    assert "Why do you want this job?" in captured["contents"][-1]


def test_parse_includes_tips():
    out = gemini_client.parse_response(json.dumps(VALID))
    assert out["tips"] == [
        "Pause instead of saying 'um'.",
        "Slow down the opening sentence.",
    ]


def test_parse_missing_tips_raises():
    bad = json.loads(json.dumps(VALID))
    del bad["tips"]
    with pytest.raises(RuntimeError, match="tips"):
        gemini_client.parse_response(json.dumps(bad))


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
            assert kwargs["model"] == config.GEMINI_MODEL
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


def test_generate_prompt_embeds_context_and_strips_quotes(monkeypatch):
    class FakeResp:
        text = '"Tell me about a deal you closed."'

    class FakeModels:
        def generate_content(self, **kwargs):
            assert "Sales pitching" in kwargs["contents"][0]
            return FakeResp()

    class FakeClient:
        models = FakeModels()

    monkeypatch.setattr(gemini_client, "_build_client", lambda: FakeClient())
    out = gemini_client.generate_prompt("Sales pitching")
    assert out == "Tell me about a deal you closed."


def test_generate_prompt_empty_raises(monkeypatch):
    class FakeResp:
        text = "   "

    class FakeModels:
        def generate_content(self, **kwargs):
            return FakeResp()

    class FakeClient:
        models = FakeModels()

    monkeypatch.setattr(gemini_client, "_build_client", lambda: FakeClient())
    with pytest.raises(RuntimeError, match="empty"):
        gemini_client.generate_prompt("Sales")


def test_build_instruction_with_context_includes_it():
    text = gemini_client.build_instruction(
        None, context="Junior developer preparing for interviews"
    )
    assert "Junior developer preparing for interviews" in text
    assert "tailor" in text.lower()


def test_build_instruction_without_context_is_base():
    assert gemini_client.build_instruction(None, context=None) == gemini_client.INSTRUCTION
    assert gemini_client.build_instruction(None, context="") == gemini_client.INSTRUCTION


def test_analyze_speech_passes_context_into_contents(monkeypatch):
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
    gemini_client.analyze_speech(
        b"RIFFWAVE", context="College student seeking internships"
    )
    assert "College student seeking internships" in captured["contents"][-1]
