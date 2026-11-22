"""Estimate what each Gemini call cost, from the token counts Google reports.

Prices are USD per 1M tokens from https://aistudio.google.com/docs/pricing
(checked 2026-11-20). Where Google has announced a price increase, the higher
price is used so estimates err on the expensive side. These are estimates for
the budget meter, not a bill: check https://aistudio.google.com/usage for that.
"""

# model -> {"in": text/other input, "audio_in": audio input, "out": text output,
#           "audio_out": audio output}
PRICES: dict[str, dict[str, float]] = {
    "gemini-4-argon": {"in": 4.00, "audio_in": 4.00, "out": 20.00, "cached": 0.20},
    "gemini-3.8-flash": {"in": 1.50, "audio_in": 1.50, "out": 7.50, "cached": 0.15, "storage_per_hour": 1.00},
    "gemini-3.5-flash-lite": {"in": 0.30, "audio_in": 0.30, "out": 2.50, "cached": 0.03, "storage_per_hour": 1.00},
    "gemini-3.5-transcribe": {"in": 2.00, "audio_in": 2.00, "out": 12.00},
    "gemini-3.8-live": {"in": 0.75, "audio_in": 3.00, "out": 4.50, "audio_out": 12.00},
    "gemini-3.1-flash-live-preview": {"in": 0.75, "audio_in": 3.00, "out": 4.50, "audio_out": 12.00},
}
# Unknown models are priced like the most expensive one we know, so a new model
# never silently reads as free.
_FALLBACK = {"in": 4.00, "audio_in": 4.00, "out": 20.00, "audio_out": 20.00}


def _modality(detail) -> str:
    mod = getattr(detail, "modality", None)
    name = getattr(mod, "name", None) or str(mod or "")
    return name.upper()


def _split(details, total: int | None) -> tuple[int, int]:
    """Return (audio_tokens, other_tokens) from a per-modality breakdown."""
    audio = sum(
        (getattr(d, "token_count", 0) or 0) for d in (details or []) if "AUDIO" in _modality(d)
    )
    total = total or 0
    return audio, max(total - audio, 0)


def cost_usd(model: str, usage) -> float:
    """Cost of one response's usage metadata. Missing data counts as zero."""
    if usage is None:
        return 0.0
    price = PRICES.get(model, _FALLBACK)
    in_audio, in_other = _split(
        getattr(usage, "prompt_tokens_details", None), getattr(usage, "prompt_token_count", None)
    )
    # Tokens served from Google's implicit cache are billed at the cache price.
    cached = min(getattr(usage, "cached_content_token_count", None) or 0, in_other)
    in_other -= cached
    out_total = (getattr(usage, "response_token_count", None) or getattr(usage, "candidates_token_count", None) or 0)
    out_total += getattr(usage, "thoughts_token_count", None) or 0
    out_details = getattr(usage, "response_tokens_details", None) or getattr(usage, "candidates_tokens_details", None)
    out_audio, out_other = _split(out_details, out_total)
    return (
        in_audio * price.get("audio_in", price["in"])
        + in_other * price["in"]
        + cached * price.get("cached", price["in"])
        + out_audio * price.get("audio_out", price["out"])
        + out_other * price["out"]
    ) / 1_000_000


def cache_cost_usd(model: str, tokens: int, hours: float) -> float:
    """Writing `tokens` into an explicit cache and storing them for `hours`.

    Writing is priced as normal input, which errs high."""
    price = PRICES.get(model, _FALLBACK)
    return tokens * (price["in"] + price.get("storage_per_hour", 1.0) * hours) / 1_000_000


class CostMeter:
    """Accumulates estimated spend per model for one interview."""

    def __init__(self) -> None:
        self.by_model: dict[str, float] = {}

    def add(self, model: str, usage) -> None:
        self.by_model[model] = self.by_model.get(model, 0.0) + cost_usd(model, usage)

    def add_usd(self, model: str, usd: float) -> None:
        self.by_model[model] = self.by_model.get(model, 0.0) + usd

    @property
    def total(self) -> float:
        return sum(self.by_model.values())

    def as_dict(self) -> dict:
        return {"total_usd": round(self.total, 4),
                "by_model": {k: round(v, 4) for k, v in self.by_model.items()}}
