"""A provider that answers from the prompt alone: no key, no network, no spend.

This is not a mock, and it is the reason the orchestrated engine is shippable today.

Everything the A-to-K pipeline does that is actually hard - rewriting against
conversation state, hybrid retrieval, rank fusion, cross-encoder reranking, MMR
across variety, token-budgeted packing, groundedness verification - is ordinary code
running on real data. The only parts that genuinely need a model are the natural
language *judgements*: which intent, which paraphrase, which sentence. This provider
answers those from structure instead:

* a structured call is answered by the deterministic equivalent the schema names, so
  the router and the slot extractor return the same shape a Haiku call would;
* a prose call is answered from the packed context the prompt carries, which is the
  one source the real generator is also allowed to use.

The consequence is worth stating plainly: with `llm_provider=offline` the orchestrated
engine runs the complete pipeline, writes the same traces and checkpoints, and emits
the same SSE frames - at $0.00 and with NFR-4 (no credentials) still true. Swapping in
`anthropic` changes the quality of three sentences, not the shape of anything.

It also doubles as the fallback that keeps the product working when the real provider
is down, which is why `degraded` is set on the result rather than inferred by callers.
"""

from __future__ import annotations

import json
import re
from collections.abc import AsyncIterator

from .types import ModelDelta, ModelRequest, ModelResult, estimate_tokens


def _joined(req: ModelRequest) -> str:
    return "\n".join(b.text for b in (*req.system, *req.user))


def _payload(req: ModelRequest) -> dict:
    """The per-turn JSON block the prompt registry appends to every call.

    The registry hands structured input as one fenced JSON block labelled
    `turn_payload`, so this provider reads its inputs rather than parsing prose. A
    prompt that forgets the block gets an empty dict and the caller's own fallback.
    """
    for block in reversed(req.user):
        if block.label == "turn_payload":
            try:
                return json.loads(block.text)
            except json.JSONDecodeError:
                return {}
    return {}


class OfflineProvider:
    name = "offline"

    async def complete(self, req: ModelRequest) -> ModelResult:
        """A structured call is answered by its schema's handler; a prose call is not.

        `req.schema is None` is the whole test, and it has to be: not every prose
        call streams. The card reason is one non-streaming prose call per card, and
        answering it with the JSON a structured handler returns put the literal text
        `{}` into `why_it_matches` on every card - visible only by reading an actual
        response, which is why `_prose` is reached from both entry points now.
        """
        payload = _payload(req)
        if req.schema is None:
            text = self._prose(req)
            return ModelResult(
                model=req.model,
                text=text,
                tokens_in=req.prompt_tokens(),
                tokens_out=estimate_tokens(text),
                degraded=True,
            )

        handler = _STRUCTURED.get(req.schema.get("name", ""))
        structured = handler(payload) if handler else {}
        text = json.dumps(structured)
        return ModelResult(
            model=req.model,
            text=text,
            structured=structured,
            tokens_in=req.prompt_tokens(),
            tokens_out=estimate_tokens(text),
            degraded=True,
        )

    async def stream(self, req: ModelRequest) -> AsyncIterator[ModelDelta | ModelResult]:
        text = self._prose(req)
        produced = 0
        # Chunked on word boundaries so a client renders it the way it renders the
        # real generator: the transport must not be able to tell the two apart.
        for word in _words(text):
            produced += estimate_tokens(word)
            yield ModelDelta(text=word)
        yield ModelResult(
            model=req.model,
            text=text,
            tokens_in=req.prompt_tokens(),
            tokens_out=produced,
            degraded=True,
        )

    # --- prose -----------------------------------------------------------
    def _prose(self, req: ModelRequest) -> str:
        payload = _payload(req)
        kind = payload.get("kind", "")
        if kind == "lead_in":
            return _lead_in(payload)
        if kind == "card_reason":
            return payload.get("fallback") or ""
        if kind == "templated":
            return payload.get("text") or ""
        # Unknown prose call: say nothing rather than invent a sentence. An empty
        # string is a visible failure the verifier catches; a plausible sentence is not.
        return ""


