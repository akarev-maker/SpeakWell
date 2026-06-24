import storage


def test_save_and_recent_newest_first(tmp_path, monkeypatch):
    monkeypatch.setattr(storage, "DB_PATH", str(tmp_path / "t.db"))
    storage.save_session("practice", "q1", {
        "filler_words": 50, "pace_pauses": 60,
        "clarity_structure": 70, "confidence_tone": 80,
    })
    storage.save_session("interview", "q2", {
        "filler_words": 55, "pace_pauses": 65,
        "clarity_structure": 75, "confidence_tone": 85,
    })
    rows = storage.recent_sessions(10)
    assert len(rows) == 2
    assert rows[0]["label"] == "q2"  # newest first
    assert rows[0]["mode"] == "interview"
    assert rows[0]["filler_words"] == 55
    assert rows[1]["mode"] == "practice"
    assert rows[1]["created_at"]  # timestamp recorded


def test_recent_respects_limit(tmp_path, monkeypatch):
    monkeypatch.setattr(storage, "DB_PATH", str(tmp_path / "t.db"))
    for i in range(5):
        storage.save_session("practice", f"q{i}", {
            "filler_words": i, "pace_pauses": i,
            "clarity_structure": i, "confidence_tone": i,
        })
    assert len(storage.recent_sessions(3)) == 3


def test_recent_empty(tmp_path, monkeypatch):
    monkeypatch.setattr(storage, "DB_PATH", str(tmp_path / "t.db"))
    assert storage.recent_sessions() == []
