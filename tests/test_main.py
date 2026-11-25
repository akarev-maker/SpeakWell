import time

import pytest
from fastapi.testclient import TestClient

import grading
import interviewer
import main
import models
import planner
import session as sessions
import storage
from tests.helpers import make_plan, make_session


@pytest.fixture
def client():
    sessions._sessions.clear()
    return TestClient(main.app)


def fake_planned(kind="behavioral"):
    s = make_session(kind)
    return {"kind": kind, "track": "swe", "level": "intern", "persona": s.persona, "interviewer_name": "Maya",
            "seeds": ["x"], "seed_titles": ["X"], "minutes": s.minutes, "planner_model": "fake", "plan": make_plan(kind)}


def test_meta(client):
    r = client.get("/api/meta")
    assert r.status_code == 200
    body = r.json()
    assert body["budget"]["limit_usd"] > 0 and body["has_resume"] is False


def test_cross_site_post_blocked(client):
    r = client.post("/api/interviews", json={}, headers={"Origin": "https://evil.example"})
    assert r.status_code == 403


def test_start_interview_returns_public_info_only(client, monkeypatch):
    monkeypatch.setattr(planner, "build_plan", lambda *a, **k: fake_planned())
    r = client.post("/api/interviews", json={"kind": "behavioral", "track": "swe", "level": "intern"})
    assert r.status_code == 200
    body = r.json()
    assert body["interviewer_name"] == "Maya" and "plan" not in body and "questions" not in str(body)


def test_start_interview_model_failure_is_readable(client, monkeypatch):
    def boom(*a, **k):
        raise models.ModelError("Every model failed for the interview plan (a: busy).")
    monkeypatch.setattr(planner, "build_plan", boom)
    r = client.post("/api/interviews", json={"kind": "coding", "track": "swe", "level": "intern"})
    assert r.status_code == 503 and "busy" in r.json()["error"]


def test_budget_guard_blocks_new_interviews(client, monkeypatch):
    storage.record_spend(main.config.MONTHLY_BUDGET_USD + 1, "test")
    called = []
    monkeypatch.setattr(planner, "build_plan", lambda *a, **k: called.append(1))
    r = client.post("/api/interviews", json={"kind": "coding", "track": "swe", "level": "intern"})
    assert r.status_code == 402 and not called


def test_resume_crud(client):
    assert client.put("/api/resume", json={"text": "  "}).status_code == 400
    assert client.put("/api/resume", json={"text": "x" * (main.MAX_RESUME_CHARS + 1)}).status_code == 413
    assert client.put("/api/resume", json={"text": "My resume"}).json()["text"] == "My resume"
    assert client.get("/api/meta").json()["has_resume"] is True
    client.delete("/api/resume")
    assert client.get("/api/resume").json()["text"] == ""


def test_grade_flow_saves_scores_only(client, monkeypatch):
    s = make_session("behavioral")
    s.t0 = time.monotonic() - 120
    s.log("interviewer", "Tell me about a conflict.")
    s.log("candidate", "We disagreed about the database.")
    s.state = "ended"
    sessions.add(s)
    seen = {}

    def fake_grade(sess, final_work, progress):
        seen["work"] = final_work
        progress("grading")
        return {"overall_score": 72, "categories": [{"id": "structure", "label": "S", "score": 70, "reason": "r"}],
                "delivery": {"filler_score": 80}, "questions_for_them": {"score": 60}}

    monkeypatch.setattr(grading, "grade", fake_grade)
    r = client.post(f"/api/interviews/{s.id}/grade", data={"final_work": "def f(): pass"})
    assert r.status_code == 200
    for _ in range(50):
        st = client.get(f"/api/interviews/{s.id}/grade").json()
        if st.get("report"):
            break
        time.sleep(0.05)
    assert st["report"]["overall_score"] == 72
    assert seen["work"] == "def f(): pass"
    saved = client.get("/api/history").json()["interviews"][0]
    assert saved["scores"] == {"structure": 70, "fillers": 80, "questions": 60}
    # A second grade request is refused while/after grading.
    assert client.post(f"/api/interviews/{s.id}/grade").status_code == 409


def test_grade_refused_before_interview_started(client):
    s = make_session("coding")
    s.state = "ended"
    sessions.add(s)
    r = client.post(f"/api/interviews/{s.id}/grade")
    assert r.status_code == 400


def test_grade_unknown_interview(client):
    assert client.post("/api/interviews/nope/grade").status_code == 404


# --- the turn-by-turn interview ----------------------------------------------
import audio  # noqa: E402
import interviewer  # noqa: E402


def ready_session(kind="coding"):
    s = make_session(kind)
    sessions.add(s)
    return s


