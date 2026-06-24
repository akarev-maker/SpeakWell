import os
from dotenv import load_dotenv

load_dotenv()

# gemini-2.0-flash was shut down 2026-06-01; use the current stable Flash model.
GEMINI_MODEL = "gemini-2.5-flash"


def get_api_key() -> str:
    key = os.environ.get("GEMINI_API_KEY", "").strip()
    if not key:
        raise RuntimeError(
            "GEMINI_API_KEY is not set. Add it to your .env file: "
            "GEMINI_API_KEY=your_key_here"
        )
    return key
