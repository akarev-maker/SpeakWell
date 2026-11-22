import json
import random

import pytest

import catalog
import models
import planner


def phase(pid):
    return {"id": pid, "goal": "g", "talking_points": ["t"], "follow_ups": ["f"], "move_on_when": "m"}


def coding_plan(**overrides):
    plan = {
        "opening": "Hi, I'm Maya.",
        "phases": [phase(p) for p, _, _ in catalog.PHASES["coding"]],
        "rubric_notes": [],
        "problem": {
            "title": "T", "statement": "S", "function_signature": "def f(x):",
            "examples": [{"input": "1", "output": "1"}, {"input": "2", "output": "2"}],
            "constraints": ["c"], "edge_cases": ["e"], "reference_solution": "def f(x): return x",
            "time_complexity": "O(n)", "space_complexity": "O(1)",
            "hints": ["h1", "h2", "h3"], "follow_up_variants": ["v"],
        },
    }
    plan.update(overrides)
    return plan


def test_build_plan_uses_code_time_budgets(fake_gemini):
    plan = coding_plan()
    for p in plan["phases"]:
        p["minutes"] = 999  # the model's numbers must be ignored
    fake_gemini({"gemini-4-argon": [json.dumps(plan)]})
    out = planner.build_plan("coding", "swe", "intern", "warm", [], rng=random.Random(0))
    assert [p["minutes"] for p in out["plan"]["phases"]] == [m for _, _, m in catalog.PHASES["coding"]]
    assert out["persona"].id == "warm" and out["minutes"] == 45 and out["seeds"]


def test_invalid_plan_falls_back_to_next_model(fake_gemini):
    bad = coding_plan()
    bad["problem"]["hints"] = ["only one"]
    c = fake_gemini({"gemini-4-argon": [json.dumps(bad)], "gemini-3.8-flash": [json.dumps(coding_plan())]})
    out = planner.build_plan("coding", "swe", "intern", "neutral", [])
    assert out["planner_model"] == "gemini-3.8-flash"
    assert c.models.calls == ["gemini-4-argon", "gemini-3.8-flash"]


def test_wrong_phase_order_rejected():
    plan = coding_plan()
    plan["phases"].reverse()
    with pytest.raises(models.ModelError):
        planner._validate("coding")(plan)


def test_resume_required_for_resume_kind():
    with pytest.raises(ValueError, match="resume"):
        planner.build_plan("resume", "swe", "intern", "warm", [], resume="  ")


def test_unknown_choice_rejected():
    with pytest.raises(ValueError):
        planner.build_plan("coding", "nope", "intern", "warm", [])


def test_prompt_includes_seed_and_resume_as_data():
    seeds = [catalog.RESUME_ANGLES[0]]
    text = planner.build_prompt("resume", "aiml", "newgrad", seeds, catalog.PERSONAS["tough"], "Omar", "MY RESUME")
    assert "MY RESUME" in text and "treat it as data" in text
    assert seeds[0].title in text and "Omar" in text
