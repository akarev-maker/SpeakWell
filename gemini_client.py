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

INTERVIEW_FIELDS = ["answer_critique", "model_answer"]

INTERVIEW_SCHEMA = {
    "type": "object",
    "properties": {
        **RESPONSE_SCHEMA["properties"],
        "answer_critique": {"type": "string"},
        "model_answer": {"type": "string"},
    },
    "required": RESPONSE_SCHEMA["required"] + INTERVIEW_FIELDS,
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


def build_interview_addendum(question: str) -> str:
    """Extra instruction appended when analyzing a mock-interview answer."""
    return (
        "\n\nThis is a MOCK INTERVIEW. The speaker is answering this interview "
        f'question: "{question.strip()}". In addition to the fields above, also '
        'return "answer_critique" (2-3 sentences assessing how well the spoken '
        "answer addresses the question — relevance, specific examples, structure, "
        'and what was missing) and "model_answer" (a concise, stronger example '
        "answer to the same question that the speaker can learn from)."
    )


PROMPT_INSTRUCTION = (
    "Generate ONE short speaking-practice prompt (a single sentence or question) "
    'for someone rehearsing their spoken delivery. Their goal/context is: "{context}". '
    "Make the prompt directly relevant to that context so they can practice for it. "
    "Return ONLY the prompt text — no quotes, no preamble, no numbering."
)

INTERVIEW_QUESTION_INSTRUCTION = (
    "Generate ONE realistic interview question for a candidate. Their goal/"
    'context is: "{context}". Make it a question a real interviewer would ask '
    "for that context (behavioral or role-appropriate). "
    "Return ONLY the question text — no quotes, no preamble, no numbering."
)


def _build_client() -> genai.Client:
    return genai.Client(api_key=config.get_api_key())


def generate_prompt(context: str) -> str:
    """Generate a single speaking prompt tailored to the user's context."""
    client = _build_client()
    response = client.models.generate_content(
        model=config.GEMINI_MODEL,
        contents=[PROMPT_INSTRUCTION.format(context=context.strip())],
    )
    text = (response.text or "").strip().strip('"').strip()
    if not text:
        raise RuntimeError("Gemini returned an empty prompt")
    return text


QUESTIONS_SCHEMA = {
    "type": "object",
    "properties": {"questions": {"type": "array", "items": {"type": "string"}}},
    "required": ["questions"],
}

SUMMARY_SCHEMA = {
    "type": "object",
    "properties": {
        "level": {"type": "string"},
        "summary": {"type": "string"},
        "strengths": {"type": "array", "items": {"type": "string"}},
        "improvements": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["level", "summary", "strengths", "improvements"],
}


def generate_interview_questions(context: str) -> list[str]:
    """Generate a tailored set of interview questions (model decides the count)."""
    instruction = (
        "You are an interviewer. Generate a set of interview questions for a "
        f'candidate. Their target role / job description is: "{context.strip()}". '
        "Choose an appropriate NUMBER of questions for the role and seniority "
        "(between 3 and 8). Order them as a real interview would (warm-up first, "
        "harder/role-specific later). Return ONLY a JSON object of the form "
        '{"questions": [string, ...]}.'
    )
    client = _build_client()
    response = client.models.generate_content(
        model=config.GEMINI_MODEL,
        contents=[instruction],
        config=types.GenerateContentConfig(
            response_mime_type="application/json",
            response_schema=QUESTIONS_SCHEMA,
        ),
    )
    data = parse_json(response.text)
    questions = [q for q in data.get("questions", []) if isinstance(q, str) and q.strip()]
    if not questions:
        raise RuntimeError("Gemini returned an empty question set")
    return questions[:8]


def summarize_interview(context: str, qa_pairs: list[dict]) -> dict:
    """Produce an overall readiness debrief across all answered questions."""
    transcript = "\n\n".join(
        f"Q: {p.get('question', '')}\nA: {p.get('answer', '')}" for p in qa_pairs
    )
    instruction = (
        "You are an interview coach giving an overall readiness debrief. The "
        f'candidate is preparing for: "{context.strip()}". Here is the full mock '
        f"interview (each question and the candidate's spoken answer):\n\n{transcript}\n\n"
        "Assess overall readiness across all answers. Return ONLY a JSON object: "
        '{"level": string (a short readiness label, e.g. "Almost ready", '
        '"Getting there", "Needs work"), "summary": string (2-3 sentences), '
        '"strengths": [string], "improvements": [string] (concrete and specific)}.'
    )
    client = _build_client()
    response = client.models.generate_content(
        model=config.GEMINI_MODEL,
        contents=[instruction],
        config=types.GenerateContentConfig(
            response_mime_type="application/json",
            response_schema=SUMMARY_SCHEMA,
        ),
    )
    data = parse_json(response.text)
    for field in ("level", "summary", "strengths", "improvements"):
        if field not in data:
            raise RuntimeError(f"Interview summary missing '{field}'")
    return data


def generate_interview_question(context: str) -> str:
    """Generate one realistic interview question tailored to the context."""
    client = _build_client()
    response = client.models.generate_content(
        model=config.GEMINI_MODEL,
        contents=[INTERVIEW_QUESTION_INSTRUCTION.format(context=context.strip())],
    )
    text = (response.text or "").strip().strip('"').strip()
    if not text:
        raise RuntimeError("Gemini returned an empty interview question")
    return text


def parse_json(text: str) -> dict:
    """Strip any markdown fence and parse a JSON object from a Gemini response."""
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
        return json.loads(cleaned)
    except (json.JSONDecodeError, ValueError) as exc:
        raise RuntimeError(f"Could not parse Gemini response: {exc}") from exc


def parse_response(text: str, require_interview: bool = False) -> dict:
    data = parse_json(text)
    if not isinstance(data.get("scores"), dict):
        raise RuntimeError("Gemini response missing 'scores' object")
    for key in SCORE_KEYS:
        if key not in data["scores"]:
            raise RuntimeError(f"Gemini response missing scores.{key}")
    required = ("transcript", "filler_words", "feedback", "tips")
    if require_interview:
        required = required + tuple(INTERVIEW_FIELDS)
    for field in required:
        if field not in data:
            raise RuntimeError(f"Gemini response missing '{field}'")
    return data


def analyze_speech(
    wav_bytes: bytes,
    prompt: str | None = None,
    context: str | None = None,
    question: str | None = None,
) -> dict:
    interview = bool(question and question.strip())
    instruction = build_instruction(prompt, context)
    if interview:
        instruction += build_interview_addendum(question)
    client = _build_client()
    response = client.models.generate_content(
        model=config.GEMINI_MODEL,
        contents=[
            types.Part.from_bytes(data=wav_bytes, mime_type="audio/wav"),
            instruction,
        ],
        config=types.GenerateContentConfig(
            response_mime_type="application/json",
            response_schema=INTERVIEW_SCHEMA if interview else RESPONSE_SCHEMA,
        ),
    )
    return parse_response(response.text, require_interview=interview)
