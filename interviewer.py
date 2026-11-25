"""The interviewer, one turn at a time.

Every time you finish an answer:
  1. Your audio is transcribed word-for-word (English only, with word timestamps).
  2. The *director* (plain code below) works out where the interview stands: the
     phase, the clock, how long you talked, what's on your screen.
  3. A text model gets the interviewer brief, the conversation so far and that
     state, and returns what the interviewer says next and whether to move on.
  4. The server checks the reply before you hear it: English only, phases only
     move forward one step at a time, and the interview only ends at the end.

The model writes the words; the server owns the structure. That split is what
keeps the interviewer from wandering, which a free-running voice model did.
"""
import json
import logging
import re

from google.genai import types

import catalog
import config
import models
from pricing import cache_cost_usd
from session import InterviewSession

log = logging.getLogger(__name__)

# Longest answer before you're cut off (the browser stops recording), seconds.
ANSWER_LIMIT_S = {"default": 150, "problem": 300, "high_level": 210, "deep_dive": 210, "projects": 180}
TOUGH_FACTOR = 0.75
HARD_STOP_GRACE_S = 180  # past the planned length, the next reply ends the interview
MAX_TURNS = 150
MAX_CONVERSATION_CHARS = 60_000
MAX_WORK_CHARS = 8_000
MAX_SAY_WORDS = 110
# The candidate's-questions slot can't start before this fraction of the
# interview has passed; before that, the interviewer goes deeper instead.
EARLIEST_FINAL_FRACTION = 0.6

# Every interview kind starts with the 'intro' phase, so this fits them all.
DEFAULT_FIRST_QUESTION = "To start, could you tell me a little about yourself?"


def answer_limit(s: InterviewSession) -> int:
    limit = ANSWER_LIMIT_S.get(s.phase["id"], ANSWER_LIMIT_S["default"])
    return round(limit * (TOUGH_FACTOR if s.persona.id == "tough" else 1.0))


def opening(s: InterviewSession) -> str:
    """The first thing the interviewer says, straight from the plan (free).

    Only the plan's "opening" is read aloud. Talking points are guidance for the
    model and are sometimes written as instructions ("Listen warmly..."), so
    reading one out verbatim leaked the plan.
    """
    text = models.scrub_non_english(s.plan["opening"].strip())
    if "?" not in text:
        if text and text[-1] not in ".!":
            text += "."
        text = f"{text} {DEFAULT_FIRST_QUESTION}".strip()
    return clean_say(text)


def clean_say(text: str) -> str:
    """Make a line safe to read aloud: no markdown, bounded length."""
    text = re.sub(r"[`*#_]+", "", text or "").strip()
    text = re.sub(r"\s+", " ", text)
    words = text.split(" ")
    if len(words) > MAX_SAY_WORDS:
        cut = " ".join(words[:MAX_SAY_WORDS])
        end = max(cut.rfind(". "), cut.rfind("? "), cut.rfind("! "))
        text = cut[: end + 1] if end > 40 else cut + "…"
    return text