def test_begin_starts_clock_and_returns_opening(client):
    s = ready_session()
    r = client.post(f"/api/interviews/{s.id}/begin").json()
    assert r["say"] == "Hi. " + interviewer.DEFAULT_FIRST_QUESTION and s.state == "live" and s.t0 is not None
    assert client.post(f"/api/interviews/{s.id}/begin").status_code == 409


def test_spoken_turn_is_transcribed_logged_and_answered(client, monkeypatch):
    s = ready_session()
    client.post(f"/api/interviews/{s.id}/begin")
    s.t0 -= 30  # the interview has been running for 30 s
    monkeypatch.setattr(audio, "to_mp3", lambda raw: b"mp3:" + raw[:3])
    monkeypatch.setattr(grading, "transcribe_turn", lambda mp3, meter: [
        {"text": "Um,", "start": 0.1, "end": 0.3}, {"text": "hello.", "start": 0.4, "end": 0.8}])
    seen = {}

    def fake_respond(sess, answer_s=0.0, auto_stopped=False, event=""):
        seen.update(answer_s=answer_s, auto_stopped=auto_stopped, work=sess.latest_work)
        return {"say": "Tell me more.", "reveal": None, "ended": False}

    monkeypatch.setattr(interviewer, "respond", fake_respond)
    r = client.post(f"/api/interviews/{s.id}/turn",
                    files={"answer": ("a.webm", b"x" * 2000, "audio/webm")},
                    data={"started_at": "0.5", "duration": "12", "auto_stopped": "true", "work": "code"})
    body = r.json()
    assert body["heard"] == "Um, hello." and body["say"] == "Tell me more."
    assert seen == {"answer_s": 12.0, "auto_stopped": True, "work": "code"}
    assert [w["start"] for w in s.words] == [pytest.approx(0.6), pytest.approx(0.9)]  # on the interview clock
    assert s.audio == [b"mp3:xxx"]


def test_silent_turn_costs_no_model_call(client, monkeypatch):
    s = ready_session()
    client.post(f"/api/interviews/{s.id}/begin")
    monkeypatch.setattr(audio, "to_mp3", lambda raw: b"mp3")
    monkeypatch.setattr(grading, "transcribe_turn", lambda mp3, meter: [])
    monkeypatch.setattr(interviewer, "respond", lambda *a, **k: pytest.fail("should not be called"))
    body = client.post(f"/api/interviews/{s.id}/turn", files={"answer": ("a.webm", b"x" * 2000, "audio/webm")}).json()
    assert body["say"] is None and "didn't hear" in body["message"]
    tiny = client.post(f"/api/interviews/{s.id}/turn", files={"answer": ("a.webm", b"x", "audio/webm")}).json()
    assert tiny["say"] is None


def test_typed_turn_and_interviewer_ending(client, monkeypatch):
    s = ready_session("behavioral")
    client.post(f"/api/interviews/{s.id}/begin")
    monkeypatch.setattr(interviewer, "respond",
                        lambda sess, *a, **k: {"say": "Thanks, goodbye.", "reveal": None, "ended": True})
    body = client.post(f"/api/interviews/{s.id}/turn", data={"text": "No more questions."}).json()
    assert body["ended"] is True and s.state == "ended"
    assert s.timeline[-1]["typed"] is True and s.timeline[-1]["text"] == "No more questions."
    assert client.post(f"/api/interviews/{s.id}/turn", data={"text": "hi"}).status_code == 409


def test_model_failure_offers_retry(client, monkeypatch):
    s = ready_session("behavioral")
    client.post(f"/api/interviews/{s.id}/begin")

    def boom(*a, **k):
        raise models.ModelError("Every model failed for the interviewer reply (x: busy).")

    monkeypatch.setattr(interviewer, "respond", boom)
    r = client.post(f"/api/interviews/{s.id}/turn", data={"text": "My answer"})
    assert r.status_code == 503 and "Retry" in r.json()["error"]
    assert s.timeline[-1]["text"] == "My answer" and s.busy is False
    monkeypatch.setattr(interviewer, "respond", lambda sess, *a, **k: {"say": "Go on.", "reveal": None, "ended": False})
    assert client.post(f"/api/interviews/{s.id}/retry").json()["say"] == "Go on."


def test_end_marks_early_and_allows_grading(client, monkeypatch):
    s = ready_session("behavioral")
    client.post(f"/api/interviews/{s.id}/begin")
    s.log("candidate", "an answer")
    body = client.post(f"/api/interviews/{s.id}/end", data={"work": ""}).json()
    assert body["ok"] and s.state == "ended" and s.ended_early
    monkeypatch.setattr(grading, "grade", lambda sess, work, progress: {"overall_score": 50, "categories": []})
    assert client.post(f"/api/interviews/{s.id}/grade").status_code == 200
