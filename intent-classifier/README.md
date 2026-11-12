# Intent classifier — standalone

Routes one turn of a wine conversation to `interview`, `recommend`, `refine` or
`out_of_scope` using Claude Haiku 5.5 through LangChain.

Self-contained: no `wines_ai` package, no FastAPI, no database, no `uv`. A
virtualenv, one dependency, and an API key. Nothing here imports the backend and
nothing in the backend imports this.

## Setup

```bash
python3 -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt
```

Put your key in `.env` on the `ANTHROPIC_API_KEY=` line. Get one at
[console.claude.com/settings/keys](https://console.claude.com/settings/keys) — copy
it from the **creation dialog**, which is the only place the secret is shown. It
starts `sk-ant-`; a value starting `apikey_` is the key's ID, not the key.

API credits are a separate purchase from a Claude.ai subscription. If your key is
not scoped to a workspace, also set `ANTHROPIC_WORKSPACE_ID=wrkspc_…`.

## Use

```bash
python3 classify.py "red, nothing too sweet"
python3 classify.py "something lighter" --previous-results w_12,w_31
python3 classify.py "in the middle" --profile '{"style":"red","sweetness":"dry"}'
python3 classify.py --suite --verbose
python3 classify.py --show-prompt        # no key needed
```

The context flags matter more here than they look. **The same words are different
intents depending on state**: "something lighter" with results on screen is a
`refine`; the same sentence as an opening message is a statement about `body`, and
routes to `interview`. A suite run without context would be measuring a different
problem than the one the product has.

## Output

```
intent      refine
confidence  0.93
reasoning   Comparative on the body axis against a shown result set.
source      model
latency     1180ms
tokens      61 in (1580 cached), 48 out
```

`source` says how the answer was reached:

| `source` | Meaning |
|---|---|
| `lexical` | The safety table matched. The model was never called. |
| `model` | The model's answer, above the confidence floor. |
| `low_confidence` | Below 0.6, floored to `interview`. |
| `no_results` | The model said `refine` with nothing shown to refine against. |
| `empty_input` | Empty turn. |
| `error` | Network, auth or parse failure. |

## How it decides

The guide is [`intent_prompt.md`](intent_prompt.md) — plain Markdown. Edit it and
re-run `--suite` to see what changed. It is the deliverable; `classify.py` is
plumbing around it.

| Intent | Produces |
|---|---|
| `interview` | The next taste question |
| `recommend` | Five wine cards against a sufficient profile |
| `refine` | The same cards re-ranked with one axis moved |
| `out_of_scope` | A decline, naming the topic |

Four design points worth knowing.

**Safety is matched in code, before the model, and the match wins.** `safety_topic()`
runs first and short-circuits the call. Three reasons, none interchangeable: a
health claim is not a probabilistic question; the topics are defined by what the
dataset contains, which is known, so there is nothing to infer; and **prompt
injection is the one topic where asking the classifier to judge *is* the attack** —
an utterance whose purpose is to change the instructions must be refused before it
is embedded in a prompt at all. This mirrors the running router, deliberately.

**`interview` is the fallback for everything that goes wrong.** Of the four, it is
the only one that asserts nothing — it asks a question. `recommend` serves five
cards against a taste profile it claims to know, `out_of_scope` refuses a user who
may have asked something answerable, and `refine` re-ranks a set that may not
exist. So an empty turn, a low-confidence answer, a malformed answer and a network
failure all route to `interview`. "Hello" lands there at about 0.2.

**The model cannot answer off-menu.** `intent` is an enum in a tool schema and the
tool call is *forced* (`tool_choice: {type: tool}`, which Haiku 5.5 still accepts),
so an invalid value is impossible by construction rather than caught by validation
afterwards.

**A `refine` is demoted when nothing was shown.** The model cannot know what is on
screen; `previous_row_ids` does. This is a rule in code, not a hope about the
prompt.

## Two API facts this file depends on

Both are load-bearing and both differ from Haiku 4.5, so they are easy to get wrong
by copying older code:

- **`temperature` is rejected.** Haiku 5.5 returns a 400 on any non-default
  `temperature`, `top_p` or `top_k`. The usual `temperature=0` for a classifier is
  not available. Determinism comes from the forced tool call constraining the shape
  of the answer instead of the sampling.
- **Thinking is ON by default and it spends `max_tokens`.** Thinking tokens come
  out of the same output budget as the answer, so a short cap with thinking on can
  return no content block at all — which looks like success everywhere except the
  response body. This call sends `thinking={"type": "disabled"}` (accepted on Haiku
  5.5 at effort `high` or below) with `effort=low` and a cap of 1024.

## Cost

A suite run is ~30 calls on a ~1,900-token prompt. At Haiku 5.5's $0.10/$0.50 per
MTok that is well under a cent, and the run prints its own measured figure. The
guide is the whole system block and carries a cache breakpoint, so repeat runs
within the cache window read most of that prefix at a tenth of the price — check
the `cache_read` number to confirm it is actually engaging rather than assuming it.

## Relationship to the main project

**This prompt is the backend's route prompt.** The guide lives at
`backend/src/wines_ai/orchestrator/intent_prompt.md`; the backend loads it as
`route@2` and this harness reads the same file. There is one copy, so a change
measured here is the change that ships — no port, no drift.

The backend's router makes the same kind of call — Haiku through LangChain, forced
tool call, thinking off, no `temperature` — from
`backend/src/wines_ai/orchestrator/gateway/langchain_router.py`, but **inside the
model gateway**, so in the service it also counts toward the per-turn cost ceiling,
the circuit breaker and the per-call cost trace. Differences from this harness, all
intentional:

1. **The backend wraps the guide.** Its request puts the house rules and the axis
   vocabulary block ahead of the guide. The suite has been run both ways and agreed
   28/28 on each, but they are not byte-identical prompts.
2. **A keyword floor, not an `interview` floor.** Below 0.6 confidence the service
   uses `turns/intent.py`'s keyword answer; here it falls back to `interview`.
3. **Slots.** The service's call also extracts `style`/`sweetness`/`body`/`oak`
   (§6 of the guide). This harness's schema does not ask for them.
4. **Chips.** A tapped chip is answered in code before any model call.

**`OUT_OF_SCOPE_TOPICS` and the budget pattern are duplicated** from
`backend/src/wines_ai/turns/intent.py`, so this folder imports nothing. Keep them in step.

### The budget pattern

The shared table used to carry the literal `"under 20"`, so `"under 15"` or
`"up to 25"` slipped past the lexical lane and were left to the model — on the one
topic that is not supposed to be probabilistic. Both copies (this file and
`backend/src/wines_ai/turns/intent.py`) now also match a bare-number budget
(`under/below/up to/around/max N`, `N quid/dollars/euros`). A lookahead keeps taste
language out: `under 13%`, `about 10 years`, `around 6 people` and
`below 8 degrees` are not prices. The backend pins both halves in
`tests/test_safety_budget.py`.

## Verified

| | |
|---|---|
| Request payload | no `temperature`, `thinking: disabled`, `output_config.effort: low`, forced `tool_choice`, enum in the tool schema, `cache_control` on the system block |
| Lexical lane | all six topics match and short-circuit before any model call, including bare-number budgets; in-scope taste language (and `13%`, `10 years`, `6 people`) does not false-positive |
| Failure paths | empty turn, missing key and bad-prefix key all exit with a message rather than a traceback; a call failure routes to `interview` |
| **The model path** | **28/28 on two consecutive runs** (2026-11-11), all three no-workflow turns floored to `interview`. ~1.0 s per call, ~$0.012 per suite run, ~85K of ~180K input tokens served from cache. |
| Found by the live run | The prompt listed level ids (`full`) but not the button labels users type back ("Rich and bold"), so a completing answer was routed `interview`. The axis table now carries both. |
| Not yet measured | Run-to-run variance beyond two runs; anything outside the 31 hand-written cases. A suite this size shows the prompt is not broken, not that it is right — real transcripts are the next eval set. |