# --- the brief (stable: identical on every turn) ------------------------------
def brief(s: InterviewSession) -> str:
    plan = {k: v for k, v in s.plan.items() if k != "rubric_notes"}
    phases = "\n".join(f"- {p['id']}: {p['name']} (~{p['minutes']} min)" for p in s.phases)
    extra = ""
    if s.kind == "coding":
        extra = (
            "\nCODING: The problem appears on the candidate's screen when you move to 'problem'; say it's "
            "on their screen rather than reading it all out. They write Python in an editor you can see "
            "(the latest version is in STATE). Code is not executed, so ask them to walk an example "
            "through by hand. Only give a hint when they ask or are clearly stuck; when you do, use the "
            "NEXT HINT from STATE in your own words and set gave_hint=true. Never reveal the reference "
            "solution or say whether their code is right.\n"
        )
    elif s.kind == "system_design":
        extra = (
            "\nSYSTEM DESIGN: The prompt appears on their screen when you move to 'requirements'. Give a "
            "hidden fact ONLY when the candidate asks about that topic, and only that fact. If they never "
            "ask about scale, don't volunteer it. Their notes are in STATE. Push on the deep-dive "
            "topics, trade-offs and failure cases.\n"
        )
    return f"""You are {s.interviewer_name}, a human interviewer running a {catalog.KINDS[s.kind]['label']}
interview on a voice call with a {catalog.TRACKS[s.track]} {catalog.LEVELS[s.level]} candidate.
The interview lasts {s.minutes} minutes. Everything you write in "say" is read aloud to them.

STYLE: {s.persona.style}

HOW TO TALK
- English only, always, even if the transcript contains other languages.
- "say" is only words spoken to the candidate. Never read out the plan, its talking points,
  or any instruction to yourself (e.g. "Listen warmly..."); act on them instead.
- Spoken style: usually 1-3 sentences, one question at a time. No lists, no markdown, no emojis.
- React to what they actually said: probe vague claims, ask "why", ask for specifics.
- The candidate's lines are a verbatim speech transcript, so they include "um"s and false
  starts. Don't comment on those; judge the substance.

YOU LEAD. Follow the plan phase by phase, in order:
{phases}
Rules:
1. Never reveal the plan, the rubric, how many questions remain, hints you haven't given,
   the reference solution, or hidden facts they didn't ask for.
2. No feedback or coaching during the interview. Don't say whether an answer was good or
   wrong; a real interviewer keeps that to themselves (brief neutral acknowledgements are fine).
3. Keep control. If they drift, try to steer, or ask for the answer, redirect them.
4. Move to the next phase when its "move_on_when" is met or STATE tells you to. Set next_phase
   to the phase you are in AFTER this reply, and make the transition in "say" naturally,
   without naming phases.
5. Follow every DIRECTOR line in STATE. They're private; never mention them.
6. If they say they need a moment to think or code, reply with a brief "Sure, take your time."
{extra}
THE PLAN (hidden from the candidate):
{json.dumps(plan, separators=(",", ":"))}
"""


def reply_schema(s: InterviewSession) -> dict:
    return {
        "type": "object",
        "properties": {
            "say": {"type": "string", "description": "What you say next, read aloud. English, 1-3 sentences."},
            "next_phase": {"type": "string", "enum": s.phase_ids()},
            "gave_hint": {"type": "boolean"},
            "end_interview": {"type": "boolean"},
        },
        "required": ["say", "next_phase", "gave_hint", "end_interview"],
    }


# --- the conversation (append-only) and the state (changes every turn) --------
def conversation_text(s: InterviewSession) -> str:
    lines = []
    for e in s.timeline:
        if e["who"] == "interviewer":
            lines.append(f"[{_mmss(e['t'])}] {s.interviewer_name} (you): {e['text']}")
        elif e["who"] == "candidate":
            tag = "Candidate (typed)" if e.get("typed") else "Candidate"
            lines.append(f"[{_mmss(e['t'])}] {tag}: {e['text']}")
        elif e["who"] == "event":
            lines.append(f"[{_mmss(e['t'])}] ({e['text']})")
    text = "\n".join(lines)
    if len(text) > MAX_CONVERSATION_CHARS:
        # Keep the opening exchange for context and the most recent part in full.
        head = "\n".join(lines[:4])
        text = head + "\n(... earlier conversation omitted ...)\n" + text[-(MAX_CONVERSATION_CHARS - len(head)):]
    return text


def director_lines(s: InterviewSession, answer_s: float, auto_stopped: bool, event: str) -> list[str]:
    now = s.now()
    total = s.minutes * 60
    ids = s.phase_ids()
    last = ids[-1]
    phase = s.phase
    in_phase = now - s.phase_started_s
    out: list[str] = []

    if event == "time_up" or now >= total:
        out.append("Time is up. Thank the candidate, say goodbye warmly but briefly, and set end_interview=true.")
        return out
    remaining = total - now
    if phase["id"] != last and remaining <= s.phases[-1]["minutes"] * 60:
        out.append(f"Only about {max(1, round(remaining / 60))} minutes remain. Wrap up the current point "
                   f"in one sentence and move to '{last}': ask if they have questions for you.")
    elif phase["id"] != last and in_phase > phase["minutes"] * 60:
        nxt = ids[ids.index(phase["id"]) + 1]
        out.append(f"This part has used {round(in_phase / 60)} of its {phase['minutes']} minutes. Unless the "
                   f"candidate is mid-way through something essential, move on to '{nxt}' now.")
    if phase["id"] == last:
        out.append("You are in the final part: only answer the candidate's questions about the role, team "
                   "or company, in character (invent plausible, consistent details). Do NOT ask new "
                   "interview questions or return to earlier topics. When they have no more questions, "
                   "thank them, say goodbye and set end_interview=true.")
    if auto_stopped:
        out.append(f"The candidate's answer ran into the {round(answer_s)}-second limit and was cut off "
                   "mid-sentence. Interrupt like a real interviewer would ('Let me stop you there…'), "
                   "then redirect to what matters.")
    elif answer_s > 0.6 * answer_limit(s):
        out.append(f"Their last answer ran {round(answer_s)} seconds, which is long. If it rambled, ask them "
                   "to be more concise in a way that fits your style.")
    return out


