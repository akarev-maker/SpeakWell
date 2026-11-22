from types import SimpleNamespace as NS

import pricing


def test_audio_and_text_priced_separately():
    usage = NS(prompt_token_count=1_000_000,
               prompt_tokens_details=[NS(modality=NS(name="AUDIO"), token_count=400_000)],
               response_token_count=100_000, thoughts_token_count=0,
               response_tokens_details=[NS(modality=NS(name="AUDIO"), token_count=100_000)])
    # live: 0.4M audio in * $3 + 0.6M text in * $0.75 + 0.1M audio out * $12
    assert round(pricing.cost_usd("gemini-3.8-live", usage), 4) == round(1.2 + 0.45 + 1.2, 4)


def test_unknown_model_is_never_free_and_none_is_zero():
    usage = NS(prompt_token_count=1_000_000, response_token_count=0)
    assert pricing.cost_usd("mystery-model", usage) > 0
    assert pricing.cost_usd("gemini-4-argon", None) == 0


def test_meter_totals():
    m = pricing.CostMeter()
    m.add_usd("a", 0.1)
    m.add_usd("a", 0.2)
    m.add_usd("b", 0.05)
    assert m.as_dict() == {"total_usd": 0.35, "by_model": {"a": 0.3, "b": 0.05}}
