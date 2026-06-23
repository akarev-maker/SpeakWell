import json
from google import genai
from google.genai import types

import config

SCORE_KEYS = ["filler_words", "pace_pauses", "clarity_structure", "confidence_tone"]

INSTRUCTION = (
    "You are SpeakWell, a speech coach. Listen to the attached audio of a "
    "person speaking and evaluate their delivery. Return ONLY a JSON object "
    "with this exact shape:\n"
    '{"scores": {"filler_words": int, "pace_pauses": int, '
    '"clarity_structure": int, "confidence_tone": int}, '
    '"transcript": string, "filler_words": [string], "feedback": string}\n'
    "Each score is an integer 0-100 (higher is better). "
    "'transcript' is a faithful transcript of the speech. "
    "'filler_words' lists the distinct filler words actually used "
    "(e.g. um, uh, like, you know); empty list if none. "
    "'feedback' is 2-4 sentences of specific, encouraging, actionable coaching "
    "covering filler words, pace & pauses, clarity & structure, and confidence "
    "& tone. Do not wrap the JSON in markdown."
)

RESPONSE_SCHEMA = {
    "type": "object",
    "properties": {
        "scores": {
            "type": "object",
            "properties": {k: {"type": "integer"} for k in SCORE_KEYS},
            "required": SCORE_KEYS,
        },
        "transcript": {"type": "string"},
        "filler_words": {"type": "array", "items": {"type": "string"}},
        "feedback": {"type": "string"},
    },
    "required": ["scores", "transcript", "filler_words", "feedback"],
}


def _build_client() -> genai.Client:
    return genai.Client(api_key=config.get_api_key())


def parse_response(text: str) -> dict:
    if not text:
        raise RuntimeError("Gemini returned an empty response")
    cleaned = text.strip()
    if cleaned.startswith("```"):
        # strip leading ```json / ``` and trailing ```
        cleaned = cleaned.split("```", 2)
        cleaned = cleaned[1] if len(cleaned) >= 2 else text
        if cleaned.startswith("json"):
            cleaned = cleaned[len("json"):]
        cleaned = cleaned.strip().rstrip("`").strip()
    try:
        data = json.loads(cleaned)
    except (json.JSONDecodeError, ValueError) as exc:
        raise RuntimeError(f"Could not parse Gemini response: {exc}") from exc

    if not isinstance(data.get("scores"), dict):
        raise RuntimeError("Gemini response missing 'scores' object")
    for key in SCORE_KEYS:
        if key not in data["scores"]:
            raise RuntimeError(f"Gemini response missing scores.{key}")
    for field in ("transcript", "filler_words", "feedback"):
        if field not in data:
            raise RuntimeError(f"Gemini response missing '{field}'")
    return data


def analyze_speech(wav_bytes: bytes) -> dict:
    client = _build_client()
    response = client.models.generate_content(
        model=config.GEMINI_MODEL,
        contents=[
            types.Part.from_bytes(data=wav_bytes, mime_type="audio/wav"),
            INSTRUCTION,
        ],
        config=types.GenerateContentConfig(
            response_mime_type="application/json",
            response_schema=RESPONSE_SCHEMA,
        ),
    )
    return parse_response(response.text)
