import json

import pytest
from google.genai import errors

import models

SCHEMA = {"type": "object"}


def api_error(code):
    return errors.APIError(code, {"error": {"code": code, "message": "x", "status": "X"}})


def test_first_model_wins(fake_gemini):
    c = fake_gemini({"a": [json.dumps({"ok": 1})]})
    r = models.generate_json(["a", "b"], ["hi"], SCHEMA, timeout_s=5)
    assert r.data == {"ok": 1} and r.model == "a"
    assert c.models.calls == ["a"]


@pytest.mark.parametrize("code", [429, 503, 404])
def test_falls_back_on_retryable_errors(fake_gemini, code):
    c = fake_gemini({"a": [api_error(code)], "b": [json.dumps({"ok": 2})]})
    r = models.generate_json(["a", "b"], ["hi"], SCHEMA, timeout_s=5)
    assert r.model == "b"
    assert [a.outcome for a in r.attempts][0] in ("over quota", "busy", "not available for this request")
    assert c.models.calls == ["a", "b"]


def test_bad_key_stops_immediately(fake_gemini):
    c = fake_gemini({"a": [api_error(403)], "b": [json.dumps({"ok": 2})]})
    with pytest.raises(models.ModelError, match="API key"):
        models.generate_json(["a", "b"], ["hi"], SCHEMA, timeout_s=5)
    assert c.models.calls == ["a"]


def test_invalid_json_and_failed_validation_fall_back(fake_gemini):
    def validate(d):
        if "good" not in d:
            raise models.ModelError("missing good")

    fake_gemini({"a": ["not json"], "b": [json.dumps({"bad": 1})], "c": [json.dumps({"good": 1})]})
    r = models.generate_json(["a", "b", "c"], ["hi"], SCHEMA, timeout_s=5, validate=validate)
    assert r.model == "c"


def test_all_fail_gives_readable_summary(fake_gemini):
    fake_gemini({"a": [api_error(503)], "b": [api_error(429)]})
    with pytest.raises(models.ModelError) as exc:
        models.generate_json(["a", "b"], ["hi"], SCHEMA, timeout_s=5, task="grading")
    msg = str(exc.value)
    assert "grading" in msg and "a: busy" in msg and "b: over quota" in msg


def test_thinking_level_dropped_when_model_rejects_it(fake_gemini):
    c = fake_gemini({"a": [api_error(400), json.dumps({"ok": 1})]})
    r = models.generate_json(["a"], ["hi"], SCHEMA, timeout_s=5, thinking="medium")
    assert r.data == {"ok": 1}
    assert c.models.calls == ["a", "a"]


def test_parse_json_strips_fence():
    assert models.parse_json('```json\n{"a": 1}\n```') == {"a": 1}
    with pytest.raises(models.ModelError):
        models.parse_json("[1, 2]")
