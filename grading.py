"""Transcription of each answer, and grading the finished interview.

During the interview each answer is transcribed verbatim with word timestamps
(`transcribe_turn`), so by the end we already have an exact, timestamped
record of everything you said. Grading then:
  1. Listens to your answers' audio for delivery: tone, energy, engagement.
  2. Computes exact stats in code: filler words, pace.
  3. Grades the timestamped conversation against the plan's rubric.
  4. Drops any feedback "moment" whose quote isn't in what you actually said.
"""
import base64
import json
import logging
import re
import warnings

from google.genai import types

import audio
import catalog
import config
import models
from pricing import CostMeter, PRICES

log = logging.getLogger(__name__)

SEGMENT_GAP_S = 2.0  # a pause longer than this starts a new transcript line
SEGMENT_MAX_S = 12.0  # ...and so does a line that has run this long

HARD_FILLERS = {"um", "uh", "uhm", "umm", "uhh", "er", "erm", "ah", "hmm", "mm", "eh"}
ALWAYS_SOFT = {"basically", "literally", "actually"}
# Counted only when set off by commas ("so, like, we..."), since "I like it"
# and "you know the answer" are not fillers.
COMMA_SOFT = {"like", "you know", "i mean", "kind of", "sort of"}


def mmss(seconds: float) -> str:
    seconds = max(0, int(seconds))
    return f"{seconds // 60:02d}:{seconds % 60:02d}"


def _norm(word: str) -> str:
    return re.sub(r"[^a-z']", "", word.lower())


def _offset(value) -> float:
    """Parse '1.300s' (or a number) into seconds."""
    if value is None:
        return 0.0
    if isinstance(value, (int, float)):
        return float(value)
    try:
        return float(str(value).rstrip("s"))
    except ValueError:
        return 0.0


# --- Transcription (once per answer, during the interview) -------------------
def transcribe_turn(mp3: bytes, meter: CostMeter) -> list[dict]:
    """Verbatim English words [{text, start, end}] with times relative to the clip."""
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")  # the Interactions API warns it is experimental
        response = models.client(config.TURN_TRANSCRIBE_TIMEOUT_S, "v1beta").interactions.create(
            model=config.TRANSCRIBE_MODEL,
            input=[{"type": "audio", "mime_type": audio.MP3_MIME,
                    "data": base64.b64encode(mp3).decode()}],
            generation_config={"transcription_config": {
                # Pinned to English: auto-detection is how other languages crept in.
                "language_codes": ["en-US"],
                "mode": {"type": "verbatim", "timestamp_granularities": ["word"]}}},
            # By default Google keeps Interactions requests for up to 55 days.
            store=False,
        )
    usage = getattr(response, "usage", None)
    if usage is not None:
        price = PRICES.get(config.TRANSCRIBE_MODEL, {"in": 2.0, "out": 12.0})
        meter.add_usd(config.TRANSCRIBE_MODEL,
                      ((usage.total_input_tokens or 0) * price["in"]
                       + (usage.total_output_tokens or 0) * price["out"]) / 1_000_000)
    words = []
    for step in getattr(response, "steps", None) or []:
        for content in getattr(step, "content", None) or []:
            for a in getattr(content, "annotations", None) or []:
                if getattr(a, "type", None) == "word_info" and getattr(a, "text", None):
                    words.append({"text": a.text, "start": _offset(a.start_offset),
                                  "end": _offset(a.end_offset)})
    return words


# --- 1b. Delivery -----------------------------------------------------------
DELIVERY_SCHEMA = {
    "type": "object",
    "properties": {
        "engagement": {"type": "integer"},
        "confidence": {"type": "integer"},
        "energy": {"type": "string"},
        "tone": {"type": "string"},
        "observations": {
            "type": "array",
            "items": {"type": "object",
                      "properties": {"time": {"type": "string"}, "note": {"type": "string"}},
                      "required": ["time", "note"]},
        },
    },
    "required": ["engagement", "confidence", "energy", "tone", "observations"],
}

