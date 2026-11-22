import catalog
from pricing import CostMeter
from session import InterviewSession


def make_plan(kind="coding"):
    phases = [{"id": p, "goal": "g", "talking_points": ["t"], "follow_ups": ["f"], "move_on_when": "m",
               "name": label, "minutes": m} for p, label, m in catalog.PHASES[kind]]
    plan = {"opening": "Hi", "phases": phases, "rubric_notes": []}
    plan["problem"] = {"title": "T", "statement": "S", "function_signature": "def f():",
                       "examples": [{"input": "1", "output": "1"}] * 2, "constraints": ["c"],
                       "edge_cases": [], "reference_solution": "pass", "time_complexity": "O(1)",
                       "space_complexity": "O(1)", "hints": ["h1", "h2", "h3"], "follow_up_variants": []}
    plan["design"] = {"prompt": "Design X", "hidden_facts": [{"topic": "users", "answer": "1M"}] * 4,
                      "must_cover": [], "deep_dive_topics": [], "pitfalls": []}
    plan["questions"] = [{"competency": "c", "question": "q", "follow_ups": [], "strong_answer_signals": "s"}] * 3
    plan["projects"] = [{"name": "p", "why_chosen": "w", "opening_question": "o", "drill_questions": [],
                         "claims_to_verify": []}]
    return plan


def make_session(kind="coding", persona="neutral"):
    planned = {"kind": kind, "track": "swe", "level": "intern", "persona": catalog.PERSONAS[persona],
               "interviewer_name": "Maya", "seeds": ["s1"], "seed_titles": ["S1"],
               "minutes": catalog.KINDS[kind]["minutes"], "planner_model": "fake", "plan": make_plan(kind)}
    return InterviewSession(planned, CostMeter())
