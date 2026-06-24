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
    '"transcript": string, "filler_words": [string], "feedback": string, '
    '"tips": [string]}\n'
    "Each score is an integer from 0 to 100 (higher is better). Use the FULL "
    "range and be precise and discriminating: do NOT default to round numbers "
    "like 70, 75, or 80 — if the delivery is an 83, score it 83, not 85. "
    "Avoid clustering scores on multiples of 5 or 10. "
    "'transcript' is a faithful transcript of the speech. "
    "'filler_words' lists the distinct filler words actually used "
    "(e.g. um, uh, like, you know); empty list if none. "
    "'feedback' is 1-2 sentences summarizing the overall delivery. "
    "'tips' is a list of 3-5 concrete, specific, actionable improvements the "
    "speaker can apply next time — each tip a single short imperative sentence "
    "tied to something they actually did (quote or paraphrase a moment from "
    "their speech where helpful), not generic advice. Cover the weakest areas "
    "across filler words, pace & pauses, clarity & structure, and confidence "
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
        "tips": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["scores", "transcript", "filler_words", "feedback", "tips"],
}


def build_instruction(prompt: str | None, context: str | None = None) -> str:
    """Return the coaching instruction, tailored to a user prompt and context."""
    text = INSTRUCTION
    if context and context.strip():
        text += (
            "\n\nAbout the speaker and their goal: "
            f'"{context.strip()}". '
            "Tailor your feedback and tips to this context — make the advice "
            "relevant to where and why they speak, and weight what matters most "
            "for their goal."
        )
    if prompt and prompt.strip():
        text += (
            "\n\nThe speaker was asked to respond to this prompt: "
            f'"{prompt.strip()}". '
            "Take into account how well they addressed the prompt — staying on "
            "topic and answering what was asked — in the 'clarity_structure' "
            "score and mention it in the feedback."
        )
    return text


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
    for field in ("transcript", "filler_words", "feedback", "tips"):
        if field not in data:
            raise RuntimeError(f"Gemini response missing '{field}'")
    return data


def analyze_speech(
    wav_bytes: bytes, prompt: str | None = None, context: str | None = None
) -> dict:
    client = _build_client()
    response = client.models.generate_content(
        model=config.GEMINI_MODEL,
        contents=[
            types.Part.from_bytes(data=wav_bytes, mime_type="audio/wav"),
            build_instruction(prompt, context),
        ],
        config=types.GenerateContentConfig(
            response_mime_type="application/json",
            response_schema=RESPONSE_SCHEMA,
        ),
    )
    return parse_response(response.text)
