import json
import time

import pytest

import config
import interviewer
import models
from tests.helpers import make_session


def live_session(kind="coding", elapsed=60.0, phase=None, persona="neutral"):
    s = make_session(kind, persona)
    s.t0 = time.monotonic() - elapsed
    s.state = "live"
    if phase:
        s.phase_index = s.phase_ids().index(phase)
        s.phase_started_s = max(0.0, elapsed - 30)
    return s


def reply(say="Okay, tell me more.", next_phase="intro", gave_hint=False, end=False):
    return {"say": say, "next_phase": next_phase, "gave_hint": gave_hint, "end_interview": end}


# --- validation --------------------------------------------------------------
def test_validator_rejects_non_english_and_unknown_phase():
    s = live_session()
    check = interviewer._validator(s)
    check(reply("Great, so how would you partition the keys?"))
    check(reply("Use a min-heap — it’s O(log n) “per op”…"))  # common punctuation is fine
    with pytest.raises(models.ModelError, match="English"):
        check(reply("好的，请继续。"))
    with pytest.raises(models.ModelError):
        check(reply(next_phase="made_up"))
    with pytest.raises(models.ModelError):
        check(reply(say="   "))


def test_chinese_reply_falls_back_to_next_model(fake_gemini):
    s = live_session(phase="problem")
    c = fake_gemini({
        "gemini-3.8-flash": [json.dumps(reply("你好", "problem"))],
        "gemini-3.5-flash-lite": [json.dumps(reply("What's your first idea?", "problem"))],
    })
    out = interviewer.respond(s)
    assert out["say"] == "What's your first idea?"
    assert c.models.calls == ["gemini-3.8-flash", "gemini-3.5-flash-lite"]


class FakeCaches:
    def __init__(self):
        self.created, self.deleted = [], []

    def create(self, model, config):
        self.created.append(model)
        from types import SimpleNamespace as NS
        return NS(name="cachedContents/abc", usage_metadata=NS(total_token_count=4000))

    def delete(self, name):
        self.deleted.append(name)


def test_brief_cached_once_for_main_model_and_released_at_end(fake_gemini, monkeypatch):
    s = live_session(phase="problem")
    c = fake_gemini({"gemini-3.8-flash": [json.dumps(reply("Go on.", "problem")),
                                          json.dumps(reply("Bye.", "problem", end=True))]})
    c.caches = FakeCaches()
    sent = []
    orig = c.models.generate_content
    monkeypatch.setattr(c.models, "generate_content",
                        lambda model, contents, config=None: sent.append(config) or orig(model, contents, config))
    interviewer.respond(s)
    assert c.caches.created == ["gemini-3.8-flash"]
    assert sent[0].cached_content == "cachedContents/abc" and sent[0].system_instruction is None
    assert s.meter.total > 0  # cache write + storage is counted
    s.phase_index = len(s.phases) - 1
    s.t0 -= 44 * 60
    interviewer.respond(s)  # ends the interview
    assert c.caches.created == ["gemini-3.8-flash"] and c.caches.deleted == ["cachedContents/abc"]


def test_broken_cache_retries_without_it(fake_gemini):
    from google.genai import errors

    s = live_session(phase="problem")
    s.cache_name, s.cache_model = "cachedContents/expired", "gemini-3.8-flash"
    expired = errors.APIError(404, {"error": {"code": 404, "message": "x", "status": "X"}})
    fake_gemini({
        "gemini-3.8-flash": [expired, json.dumps(reply("Recovered.", "problem"))],
        "gemini-3.5-flash-lite": [errors.APIError(503, {"error": {"code": 503, "message": "x", "status": "X"}})],
    })
    assert interviewer.respond(s)["say"] == "Recovered."
    assert s.cache_name == "" and s.cache_failed


def test_small_talk_phases_use_fast_model(fake_gemini):
    s = live_session(phase="intro")
    c = fake_gemini({"gemini-3.5-flash-lite": [json.dumps(reply())]})
    interviewer.respond(s)
    assert c.models.calls == ["gemini-3.5-flash-lite"]
    assert "intro" in config.FAST_PHASES


# --- structure enforcement ----------------------------------------------------
def test_phase_moves_forward_one_step_and_reveals_problem():
    s = live_session(phase="intro")
    out = interviewer.apply_reply(s, reply(next_phase="candidate_questions"), "")
    assert s.phase["id"] == "problem"  # can't skip straight to the end
    assert out["reveal"]["type"] == "problem"