DELIVERY_PROMPT = (
    "These are the candidate's spoken answers from a mock job interview, joined back to back "
    "(only their microphone; the interviewer is not included). "
    "Judge HOW they sound, not what they say: energy, enthusiasm, warmth, confidence, "
    "vocal variety vs monotone, hesitation, rushing, trailing off, upspeak, and whether "
    "they'd be engaging to talk with. Scores are 0-100 (higher is better); use the full "
    "range and don't cluster on multiples of 5. 'energy' and 'tone' are one or two "
    "sentences each. 'observations': 3-6 specific moments and what you noticed there; "
    "describe each moment by what they were saying (e.g. 'while explaining the cache'), "
    "and set 'time' to an empty string, because this audio's clock doesn't match the interview's."
)


def analyze_delivery(mp3: bytes, meter: CostMeter) -> dict:
    result = models.generate_json(
        config.DELIVERY_MODELS,
        [types.Part.from_bytes(data=mp3, mime_type=audio.MP3_MIME), DELIVERY_PROMPT],
        DELIVERY_SCHEMA, timeout_s=config.DELIVERY_TIMEOUT_S, meter=meter, task="delivery analysis",
    )
    return result.data


# --- 2. Exact stats ---------------------------------------------------------
def filler_stats(words: list[dict]) -> dict:
    hits: list[dict] = []
    for i, w in enumerate(words):
        raw = w["text"]
        token = _norm(raw)
        prev_raw = words[i - 1]["text"] if i else ""
        nxt = _norm(words[i + 1]["text"]) if i + 1 < len(words) else ""
        two = f"{token} {nxt}"
        if token in HARD_FILLERS:
            hits.append({"word": token, "t": w["start"], "hard": True})
        elif token in ALWAYS_SOFT:
            hits.append({"word": token, "t": w["start"], "hard": False})
        elif two in COMMA_SOFT:
            nxt_raw = words[i + 1]["text"]
            if prev_raw.endswith(",") or nxt_raw.endswith(","):
                hits.append({"word": two, "t": w["start"], "hard": False})
        elif token in COMMA_SOFT and (prev_raw.endswith(",") or raw.endswith(",")):
            hits.append({"word": token, "t": w["start"], "hard": False})
    counts: dict[str, int] = {}
    for h in hits:
        counts[h["word"]] = counts.get(h["word"], 0) + 1
    return {"hits": hits, "counts": counts}


def segments(words: list[dict]) -> list[dict]:
    """Group words into short spoken lines, each with its own start time.

    A new line starts after a pause, at a sentence end once the line has a
    few words, or when a line gets long. Short lines are what let feedback
    point at the exact moment instead of the start of a two-minute answer.
    """
    out: list[dict] = []
    for w in words:
        cur = out[-1] if out else None
        new_line = (
            cur is None
            or w["start"] - cur["end"] > SEGMENT_GAP_S
            or (cur["words"][-1].endswith((".", "?", "!")) and len(cur["words"]) >= 6)
            or w["start"] - cur["start"] > SEGMENT_MAX_S
        )
        if new_line:
            out.append({"start": w["start"], "end": w["end"], "words": [w["text"]]})
        else:
            cur["words"].append(w["text"])
            cur["end"] = w["end"]
    return out


def speaking_seconds(words: list[dict]) -> float:
    """Time spent talking: word spans, counting gaps between words up to the pause limit."""
    total = 0.0
    for prev, w in zip(words, words[1:]):
        gap = w["start"] - prev["start"]
        if gap <= SEGMENT_GAP_S:
            total += gap
    if words:
        total += words[-1]["end"] - words[-1]["start"]
    return total


def pace_wpm(words: list[dict]) -> int | None:
    seconds = speaking_seconds(words)
    if seconds < 20 or not words:
        return None
    return round(len(words) / seconds * 60)