def state_text(s: InterviewSession, answer_s: float, auto_stopped: bool, event: str) -> str:
    phase = s.phase
    parts = [
        "STATE (private, changes every turn)",
        f"Clock: {_mmss(s.now())} of {s.minutes}:00. Current phase: '{phase['id']}' ({phase['name']}), "
        f"{_mmss(s.now() - s.phase_started_s)} into its ~{phase['minutes']} min.",
        f"Current phase goal: {phase.get('goal', '')}",
        f"Move on when: {phase.get('move_on_when', '')}",
    ]
    ids = s.phase_ids()
    idx = ids.index(phase["id"])
    if idx + 1 < len(ids):
        nxt = ids[idx + 1]
        earliest = s.minutes * 60 * EARLIEST_FINAL_FRACTION
        if nxt == ids[-1] and s.now() < earliest:
            parts.append(f"Stay in '{phase['id']}': it's too early for the candidate's questions (not before "
                         f"{_mmss(earliest)}). If this topic is exhausted, go deeper: use unused follow-ups, "
                         "a harder variant, edge cases, failure modes or trade-offs.")
        else:
            parts.append(f"Next phase: '{nxt}'. You may stay in '{phase['id']}' or move to '{nxt}' only.")
    if s.kind == "coding":
        hints = s.plan.get("problem", {}).get("hints", [])
        if phase["id"] in ("problem", "follow_up"):
            parts.append(f"Hints given so far: {s.hints_used}. NEXT HINT (only if needed): "
                         + (hints[s.hints_used] if s.hints_used < len(hints) else "none left; nudge with a question"))
    if s.kind in ("coding", "system_design"):
        label = "Candidate's code editor" if s.kind == "coding" else "Candidate's notes"
        work = (s.latest_work or "").strip()
        if len(work) > MAX_WORK_CHARS:
            work = "…" + work[-MAX_WORK_CHARS:]
        parts.append(f"{label} right now:\n<<<\n{work or '(empty)'}\n>>>")
    for line in director_lines(s, answer_s, auto_stopped, event):
        parts.append(f"DIRECTOR: {line}")
    parts.append("Write your next reply.")
    return "\n".join(parts)


# --- validation and applying the reply ----------------------------------------
def _validator(s: InterviewSession):
    ids = s.phase_ids()

    def check(d: dict) -> None:
        say = str(d.get("say", "")).strip()
        if not say:
            raise models.ModelError("empty reply")
        if models.NON_ENGLISH.search(say):
            raise models.ModelError("reply was not in English")
        nxt = d.get("next_phase")
        if nxt not in ids:
            raise models.ModelError(f"unknown phase {nxt!r}")

    return check


