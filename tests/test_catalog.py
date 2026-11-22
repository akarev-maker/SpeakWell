import random
from collections import Counter

import catalog


def test_every_track_has_coding_and_design_seeds():
    for track in catalog.TRACKS:
        assert len(catalog.CODING_SEEDS[track]) >= 8
        assert len(catalog.DESIGN_SEEDS[track]) >= 6


def test_seed_ids_unique_within_pools():
    pools = [*catalog.CODING_SEEDS.values(), *catalog.DESIGN_SEEDS.values(),
             catalog.BEHAVIORAL_COMPETENCIES, catalog.RESUME_ANGLES]
    for pool in pools:
        ids = [s.id for s in pool]
        assert len(ids) == len(set(ids))


def test_phases_match_kind_lengths():
    for kind, phases in catalog.PHASES.items():
        assert sum(m for _, _, m in phases) == catalog.KINDS[kind]["minutes"]
        assert phases[0][0] == "intro" and phases[-1][0] == "candidate_questions"


def test_recent_seeds_are_strongly_avoided():
    rng = random.Random(0)
    recent = [s.id for s in catalog.CODING_SEEDS["swe"][:10]]
    picks = Counter(catalog.pick_seeds("coding", "swe", recent, rng)[0].id for _ in range(2000))
    fresh = sum(n for sid, n in picks.items() if sid not in recent)
    assert fresh / 2000 > 0.8


def test_behavioral_picks_four_distinct():
    seeds = catalog.pick_seeds("behavioral", "swe", [], random.Random(1))
    assert len(seeds) == 4 and len({s.id for s in seeds}) == 4


def test_persona_choice_and_random():
    assert catalog.pick_persona("tough").id == "tough"
    assert catalog.pick_persona("random", random.Random(2)).id in catalog.PERSONAS


def test_options_shape():
    o = catalog.options()
    assert {k["id"] for k in o["kinds"]} == set(catalog.KINDS)
    assert o["personas"][-1]["id"] == "random"
    assert set(o["rubrics"]) == set(catalog.KINDS)