def pace_score(wpm: int | None) -> int | None:
    """100 inside a comfortable 120-160 wpm band, falling off outside it."""
    if wpm is None:
        return None
    if 120 <= wpm <= 160:
        return 100
    off = 120 - wpm if wpm < 120 else wpm - 160
    return max(0, 100 - round(off * 1.5))


def filler_score(stats: dict, speaking_minutes: float) -> tuple[int | None, float | None]:
    """Score from filler rate (hard fillers count 1, soft 0.5): 0/min=100, 5/min=60, 10/min=20."""
    if speaking_minutes < 0.5:
        return None, None
    weight = sum(1.0 if h["hard"] else 0.5 for h in stats["hits"])
    rate = weight / speaking_minutes
    return max(0, round(100 - rate * 8)), round(rate, 1)


# --- 3. Grading -------------------------------------------------------------
def build_timeline_text(timeline: list[dict], segs: list[dict]) -> str:
    """Interviewer lines and typed answers from the timeline, spoken answers as
    short timestamped lines from the verbatim transcript."""
    rows: list[tuple[float, str]] = []
    for e in timeline:
        if e["who"] == "interviewer":
            rows.append((e["t"], f"Interviewer: {e['text']}"))
        elif e["who"] == "event":
            rows.append((e["t"], f"({e['text']})"))
        elif e["who"] == "candidate" and e.get("typed"):
            rows.append((e["t"], f"Candidate (typed): {e['text']}"))
    for s in segs:
        rows.append((s["start"], "Candidate: " + " ".join(s["words"])))
    rows.sort(key=lambda r: r[0])
    return "\n".join(f"[{mmss(t)}] {line}" for t, line in rows)


def _grade_schema(kind: str) -> dict:
    ids = [cid for cid, _, _ in catalog.RUBRICS[kind]]
    return {
        "type": "object",
        "properties": {
            "overall_score": {"type": "integer"},
            "verdict": {"type": "string"},
            "categories": {
                "type": "array",
                "items": {"type": "object",
                          "properties": {"id": {"type": "string", "enum": ids},
                                         "score": {"type": "integer"},
                                         "reason": {"type": "string"}},
                          "required": ["id", "score", "reason"]},
            },
            "moments": {
                "type": "array",
                "items": {"type": "object",
                          "properties": {"time": {"type": "string"}, "quote": {"type": "string"},
                                         "issue": {"type": "string"}, "better": {"type": "string"},
                                         "type": {"type": "string",
                                                  "enum": ["content", "communication", "structure", "delivery", "strength"]}},
                          "required": ["time", "quote", "issue", "better", "type"]},
            },
            "strengths": {"type": "array", "items": {"type": "string"}},
            "improvements": {"type": "array", "items": {"type": "string"}},
            "questions_for_them": {"type": "object",
                                   "properties": {"score": {"type": "integer"}, "feedback": {"type": "string"}},
                                   "required": ["score", "feedback"]},
            "engagement_feedback": {"type": "string"},
            "work_review": {"type": "string"},
        },
        "required": ["overall_score", "verdict", "categories", "moments", "strengths",
                     "improvements", "questions_for_them", "engagement_feedback", "work_review"],
    }