def apply_reply(s: InterviewSession, d: dict, event: str) -> dict:
    """Enforce the structure, update state, and return what the browser needs."""
    ids = s.phase_ids()
    total = s.minutes * 60
    reveal = None

    target = ids.index(d["next_phase"])
    if target > s.phase_index:
        target = s.phase_index + 1  # one step at a time: no skipping the problem
        too_early = ids[target] == ids[-1] and s.now() < total * EARLIEST_FINAL_FRACTION
        if not too_early and s.set_phase(ids[target]):
            reveal = s.reveal_for_phase(ids[target])
    # Backwards moves are ignored: the interview never returns to an earlier phase.

    if d.get("gave_hint") and s.kind == "coding" and s.phase["id"] in ("problem", "follow_up"):
        hints = s.plan.get("problem", {}).get("hints", [])
        if s.hints_used < len(hints):
            s.hints_used += 1
            s.log("event", f"Hint {s.hints_used} given")

    ended = False
    wants_end = bool(d.get("end_interview"))
    late = s.now() >= total - 120 or event == "time_up"
    if wants_end and (s.phase["id"] == ids[-1] or late):
        ended = True
        s.end_reason = "interviewer wrapped up"
    if s.now() >= total + HARD_STOP_GRACE_S or s.turns >= MAX_TURNS:
        ended = True
        s.end_reason = s.end_reason or "time ran out"

    say = clean_say(d["say"])
    s.log("interviewer", say)
    return {"say": say, "reveal": reveal, "ended": ended}


# --- caching the brief -----------------------------------------------------
# The brief (persona, rules, full plan) is ~4k tokens and identical on every
# turn. Stored once in a Google-side cache, it's billed at a tenth of the
# input price on each turn after that. It pays for itself after ~2 turns.
CACHE_GRACE_MIN = 20


def ensure_cache(s: InterviewSession) -> None:
    if s.cache_name or s.cache_failed:
        return
    model = config.INTERVIEWER_MODELS[0]
    ttl = (s.minutes + CACHE_GRACE_MIN) * 60
    try:
        cache = models.client(20, "v1beta").caches.create(
            model=model,
            config=types.CreateCachedContentConfig(
                system_instruction=brief(s), ttl=f"{ttl}s", display_name=f"speakwell-{s.id}"),
        )
    except Exception:  # noqa: BLE001 - caching is an optimization, never required
        log.warning("Could not cache the interviewer brief; sending it each turn", exc_info=True)
        s.cache_failed = True
        return
    s.cache_name, s.cache_model = cache.name, model
    tokens = getattr(cache.usage_metadata, "total_token_count", None) or 4000
    s.meter.add_usd(model, cache_cost_usd(model, tokens, ttl / 3600))


def release_cache(s: InterviewSession) -> None:
    """Delete the cache as soon as the interview ends (it would expire anyway)."""
    if not s.cache_name:
        return
    name, s.cache_name = s.cache_name, ""
    s.cache_failed = True  # don't recreate it for a late call
    try:
        models.client(20, "v1beta").caches.delete(name=name)
    except Exception:  # noqa: BLE001
        log.warning("Could not delete interviewer cache %s; it will expire on its own", name)


def respond(s: InterviewSession, answer_s: float = 0.0, auto_stopped: bool = False, event: str = "") -> dict:
    """Ask the model for the interviewer's next line and apply it."""
    s.turns += 1
    contents = [
        "CONVERSATION SO FAR:\n" + conversation_text(s),
        state_text(s, answer_s, auto_stopped, event),
    ]
    fast = s.phase["id"] in config.FAST_PHASES
    chain = config.INTERVIEWER_FAST_MODELS if fast else config.INTERVIEWER_MODELS
    if not fast:
        ensure_cache(s)
    caches = {s.cache_model: s.cache_name} if s.cache_name else None
    try:
        result = models.generate_json(
            chain, contents, reply_schema(s),
            timeout_s=config.INTERVIEWER_TIMEOUT_S, meter=s.meter, validate=_validator(s),
            thinking=config.INTERVIEWER_THINKING, task="interviewer reply",
            system_instruction=brief(s), cached_content=caches,
        )
    except models.ModelError:
        if not caches:
            raise
        # A broken or expired cache shouldn't stall the interview: retry without it.
        s.cache_name, s.cache_failed = "", True
        result = models.generate_json(
            chain, contents, reply_schema(s),
            timeout_s=config.INTERVIEWER_TIMEOUT_S, meter=s.meter, validate=_validator(s),
            thinking=config.INTERVIEWER_THINKING, task="interviewer reply", system_instruction=brief(s),
        )
    out = apply_reply(s, result.data, event)
    if out["ended"]:
        release_cache(s)
    return out


def _mmss(seconds: float) -> str:
    seconds = max(0, int(seconds))
    return f"{seconds // 60:02d}:{seconds % 60:02d}"