def _words(text: str) -> list[str]:
    parts = re.split(r"(\s+)", text)
    out: list[str] = []
    for part in parts:
        if not part:
            continue
        if out and part.isspace():
            out[-1] = out[-1] + part
        else:
            out.append(part)
    return out


def _lead_in(payload: dict) -> str:
    count = int(payload.get("count") or 0)
    labels = [str(x) for x in (payload.get("profile_labels") or [])]
    tail = f": {', '.join(labels)}" if labels else ""
    return f"Here are {count} grape varieties worth looking for{tail}."


# --- structured answers --------------------------------------------------
# Each entry mirrors one prompt in the registry. The deterministic equivalent is the
# baseline the model is measured against, so these are the same functions the
# keyword lane uses rather than a second implementation of the same rules.


def _route(payload: dict) -> dict:
    from ...turns.intent import classify

    intent, confidence, topic = classify(
        payload.get("utterance", ""),
        payload.get("profile") or {},
        selected_chip_id=payload.get("selected_chip_id"),
        has_results=bool(payload.get("previous_row_ids")),
    )
    return {
        "intent": intent,
        "confidence": confidence,
        "out_of_scope_topic": topic,
        "slots": _slots(payload).get("slots", {}),
    }


def _slots(payload: dict) -> dict:
    from ...taste import interview

    chip = payload.get("selected_chip_id")
    if chip and (read := interview.read_chip(chip)):
        axis, value = read
        return {"slots": {axis: value}, "provenance": "asked"}
    return {"slots": interview.read_any(payload.get("utterance", "")), "provenance": "inferred"}


def _rewrite(payload: dict) -> dict:
    """Stage A without a model: resolve the obvious ellipsis from filled slots.

    Deliberately literal. A standalone query is assembled out of the profile the
    interview already collected plus the utterance's own content words, which is
    exactly the information the Haiku rewriter is given - it just phrases it better.
    """
    from ...taste.axes import AXES_BY_ID

    profile = payload.get("profile") or {}
    bits: list[str] = []
    for axis_id in ("sweetness", "body", "oak", "tannin", "acidity", "fruit_savoury"):
        value = profile.get(axis_id)
        axis = AXES_BY_ID.get(axis_id)
        if not value or axis is None:
            continue
        for level in axis.levels:
            if level.value == value:
                bits.append(level.label.lower())
                break
    style = profile.get("style")
    head = f"{style} wine" if style else "wine"
    utterance = (payload.get("utterance") or "").strip()
    query = ", ".join([head, *bits]) if bits else head
    if utterance and not _is_deictic(utterance):
        query = f"{query}; {utterance}"
    return {"query": query, "resolved": bool(bits)}


_DEICTIC = ("that", "those", "it", "them", "this", "these")


def _is_deictic(text: str) -> bool:
    """True when the utterance cannot stand on its own - the case stage A exists for."""
    words = re.findall(r"[a-z']+", text.lower())
    return bool(words) and len(words) <= 6 and any(w in _DEICTIC for w in words)


def _decompose(payload: dict) -> dict:
    """Stage B: split on a coordinating 'and' that joins two wine requests."""
    text = (payload.get("utterance") or "").strip()
    parts = re.split(r"\s+and\s+(?=something|a\s|an\s|then\s)", text, flags=re.IGNORECASE)
    parts = [p.strip() for p in parts if p.strip()]
    return {"sub_queries": parts[:2] if len(parts) > 1 else []}


def _verify(payload: dict) -> dict:
    """Stage K without a model: every claim must name a row id that was packed.

    The real verifier reads the prose. This one checks the structural property the
    prose is required to have, which is the half that can be checked exactly: a card
    whose row id was not in the packed context is unsourced by construction.
    """
    packed = {str(r) for r in (payload.get("packed_row_ids") or [])}
    claims = payload.get("claims") or []
    unsupported = [c for c in claims if str(c.get("row_id")) not in packed]
    return {
        "grounded": not unsupported,
        "unsupported_row_ids": [str(c.get("row_id")) for c in unsupported],
    }


_STRUCTURED = {
    "route": _route,
    "slots": _slots,
    "rewrite": _rewrite,
    "decompose": _decompose,
    "verify": _verify,
}