def _grade_prompt(session, timeline_text: str, final_work: str, stats_text: str, delivery: dict | None) -> str:
    kind = session.kind
    rubric = "\n".join(f"- {cid} ({label}): {desc}" for cid, label, desc in catalog.RUBRICS[kind])
    work_label = {"coding": "FINAL CODE IN THE EDITOR", "system_design": "CANDIDATE'S NOTES"}.get(kind)
    work = f"\n{work_label}:\n<<<\n{final_work or '(empty)'}\n>>>\n" if work_label else ""
    review = {"coding": "a short code review of the final code (correctness, bugs, style, complexity), comparing with the reference solution",
              "system_design": "a short review of the design: what was strong, what was missing compared with must_cover and the deep-dive topics"}.get(
        kind, "an empty string")
    ended = (f"The candidate ENDED EARLY after {mmss(session.elapsed_s)} of {session.minutes}:00. "
             "Grade what they covered; mention unfinished parts as improvements but don't "
             "re-penalize the same gap in every category." if session.ended_early else
             f"The interview ran {mmss(session.elapsed_s)} of a planned {session.minutes}:00.")
    return f"""You are a hiring-committee grader for a {catalog.KINDS[kind]['label']} mock
interview. Candidate level: {catalog.LEVELS[session.level]}, track: {catalog.TRACKS[session.track]}.
Calibrate to that level: an average real {catalog.LEVELS[session.level].lower()} candidate scores about 55-65,
a clear hire 75+, exceptional 90+. Be honest and specific; this is for practice, so
kind-but-direct beats flattering. {ended}

Hints used (coding): {session.hints_used}. Each hint should lower "approach" a bit.

RUBRIC (score each category 0-100; use the full range, no clustering on multiples of 5):
{rubric}

THE HIDDEN INTERVIEW PLAN (what the interviewer was looking for):
{json.dumps(session.plan, indent=1)[:30000]}

TIMESTAMPED TRANSCRIPT. Candidate lines are verbatim speech, including filler words
(lines marked "typed" were typed instead of spoken). Interviewer lines are exact.
<<<
{timeline_text[:120000]}
>>>
{work}
MEASURED DELIVERY STATS (computed exactly; use them, don't recount):
{stats_text}

VOICE ANALYSIS (from the audio): {json.dumps(delivery) if delivery else "unavailable"}

Return:
- overall_score (0-100): weight content ~75% and delivery/communication ~25%.
- verdict: one sentence a hiring manager would say.
- categories: one entry per rubric id with a score and a one-to-two-sentence reason
  citing specific moments.
- moments: 6-14 precise feedback items in time order. "time" is the [MM:SS] of the
  transcript line. "quote" is copied EXACTLY from a Candidate line (a short phrase,
  max ~20 words; quotes not found in the transcript are discarded). "issue" says what
  was weak or, for type "strength", what was good. "better" is what to say or do
  instead (for strengths, how to keep doing it). Cover content mistakes, vague or
  unsupported claims, missed questions (e.g. scale questions in system design),
  rambling, weak structure, and at least one strength.
- strengths and improvements: 3-5 each, concrete.
- questions_for_them: how good the candidate's questions at the end were (0-100)
  and why. If they asked none, score low and say so.
- engagement_feedback: how they came across to talk to (interest, energy, rapport).
- work_review: {review}.
"""


def _validate_grade(data: dict) -> None:
    if not data.get("categories"):
        raise models.ModelError("grade has no category scores")
    if not isinstance(data.get("overall_score"), int):
        raise models.ModelError("grade has no overall score")


def _norm_text(s: str) -> str:
    return " ".join(re.sub(r"[^a-z0-9' ]", " ", s.lower()).split())


def keep_real_quotes(moments: list[dict], candidate_text: str) -> list[dict]:
    """Drop moments whose quote the candidate never said (model hallucination guard)."""
    haystack = _norm_text(candidate_text)
    kept = []
    for m in moments:
        q = _norm_text(m.get("quote", ""))
        if not q:
            continue
        probe = " ".join(q.split()[:6])  # first words: tolerant of a sloppy ending
        if probe and probe in haystack:
            kept.append(m)
    return kept