def test_final_phase_not_entered_too_early():
    s = live_session(kind="system_design", phase="deep_dive", elapsed=12 * 60)
    interviewer.apply_reply(s, reply(next_phase="candidate_questions"), "")
    assert s.phase["id"] == "deep_dive"
    assert "too early for the candidate's questions" in interviewer.state_text(s, 5, False, "")
    s.t0 -= 20 * 60  # now 32 of 45 minutes in
    interviewer.apply_reply(s, reply(next_phase="candidate_questions"), "")
    assert s.phase["id"] == "candidate_questions"


def test_never_goes_back_to_an_earlier_phase():
    s = live_session(kind="system_design", phase="candidate_questions", elapsed=41 * 60)
    interviewer.apply_reply(s, reply(next_phase="deep_dive"), "")
    assert s.phase["id"] == "candidate_questions"


def test_end_only_honored_at_the_end():
    s = live_session(phase="problem", elapsed=10 * 60)
    assert interviewer.apply_reply(s, reply(next_phase="problem", end=True), "")["ended"] is False
    s2 = live_session(phase="candidate_questions", elapsed=42 * 60)
    out = interviewer.apply_reply(s2, reply(next_phase="candidate_questions", end=True), "")
    assert out["ended"] is True and s2.end_reason == "interviewer wrapped up"


def test_hard_stop_after_grace():
    s = live_session(phase="problem", elapsed=45 * 60 + interviewer.HARD_STOP_GRACE_S + 1)
    assert interviewer.apply_reply(s, reply(next_phase="problem"), "")["ended"] is True


def test_hints_counted_only_in_coding_problem_phases():
    s = live_session(phase="problem")
    for _ in range(5):
        interviewer.apply_reply(s, reply(next_phase="problem", gave_hint=True), "")
    assert s.hints_used == 3  # the ladder has 3
    s2 = live_session(phase="intro")
    interviewer.apply_reply(s2, reply(next_phase="intro", gave_hint=True), "")
    assert s2.hints_used == 0


def test_reply_is_cleaned_for_speech():
    s = live_session()
    out = interviewer.apply_reply(s, reply(say="**Great.** Use `heapq`.  " + "word " * 300), "")
    assert "*" not in out["say"] and "`" not in out["say"]
    assert len(out["say"].split()) <= interviewer.MAX_SAY_WORDS + 1
    assert s.timeline[-1] == {"t": pytest.approx(60, abs=1), "who": "interviewer", "text": out["say"]}


# --- the director's state ----------------------------------------------------
def test_final_phase_forbids_new_questions():
    s = live_session(kind="system_design", phase="candidate_questions", elapsed=41 * 60)
    text = interviewer.state_text(s, 10, False, "")
    assert "Do NOT ask new interview questions" in text


def test_overrun_and_wrapup_directives():
    s = live_session(kind="system_design", phase="requirements", elapsed=22 * 60)
    s.phase_started_s = 4 * 60
    assert "move on to 'high_level' now" in interviewer.state_text(s, 5, False, "")
    s2 = live_session(kind="system_design", phase="deep_dive", elapsed=41 * 60)
    assert "move to 'candidate_questions'" in interviewer.state_text(s2, 5, False, "")


def test_time_up_and_cut_off_directives():
    s = live_session(phase="problem", elapsed=20 * 60)
    assert "Time is up" in interviewer.state_text(s, 0, False, "time_up")
    assert "Let me stop you there" in interviewer.state_text(s, 300, True, "")
    assert "long" in interviewer.state_text(s, 200, False, "")


def test_state_includes_code_and_next_hint():
    s = live_session(phase="problem")
    s.latest_work = "def f(x):\n    return x"
    text = interviewer.state_text(s, 5, False, "")
    assert "return x" in text and "NEXT HINT (only if needed): h1" in text


def test_brief_hides_rubric_and_pins_english():
    s = live_session(kind="system_design")
    s.plan["rubric_notes"] = [{"category": "SECRET_RUBRIC", "strong_signals": "", "weak_signals": ""}]
    text = interviewer.brief(s)
    assert "SECRET_RUBRIC" not in text and "English only" in text and "hidden fact ONLY when" in text


def test_conversation_is_append_only_and_marks_typed():
    s = live_session()
    s.log("interviewer", "Hi", t=0)
    s.log("candidate", "typed hello", t=5)
    s.timeline[-1]["typed"] = True
    first = interviewer.conversation_text(s)
    s.log("interviewer", "Next", t=9)
    assert interviewer.conversation_text(s).startswith(first)  # stable prefix for Google's cache
    assert "Candidate (typed): typed hello" in first


def test_answer_limit_by_phase_and_persona():
    assert interviewer.answer_limit(live_session(phase="problem")) == 300
    assert interviewer.answer_limit(live_session(phase="intro", persona="tough")) == round(150 * 0.75)


def test_opening_comes_from_plan():
    s = live_session()
    assert interviewer.opening(s) == "Hi t"
