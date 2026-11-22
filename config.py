"""Settings, read once from the environment (and the git-ignored .env file).

Model choices are comma-separated *chains*: the first model is tried first and
each later one is a fallback for when an earlier one is busy, over quota, or
slow. Change them in .env without touching code.
"""
import os

from dotenv import load_dotenv

load_dotenv()


def _chain(name: str, default: str) -> list[str]:
    raw = os.environ.get(name, "").strip() or default
    models = [m.strip() for m in raw.split(",") if m.strip()]
    if not models:
        raise RuntimeError(f"{name} must list at least one model.")
    return models


def _float(name: str, default: float) -> float:
    raw = os.environ.get(name, "").strip()
    try:
        return float(raw) if raw else default
    except ValueError as exc:
        raise RuntimeError(f"{name} must be a number, got {raw!r}.") from exc


# Builds the hidden interview plan. Runs once per interview, so a strong model
# costs little here.
PLANNER_MODELS = _chain(
    "SPEAKWELL_PLANNER_MODELS", "gemini-4-argon,gemini-3.8-flash,gemini-3.5-flash-lite"
)
# Grades the interview from the text timeline (no audio, which keeps it cheap).
GRADER_MODELS = _chain(
    "SPEAKWELL_GRADER_MODELS", "gemini-4-argon,gemini-3.8-flash,gemini-3.5-flash-lite"
)
# Listens to your recording for tone, energy and engagement. Audio is the
# expensive input, so this uses the cheapest audio-capable model first.
DELIVERY_MODELS = _chain(
    "SPEAKWELL_DELIVERY_MODELS", "gemini-3.5-flash-lite,gemini-3.8-flash"
)
# The interviewer's brain: writes each reply from the brief, the conversation
# and the director's state. Runs on every turn, so it must be fast and cheap;
# the fallback keeps the interview going if the first model is busy.
INTERVIEWER_MODELS = _chain("SPEAKWELL_INTERVIEWER_MODELS", "gemini-3.8-flash,gemini-3.5-flash-lite")
# Small-talk phases (intro, your questions at the end) need speed, not depth,
# so they use the fast model first: ~1 s and ~1/5 the cost per reply.
INTERVIEWER_FAST_MODELS = _chain("SPEAKWELL_INTERVIEWER_FAST_MODELS", "gemini-3.5-flash-lite,gemini-3.8-flash")
FAST_PHASES = {"intro", "candidate_questions"}
INTERVIEWER_THINKING = os.environ.get("SPEAKWELL_INTERVIEWER_THINKING", "").strip() or "low"
# Verbatim transcription with word timestamps (keeps "um"s, unlike Live).
TRANSCRIBE_MODEL = os.environ.get("SPEAKWELL_TRANSCRIBE_MODEL", "").strip() or "gemini-3.5-transcribe"

# Shown as a meter on the home screen. Matches the Google AI Pro monthly credit.
MONTHLY_BUDGET_USD = _float("SPEAKWELL_MONTHLY_BUDGET_USD", 10.0)

# Per-call ceilings, in seconds. A model that blows its ceiling is abandoned
# for the next one in its chain.
PLANNER_TIMEOUT_S = 75
GRADER_TIMEOUT_S = 150
DELIVERY_TIMEOUT_S = 120
TRANSCRIBE_TIMEOUT_S = 180
TURN_TRANSCRIBE_TIMEOUT_S = 30
# A reply slower than this is abandoned for the fast model, so you never wait long.
INTERVIEWER_TIMEOUT_S = 10

def get_api_key() -> str:
    key = os.environ.get("GEMINI_API_KEY", "").strip()
    if not key:
        raise RuntimeError(
            "GEMINI_API_KEY is not set. Add it to your .env file: "
            "GEMINI_API_KEY=your_key_here"
        )
    return key
