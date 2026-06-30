import os
from dotenv import load_dotenv

load_dotenv()

# Retired / non-audio Gemini families that will fail at request time. SpeakWell
# sends audio, so the model must be audio-capable. We reject these early with a
# clear message instead of letting Gemini return a cryptic error mid-request.
_RETIRED_MODEL_PREFIXES = (
    "gemini-1.",   # 1.0 / 1.5 families, retired
    "gemini-2.0",  # shut down 2026-06-01
)


def _validate_model(model: str) -> str:
    lowered = model.lower()
    for prefix in _RETIRED_MODEL_PREFIXES:
        if lowered.startswith(prefix):
            raise RuntimeError(
                f"GEMINI_MODEL='{model}' is a retired Gemini model and will not "
                "work. SpeakWell needs an audio-capable model such as "
                "gemini-3.1-flash-lite (default) or gemini-2.5-flash."
            )
    return model


# Model is configurable via GEMINI_MODEL in .env. Default: gemini-3.1-flash-lite
# (audio-capable, generous free-tier RPD). gemini-2.0-flash was shut down 2026-06-01.
GEMINI_MODEL = _validate_model(
    os.environ.get("GEMINI_MODEL", "").strip() or "gemini-3.1-flash-lite"
)


def get_api_key() -> str:
    key = os.environ.get("GEMINI_API_KEY", "").strip()
    if not key:
        raise RuntimeError(
            "GEMINI_API_KEY is not set. Add it to your .env file: "
            "GEMINI_API_KEY=your_key_here"
        )
    return key
