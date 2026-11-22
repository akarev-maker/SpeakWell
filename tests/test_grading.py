import grading


def words_from(text, start=0.0, step=0.4):
    out, t = [], start
    for w in text.split():
        out.append({"text": w, "start": round(t, 2), "end": round(t + 0.3, 2)})
        t += step
    return out


def test_hard_and_comma_fillers_counted_but_not_normal_like():
    words = words_from("Um, so, like, I like Python. You know, it's, uh, basically fine and I know you know it.")
    stats = grading.filler_stats(words)
    assert stats["counts"]["um"] == 1
    assert stats["counts"]["uh"] == 1
    assert stats["counts"]["like"] == 1  # ", like," only; "I like Python" is not a filler
    assert stats["counts"]["basically"] == 1
    assert stats["counts"]["you know"] == 1  # "You know," counts; "you know it." does not


def test_segments_split_on_pause_and_sentence():
    words = words_from("This is the first full sentence here.") + words_from("Then more", start=10)
    segs = grading.segments(words)
    assert len(segs) == 2
    assert segs[1]["start"] == 10


def test_pace_and_scores():
    words = words_from(" ".join(["word"] * 100), step=0.4)  # 150 wpm
    wpm = grading.pace_wpm(words)
    assert 140 <= wpm <= 160
    assert grading.pace_score(140) == 100
    assert grading.pace_score(200) < 50
    assert grading.pace_score(None) is None
    score, rate = grading.filler_score({"hits": [{"hard": True}] * 5}, 1.0)
    assert (score, rate) == (60, 5.0)
    assert grading.filler_score({"hits": []}, 0.1) == (None, None)


def test_hallucinated_quotes_are_dropped():
    said = "So I think we need a load balancer in front of the API servers"
    moments = [
        {"quote": "we need a load balancer in front", "time": "01:00"},
        {"quote": "I would use Kafka for everything", "time": "02:00"},
        {"quote": "", "time": "03:00"},
    ]
    kept = grading.keep_real_quotes(moments, said)
    assert [m["time"] for m in kept] == ["01:00"]


def test_timeline_merges_spoken_and_typed_lines():
    timeline = [{"t": 0.0, "who": "interviewer", "text": "Hi"},
                {"t": 5.0, "who": "candidate", "text": "spoken, comes from words instead"},
                {"t": 20.0, "who": "candidate", "text": "a typed answer", "typed": True},
                {"t": 30.0, "who": "event", "text": "Phase: Questions"}]
    segs = [{"start": 5.0, "end": 6.0, "words": ["Hello", "there."]}]
    text = grading.build_timeline_text(timeline, segs)
    assert text.splitlines() == ["[00:00] Interviewer: Hi", "[00:05] Candidate: Hello there.",
                                 "[00:20] Candidate (typed): a typed answer", "[00:30] (Phase: Questions)"]


def test_grade_uses_session_words_and_drops_fake_quotes(fake_gemini, monkeypatch):
    import json
    import time

    from tests.helpers import make_session

    s = make_session("behavioral")
    s.t0 = time.monotonic() - 600
    s.ended_at = time.monotonic()
    s.log("interviewer", "Tell me about a conflict.", t=0)
    s.words = words_from("Um, so we disagreed about the database and I ran a benchmark.", start=10)
    s.log("candidate", " ".join(w["text"] for w in s.words), t=10)
    s.audio = [b"mp3"]
    monkeypatch.setattr(grading, "analyze_delivery", lambda mp3, meter: {
        "engagement": 70, "confidence": 66, "energy": "ok", "tone": "ok", "observations": []})
    graded = {
        "overall_score": 61, "verdict": "v",
        "categories": [{"id": "structure", "score": 60, "reason": "r"}, {"id": "bogus", "score": 1, "reason": "x"}],
        "moments": [{"time": "00:10", "quote": "we disagreed about the database", "issue": "i", "better": "b", "type": "content"},
                    {"time": "00:20", "quote": "I invented Kubernetes", "issue": "i", "better": "b", "type": "content"}],
        "strengths": [], "improvements": [], "questions_for_them": {"score": 10, "feedback": "f"},
        "engagement_feedback": "e", "work_review": "",
    }
    fake_gemini({"gemini-4-argon": [json.dumps(graded)]})
    rep = grading.grade(s, "")
    assert [c["id"] for c in rep["categories"]] == ["structure"]
    assert [m["time"] for m in rep["moments"]] == ["00:10"]
    assert rep["delivery"]["filler_counts"] == {"um": 1}
    assert rep["delivery"]["engagement_score"] == 70


def test_scores_for_history_flattens():
    report = {"categories": [{"id": "approach", "score": 70}],
              "delivery": {"filler_score": 80, "pace_score": None, "engagement_score": 65},
              "questions_for_them": {"score": 50}}
    assert grading.scores_for_history(report) == {"approach": 70, "fillers": 80, "engagement": 65, "questions": 50}