def grade(session, final_work: str, progress=lambda stage: None) -> dict:
    """Grade a finished interview and return the report dict."""
    meter = session.meter
    notes: list[str] = []
    words = session.words
    delivery: dict | None = None

    progress("delivery")
    if session.audio:
        try:
            # MP3 frames concatenate cleanly, so the answers join into one clip.
            delivery = analyze_delivery(b"".join(session.audio), meter)
        except Exception:  # noqa: BLE001 - voice analysis is a bonus, never fatal
            log.exception("Delivery analysis failed")
            notes.append("Voice analysis was unavailable for this interview.")
    else:
        notes.append("You didn't answer out loud, so filler words and voice analysis are unavailable.")

    segs = segments(words)
    stats = filler_stats(words)
    speaking_min = speaking_seconds(words) / 60
    f_score, f_rate = filler_score(stats, speaking_min) if words else (None, None)
    wpm = pace_wpm(words)
    p_score = pace_score(wpm)
    stats_text = (
        f"Speaking time: {speaking_min:.1f} min. Filler rate: {f_rate} per minute "
        f"(hard fillers count 1, soft 0.5). Filler counts: {stats['counts'] or 'none'}. "
        f"Pace: {wpm} words/min while speaking. Filler score {f_score}, pace score {p_score}."
        if words else "Unavailable (no spoken answers)."
    )

    progress("grading")
    timeline_text = build_timeline_text(session.timeline, segs)
    result = models.generate_json(
        config.GRADER_MODELS, [_grade_prompt(session, timeline_text, final_work, stats_text, delivery)],
        _grade_schema(session.kind), timeout_s=config.GRADER_TIMEOUT_S, meter=meter,
        thinking="medium", task="grading", validate=_validate_grade,
    )
    g = result.data

    typed = " ".join(e["text"] for e in session.timeline if e["who"] == "candidate" and e.get("typed"))
    candidate_text = " ".join(w["text"] for w in words) + " " + typed
    moments = keep_real_quotes(g.get("moments", []), candidate_text)

    labels = {cid: label for cid, label, _ in catalog.RUBRICS[session.kind]}
    by_id = {c["id"]: c for c in g.get("categories", []) if c.get("id") in labels}
    categories = [{"id": cid, "label": labels[cid], "score": by_id[cid]["score"], "reason": by_id[cid]["reason"]}
                  for cid in labels if cid in by_id]

    filler_moments = [{"time": mmss(h["t"]), "word": h["word"], "hard": h["hard"]} for h in stats["hits"]][:60]
    return {
        "title": session.title,
        "kind": session.kind, "track": session.track, "level": session.level,
        "persona": session.persona.label, "interviewer_name": session.interviewer_name,
        "duration_sec": int(session.elapsed_s), "planned_minutes": session.minutes,
        "ended_early": session.ended_early, "hints_used": session.hints_used,
        "overall_score": g.get("overall_score"), "verdict": g.get("verdict", ""),
        "categories": categories,
        "delivery": {
            "filler_score": f_score, "filler_rate_per_min": f_rate, "filler_counts": stats["counts"],
            "filler_moments": filler_moments, "pace_wpm": wpm, "pace_score": p_score,
            "engagement_score": (delivery or {}).get("engagement"),
            "confidence_score": (delivery or {}).get("confidence"),
            "energy": (delivery or {}).get("energy", ""), "tone": (delivery or {}).get("tone", ""),
            "observations": (delivery or {}).get("observations", []),
            "engagement_feedback": g.get("engagement_feedback", ""),
        },
        "questions_for_them": g.get("questions_for_them", {}),
        "moments": moments,
        "strengths": g.get("strengths", []), "improvements": g.get("improvements", []),
        "work_review": g.get("work_review", ""),
        "reference": session.public_reference(),
        "notes": notes,
        "models": {"planner": session.planner_model, "grader": result.model},
    }


def scores_for_history(report: dict) -> dict:
    """Flat {id: 0-100} map stored for progress charts."""
    out = {c["id"]: c["score"] for c in report.get("categories", [])}
    d = report.get("delivery", {})
    for key, src in (("fillers", "filler_score"), ("pace", "pace_score"), ("engagement", "engagement_score")):
        if d.get(src) is not None:
            out[key] = d[src]
    q = (report.get("questions_for_them") or {}).get("score")
    if q is not None:
        out["questions"] = q
    return out
