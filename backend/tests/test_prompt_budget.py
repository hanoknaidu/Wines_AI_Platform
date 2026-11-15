"""Regression: the generator's worst-case fan-out must fit under the turn ceiling.

The ledger pre-checks `max_tokens` priced as output. With LEAD_IN and CARD_REASON at
2048 tokens on Sonnet, a 3-card turn priced at ~$0.06 against a $0.05 ceiling, so every
card reason silently fell back to templated copy (`card_reasons_over_budget`).
"""

from wines_ai.config import Settings
from wines_ai.orchestrator.prompts import CARD_REASON, LEAD_IN
from wines_ai.pricing import cost_usd

MAX_CARDS = 5
ROW = {
    "variety": "Pinot Noir", "style": "red", "sweetness": "dry", "body": "light",
    "description": "Red cherry and rose, delicate and silky, with very little grip.",
}


def _worst(prompt, model):
    req = prompt.build(model, {"kind": prompt.id, "row": ROW, "utterance": "a light red",
                               "fallback": "x" * 200})
    return cost_usd(model, tokens_in=req.prompt_tokens(), tokens_out=req.max_tokens)


def test_card_reason_fan_out_fits_turn_ceiling():
    s = Settings()
    model = s.model_generator
    # Headroom for router + rewriter + verifier, which run before the fan-out.
    spent_before = 0.005
    worst = _worst(LEAD_IN, model) + MAX_CARDS * _worst(CARD_REASON, model)
    assert spent_before + worst < s.cost_ceiling_per_turn_usd, (
        f"worst-case generator spend ${worst:.4f} exceeds the turn ceiling "
        f"${s.cost_ceiling_per_turn_usd}; card reasons would always degrade to templates"
    )
