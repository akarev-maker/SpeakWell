import os
from dotenv import load_dotenv

load_dotenv()

# Model is configurable via GEMINI_MODEL in .env. Default: gemini-3.1-flash-lite
# (audio-capable, generous free-tier RPD). gemini-2.0-flash was shut down 2026-06-01.
GEMINI_MODEL = os.environ.get("GEMINI_MODEL", "").strip() or "gemini-3.1-flash-lite"


def get_api_key() -> str:
    key = os.environ.get("GEMINI_API_KEY", "").strip()
    if not key:
        raise RuntimeError(
            "GEMINI_API_KEY is not set. Add it to your .env file: "
            "GEMINI_API_KEY=your_key_here"
        )
    return key
