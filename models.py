"""One place that calls Gemini text/audio models, with fallback across a chain.

Every call goes through `generate_json`, which tries each model in a chain
until one returns valid JSON. Busy (503), over-quota (429), timed-out and
unsupported-model errors move on to the next model. A rejected API key stops
immediately, because no other model will accept it either.
"""
import functools
import json
import logging
import time
from dataclasses import dataclass, field

from google import genai
from google.genai import errors, types

import config
from pricing import CostMeter

log = logging.getLogger(__name__)


class ModelError(RuntimeError):
    """A failure whose message is safe and useful to show the user."""


@dataclass
class Attempt:
    model: str
    outcome: str  # "ok" or a short reason


@dataclass
class Result:
    data: dict
    model: str
    attempts: list[Attempt] = field(default_factory=list)


@functools.lru_cache(maxsize=8)
def _client(api_key: str, timeout_s: int, api_version: str = "") -> genai.Client:
    # Cached: each Client owns a connection pool, so one per request would throw
    # away kept-alive connections.
    opts = {"timeout": timeout_s * 1000}
    if api_version:
        opts["api_version"] = api_version
    return genai.Client(api_key=api_key, http_options=types.HttpOptions(**opts))


def client(timeout_s: int, api_version: str = "") -> genai.Client:
    return _client(config.get_api_key(), timeout_s, api_version)


def describe_error(exc: Exception) -> tuple[str, bool]:
    """Return (short reason, worth trying another model?)."""
    if isinstance(exc, errors.APIError):
        code = getattr(exc, "code", None)
        if code in (401, 403):
            return "API key rejected", False
        if code == 429:
            return "over quota", True
        if code in (500, 502, 503, 504):
            return "busy", True
        if code in (400, 404):
            return "not available for this request", True
        return f"error {code}", True
    name = type(exc).__name__.lower()
    if "timeout" in name or "timedout" in name:
        return "timed out", True
    if isinstance(exc, ModelError):
        return str(exc), True
    return "unexpected error", True


def parse_json(text: str | None) -> dict:
    """Parse a JSON object, tolerating a markdown fence around it."""
    if not text:
        raise ModelError("empty response")
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = cleaned.split("\n", 1)[1] if "\n" in cleaned else ""
        cleaned = cleaned.rsplit("```", 1)[0]
    try:
        data = json.loads(cleaned)
    except (json.JSONDecodeError, ValueError) as exc:
        raise ModelError("response was not valid JSON") from exc
    if not isinstance(data, dict):
        raise ModelError("response was not a JSON object")
    return data


def generate_json(
    chain: list[str],
    contents: list,
    schema: dict,
    *,
    timeout_s: int,
    meter: CostMeter | None = None,
    validate=None,
    thinking: str | None = None,
    task: str = "request",
    system_instruction: str | None = None,
    cached_content: dict[str, str] | None = None,
) -> Result:
    """Try each model in `chain` until one returns JSON that passes `validate`.

    `validate(data)` may raise ModelError to reject a response; the next model
    is then tried. `thinking` ("low" / "medium" / "high") is passed only to
    models that accept it, and dropped on retry if a model refuses it.
    """
    attempts: list[Attempt] = []
    for model in chain:
        started = time.monotonic()
        try:
            cfg = dict(response_mime_type="application/json", response_json_schema=schema)
            api_version = ""
            cache = (cached_content or {}).get(model)
            if cache:
                # The system instruction lives inside the cache; Google rejects both.
                cfg["cached_content"] = cache
                api_version = "v1beta"
            elif system_instruction:
                cfg["system_instruction"] = system_instruction
            if thinking:
                cfg["thinking_config"] = types.ThinkingConfig(thinking_level=thinking)
            try:
                response = client(timeout_s, api_version).models.generate_content(
                    model=model, contents=contents, config=types.GenerateContentConfig(**cfg)
                )
            except errors.APIError as exc:
                if thinking and getattr(exc, "code", None) == 400:
                    cfg.pop("thinking_config", None)  # model doesn't take a thinking level
                    response = client(timeout_s, api_version).models.generate_content(
                        model=model, contents=contents, config=types.GenerateContentConfig(**cfg)
                    )
                else:
                    raise
            if meter is not None:
                meter.add(model, getattr(response, "usage_metadata", None))
            data = parse_json(response.text)
            if validate is not None:
                validate(data)
            attempts.append(Attempt(model, "ok"))
            log.info("%s: %s answered in %.1fs", task, model, time.monotonic() - started)
            return Result(data, model, attempts)
        except Exception as exc:  # noqa: BLE001 - every failure is classified below
            reason, retryable = describe_error(exc)
            attempts.append(Attempt(model, reason))
            log.warning("%s: %s failed after %.1fs (%s): %s",
                        task, model, time.monotonic() - started, reason, exc)
            if not retryable:
                raise ModelError(
                    "Google rejected the API key. Check GEMINI_API_KEY in your .env file."
                ) from exc
    summary = "; ".join(f"{a.model}: {a.outcome}" for a in attempts)
    raise ModelError(f"Every model failed for the {task} ({summary}). Try again in a minute.")
