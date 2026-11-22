"""One interview's in-memory state, from plan to report.

Sessions live only in this process's memory. Nothing here is written to disk
except the final report (via storage.py). Old sessions expire automatically.
"""
import secrets
import threading
import time

import catalog
import storage
from pricing import CostMeter

SESSION_TTL_S = 3 * 60 * 60
MAX_SESSIONS = 6

_lock = threading.Lock()
_sessions: dict[str, "InterviewSession"] = {}


class InterviewSession:
    def __init__(self, planned: dict, meter: CostMeter):
        self.id = secrets.token_urlsafe(12)
        self.created = time.time()
        self.kind: str = planned["kind"]
        self.track: str = planned["track"]
        self.level: str = planned["level"]
        self.persona: catalog.Persona = planned["persona"]
        self.interviewer_name: str = planned["interviewer_name"]
        self.seeds: list[str] = planned["seeds"]
        self.seed_titles: list[str] = planned["seed_titles"]
        self.minutes: int = planned["minutes"]
        self.planner_model: str = planned["planner_model"]
        self.plan: dict = planned["plan"]
        self.meter = meter
        self._recorded_usd = 0.0

        # Live state
        self.state = "ready"  # ready -> live -> ended -> grading -> graded | error
        self.t0: float | None = None  # monotonic time the interview went live
        self.ended_at: float | None = None
        self.timeline: list[dict] = []  # {"t", "who": interviewer|candidate|event, "text"}
        self.phase_index = 0
        self.phase_started_s = 0.0
        self.hints_used = 0
        self.ended_early = False
        self.end_reason = ""
        self.latest_work = ""
        self.turns = 0
        self.words: list[dict] = []  # your spoken words, times on the interview clock
        self.audio: list[bytes] = []  # your answers as MP3, in memory only, for voice analysis
        self.busy = False  # a turn is being processed
        self.cache_name = ""  # Google-side cache of the interviewer brief
        self.cache_model = ""
        self.cache_failed = False

        # Grading state
        self.grade_stage = ""
        self.report: dict | None = None
        self.error = ""

    # --- time --------------------------------------------------------------
    def now(self) -> float:
        return 0.0 if self.t0 is None else time.monotonic() - self.t0

    @property
    def elapsed_s(self) -> float:
        if self.t0 is None:
            return 0.0
        end = self.ended_at if self.ended_at is not None else time.monotonic()
        return end - self.t0

    # --- phases ------------------------------------------------------------
    @property
    def phases(self) -> list[dict]:
        return self.plan["phases"]

    @property
    def phase(self) -> dict:
        return self.phases[min(self.phase_index, len(self.phases) - 1)]

    def phase_ids(self) -> list[str]:
        return [p["id"] for p in self.phases]

    def set_phase(self, phase_id: str) -> bool:
        ids = self.phase_ids()
        if phase_id not in ids:
            return False
        idx = ids.index(phase_id)
        if idx <= self.phase_index:
            return idx == self.phase_index
        self.phase_index = idx
        self.phase_started_s = self.now()
        self.log("event", f"Phase: {self.phase['name']}")
        return True

    def log(self, who: str, text: str, t: float | None = None) -> None:
        text = (text or "").strip()
        if text:
            self.timeline.append({"t": round(self.now() if t is None else t, 1), "who": who, "text": text})

    # --- what the candidate may see ------------------------------------------
    @property
    def title(self) -> str:
        return f"{catalog.KINDS[self.kind]['label']} · {catalog.TRACKS[self.track]} · {catalog.LEVELS[self.level]}"

    def public_info(self) -> dict:
        return {
            "id": self.id, "kind": self.kind, "title": self.title, "minutes": self.minutes,
            "interviewer_name": self.interviewer_name, "persona": self.persona.label,
            "persona_id": self.persona.id,
            "track": catalog.TRACKS[self.track], "level": catalog.LEVELS[self.level],
            "kind_label": catalog.KINDS[self.kind]["label"],
        }

    def reveal_for_phase(self, phase_id: str) -> dict | None:
        """Material the candidate sees on screen when a phase starts."""
        if self.kind == "coding" and phase_id == "problem":
            p = self.plan["problem"]
            return {"type": "problem", "title": p["title"], "statement": p["statement"],
                    "signature": p["function_signature"], "examples": p["examples"],
                    "constraints": p["constraints"]}
        if self.kind == "system_design" and phase_id == "requirements":
            return {"type": "prompt", "text": self.plan["design"]["prompt"]}
        return None

    def public_reference(self) -> dict:
        """Shown after grading, for learning: what the interviewer was looking for."""
        if self.kind == "coding":
            p = self.plan["problem"]
            return {"title": p["title"], "statement": p["statement"],
                    "reference_solution": p["reference_solution"],
                    "time_complexity": p["time_complexity"], "space_complexity": p["space_complexity"],
                    "hints": p["hints"], "follow_up_variants": p["follow_up_variants"]}
        if self.kind == "system_design":
            d = self.plan["design"]
            return {"prompt": d["prompt"], "hidden_facts": d["hidden_facts"],
                    "must_cover": d["must_cover"], "deep_dive_topics": d["deep_dive_topics"],
                    "pitfalls": d["pitfalls"]}
        if self.kind == "behavioral":
            return {"questions": [{"competency": q["competency"], "question": q["question"],
                                   "strong_answer_signals": q["strong_answer_signals"]}
                                  for q in self.plan["questions"]]}
        return {"projects": [{"name": p["name"], "opening_question": p["opening_question"],
                              "drill_questions": p["drill_questions"]} for p in self.plan["projects"]]}

    # --- cost --------------------------------------------------------------
    def flush_spend(self, what: str) -> None:
        """Log spend accrued since the last flush, so the monthly meter is current."""
        delta = self.meter.total - self._recorded_usd
        if delta > 0:
            storage.record_spend(delta, what)
            self._recorded_usd = self.meter.total


def add(s: InterviewSession) -> None:
    with _lock:
        _expire()
        if len(_sessions) >= MAX_SESSIONS:
            oldest = min(_sessions.values(), key=lambda x: x.created)
            _sessions.pop(oldest.id, None)
        _sessions[s.id] = s


def get(session_id: str) -> InterviewSession | None:
    with _lock:
        _expire()
        return _sessions.get(session_id)


def _expire() -> None:
    cutoff = time.time() - SESSION_TTL_S
    for sid in [k for k, v in _sessions.items() if v.created < cutoff]:
        _sessions.pop(sid, None)
