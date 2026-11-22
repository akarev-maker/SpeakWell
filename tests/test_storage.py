from datetime import datetime, timedelta, timezone

import storage


def rec(i, kind="coding", seeds=("a",), created=None, score=70):
    return {"id": f"id{i}", "created_at": created or f"2026-11-{10 + i:02d}T00:00:00+00:00",
            "kind": kind, "track": "swe", "level": "intern", "persona": "warm", "seeds": list(seeds),
            "title": "t", "duration_sec": 100, "ended_early": False, "overall_score": score,
            "scores": {"approach": 150, "pace": "x"}, "report": {"k": 1}, "cost_usd": 0.5}


def test_save_list_get_delete():
    storage.save_interview(rec(1))
    storage.save_interview(rec(2))
    items = storage.list_interviews()
    assert [i["id"] for i in items] == ["id2", "id1"]
    assert items[0]["scores"] == {"approach": 100, "pace": None}  # clamped / invalid -> None
    assert "report" not in items[0]
    assert storage.get_interview("id1")["report"] == {"k": 1}
    assert storage.delete_interview("id1") and storage.get_interview("id1") is None


def test_recent_seeds_newest_first_per_kind():
    storage.save_interview(rec(1, seeds=["old"]))
    storage.save_interview(rec(2, seeds=["new", "old"]))
    storage.save_interview(rec(3, kind="behavioral", seeds=["other"]))
    assert storage.recent_seeds("coding", "swe") == ["new", "old"]


def test_month_spend_counts_only_this_month():
    now = datetime.now(timezone.utc)
    storage.record_spend(1.25, "plan")
    storage.record_spend(0, "nothing")
    conn = storage._connect()
    conn.execute("INSERT INTO spend (created_at, usd, what) VALUES (?, ?, ?)",
                 ((now - timedelta(days=40)).isoformat(), 9.0, "old"))
    conn.commit()
    conn.close()
    assert round(storage.month_spend_usd(now), 2) == 1.25


def test_resume_roundtrip():
    assert storage.get_resume() is None
    storage.save_resume("v1")
    storage.save_resume("v2")
    assert storage.get_resume()["text"] == "v2"
    storage.clear_resume()
    assert storage.get_resume() is None
