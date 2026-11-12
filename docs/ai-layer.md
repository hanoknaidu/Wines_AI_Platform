# The AI layer, and how it is wired to the backend

What this covers: the orchestrator, the four workflows, the A→K pipeline, the model
gateway, and the seam where a turn sent to the turns API becomes a graph run. Written
after building it, so every claim here is a statement about code rather than a plan.

The one-line version: **`WA_ENGINE=orchestrated` is the whole switch.** No route, no
schema, no SSE frame and no line of frontend code changed. The frontend's
real-backend suite — written months earlier against the deterministic engine, including
the stream-drop-and-resume test — passes unchanged against the orchestrated one.

---

## 1. The request path

```
POST /api/v1/conversations/{cid}/messages          api/v1/turns.py
  │   idempotency · one-in-flight check · user message + parts persisted
  │   TurnRequest assembled from the stored profile, transcript and previous row ids
  ▼
TurnRunner.run()                                    services/runner.py
  │   cost guard picks the engine · turn cache consulted
  ▼
OrchestratedEngine.run()                            turns/orchestrated.py
  │   GraphState + TurnLedger built for this turn
  ▼
graph.run()                                         orchestrator/graph.py
  │
  ├─ node: route           orchestrator/router.py        Haiku via LangChain + a keyword floor
  ├─ node: slot_merge      (profile patch, emitted)
  └─ node: dispatch ──┬─ interview   workflows/interview.py
                      ├─ ask         workflows/ask.py        ← stages A→K
                      ├─ refine      workflows/refine.py
                      └─ safety      workflows/safety.py
  │
  │   each yields the same TurnEvent protocol lane 2 defined
  ▼
TurnRunner, again
      grounding guard rebuilds every row-owned field from the dataset
      seq allocated · message_part rows written · SSE frames published
      one transaction_log row · retrieval_log per stage · graph_checkpoint per node
  ▼
GET /api/v1/conversations/{cid}/stream?after={seq}
```

Nothing in `orchestrator/` touches the database, the bus, or a route. It yields events;
the runner does everything else. That is why the switch is free.

### The ask workflow, stage by stage

| | Stage | Where | Model? |
|---|---|---|---|
| A | Query rewrite — resolve ellipsis and coreference | `pipeline/query.py` | Haiku |
| B | Decompose a two-part ask into sub-queries | `pipeline/query.py` | Haiku, **skipped unless the utterance contains a coordinating "and"** |
| C | Consumer → sommelier vocabulary, plus HyDE | `pipeline/query.py` | no — a lookup table and a template |
| D | Retrieval planner: hard filter, sweetness band, soft weights, k per arm | `pipeline/retrieve.py` | no |
| E1/E2/E3 | Dense · BM25 · structured axis scan, run concurrently | `pipeline/retrieve.py` | no |
| F | Reciprocal Rank Fusion, k=60, deduped by row_id | `pipeline/retrieve.py` | no |
| G | Joint (query, candidate) rerank | `pipeline/rerank.py` | no — see §3 |
| — | **The abstention gate (FR-13)** | `workflows/ask.py` `_gate` | no |
| H | MMR across grape variety, merging sub-query groups | `pipeline/rerank.py` | no |
| I | Context packer: token budget, near-duplicate collapse, fixed field set | `pipeline/pack.py` | no |
| J | Grounded generator: lead-in (streamed) + one reason per card | `workflows/ask.py` | Sonnet |
| K | Verifier + eval tap | `pipeline/verify.py` | Haiku |

Three model roles on Haiku, one on Sonnet — the tiering the architecture specifies, with
the highest call volume on the cheapest tier and the expensive model only ever writing
prose.

---

## 2. Two providers, and why the default one is not a mock

`WA_LLM_PROVIDER` selects what the gateway calls:

- **`offline`** (the default). Everything in the pipeline that is actually hard —
  rewriting against conversation state, hybrid retrieval, rank fusion, reranking, MMR,
  budgeted packing, groundedness verification — is ordinary code over real data, and it
  all runs. The only parts that genuinely need a model are three natural-language
  *judgements*: which intent, which paraphrase, which sentence. This provider answers
  those from structure: a structured call is handled by the deterministic equivalent its
  schema names, and a prose call is answered from the packed context — the one source
  the real generator is also restricted to.

  The consequence: the orchestrated engine runs end to end on an **empty environment**,
  writing the same traces and checkpoints and emitting the same SSE frames, at $0.00,
  with NFR-4 (no credentials) intact.

- **`anthropic`**. The real models. Needs `uv sync --extra orchestrator` and
  `WA_ANTHROPIC_API_KEY`. Asking for it without either **logs the reason and falls back
  to `offline`** rather than failing to boot — right for a demo, wrong for a deployment
  that meant to call the models, so `WA_REQUIRE_LLM_PROVIDER=true` makes the same
  situation fail `/readyz` instead. `/readyz` always reports both the requested and the
  live provider, so the downgrade is never silent: serving templated copy in production
  is a misconfiguration wearing a working service as a disguise, visible only in the
  bill that never arrives.

Both paths have now been run. Switching providers changes the quality of three
sentences, not the shape of anything —
and because a different provider means a different answer, the provider name is part of
the turn cache key, so flipping it cannot serve yesterday's prose.

---

## 3. Where this is weaker than the diagram, stated plainly

Three stages are honest substitutions. Each is behind a protocol, each file names what
it gives up, and none of them is hidden behind a hopeful variable name.

| Diagram | Built | Gives up | Swap cost |
|---|---|---|---|
| 384-d bi-encoder (E1) | Hashed character-n-gram embedder, `retrieval/embed.py` | Taste-adjacency between unrelated words ("jammy" ≈ "fruit-forward"). Catches paraphrase and morphology, because the n-grams overlap | One class behind `Embedder`. **Stage C's vocabulary expansion is what covers the gap, which is why it is not optional here** |
| SQLite FTS5 (E2) | Okapi BM25 in-process, `retrieval/bm25.py` | Nothing in ranking — same function, k1=1.5, b=0.75. Would matter at a corpus size where an in-memory index does not fit | Replace `search()` |
| Cross-encoder (G) | Joint feature scorer, `pipeline/rerank.py` | The semantic judgement a trained model makes about whether a note answers a question. Keeps the part that matters structurally: the score is a function of the **pair**, so it uses evidence a bi-encoder cannot — which query terms this row contains, whether its variety was named, how far its axes are from what was asked | Same function signature |

The reason is the same in all three cases: a real bi-encoder and a real cross-encoder
mean `torch` plus `sentence-transformers`, roughly 2 GB of wheels, to serve 45 rows that
a brute-force scan reads in under a millisecond. That trade is wrong at this corpus
size, and the eval tap (§5) is how anyone would know it has become right.

LangGraph was declared in the `orchestrator` extra and has been **dropped**. What it
brings is a graph DSL, a checkpointer and conditional-edge routing; the checkpointer is
`graph_checkpoint`, which lane 2 has written since the start, and the routing is a
four-way dispatch on one field. `orchestrator/graph.py` is the same machine with the
same checkpoints in ~40 lines, with nodes named and recorded. A cycle, a join, or
human-in-the-loop interrupts is the point at which the dependency earns itself back.

---

## 4. What the integration changed outside `orchestrator/`

Six things, all of them defects or gaps that lane 2 could not expose.

1. **The runner buffered the entire engine stream before publishing anything.**
   `services/runner.py` drained `engine.run()` into a list, then iterated it. Invisible
   with a sub-10 ms deterministic engine; fatal for a streamed generator, where it would
   have meant the client's cursor, Stop button and `?after=` resume all had nothing to
   work with until the answer was already complete. Now one async iterator, consumed as
   it arrives, recorded for the cache as it goes. Regression test:
   `test_tokens_reach_a_subscriber_while_the_engine_is_still_running`.

2. **`cost_ceiling_per_turn_usd` was a number nothing read.** The per-turn ceiling is
   now enforced by `TurnLedger`, checked before each call *and* as streamed output
   accrues — so a runaway generator is stopped mid-stream rather than reported
   afterwards. The partial text already streamed is kept: retracting text a user has
   read is worse than a short answer.

3. **A multi-model turn was priced off one model id.** `Usage.cost_usd` was added so an
   engine that spent across four models reports its own total; the runner prices a
   single-model turn from `model` as before.

4. **`retrieval_eval` had no writer**, which meant the retrieval side could not be
   measured at all. `pipeline/verify.py` now has the eval tap, and `recall@k` / `nDCG@10`
   are **NULL until a labelled relevant set exists** — an unmeasured metric must not be
   able to masquerade as a measured one.

5. **Prompt injection was not in the lexical safety table.** The safety workflow's claim
   that "a prompt-injection attempt never reaches the retriever" was only true if the
   router happened to classify it as out-of-scope. It is now an `injection` topic in
   `turns/intent.py`, matched lexically and first — so the utterance is never rewritten,
   never embedded, never packed. The one topic where asking the classifier to judge *is*
   the attack cannot be left to the classifier.

6. **Sonnet 5.5's cache-read rate was wrong** in `pricing.py` ($0.20 against the actual
   $0.10), and a refine turn was labelled `recommend` in `transaction_log.intent` by both
   engines. The label rule is now explicit and shared: an interview turn that ends up
   serving cards is a `recommend` (the user got cards), a refine turn stays a `refine`
   (the defining action is the one-axis delta). Mislabelling either corrupts the intent
   eval set, which is the one thing in this lane that cannot be recomputed later.

### Found only by running it against the live API

The whole lane was built and tested against the offline provider, and the first real
turn exposed four things no test had any way to see. Recording them because the shape
of the lesson repeats: **every one of them looked like success everywhere except the
per-call gateway trace.**

7. **Thinking is on by default, and it spends `max_tokens`.** Every current model runs
   adaptive thinking unless told otherwise, and thinking tokens come out of the same
   output budget as the answer. With `max_tokens: 200` on the card-reason prompt, the
   model spent all 200 thinking and returned **no text block at all** — so four of five
   cards silently used their templated fallback, and the verifier's JSON was truncated
   into an unparseable response that fell back to the structural check. The turn
   reported `status: ok`, `degraded: false`, nine successful calls and a plausible bill.
   Fixed by turning thinking off for these calls — which is model-specific and not
   uniform: Haiku 5.5 takes `{"type": "disabled"}`, Sonnet 5.5 **400s** on that and
   wants `{"type": "between_tools"}` — plus headroom on every `max_tokens` (a cap is
   not a charge). A cap hit before any text is now an ERROR log, not a quiet fallback.

8. **A cache read with no rate in the table was billed at $0.00.** A Haiku router call
   reported **1,580 cache-read tokens against 59 fresh** — the prefix ordering works,
   and 96% of that prompt was cached — but `RATES["claude-haiku-5-5"].cache_read` was
   `None`, so `cost_usd` skipped all of it. Cache *writes* were not read from the
   response at all, and the first turn is the one that writes the cache. Both are now
   priced; an unrated cache read is charged at the **full input rate**, deliberately
   pessimistic, because a ceiling that can under-report is not a ceiling.

9. **The usage frame named Sonnet on a turn that called no model.** A chip-answered
   interview turn makes zero model calls; reporting the configured generator against 0
   tokens and $0.00 invites exactly the wrong conclusion about where the money goes. It
   now reports the model that did the most expensive work, or `none`.

10. **The five card-reason calls ran sequentially** — 7.7s of a 14.1s turn, against an
    architecture whose own amendment puts p95 at 2–4s. They are independent calls over
    disjoint rows and nothing is streamed from them, so they now fan out: **14.1s →
    7.0s** for identical output. The fan-out is priced against the ledger as a group
    before it launches, because each call's own pre-check reads the ledger before its
    siblings have recorded anything — a ceiling that holds only when requests are
    serialised is not a ceiling.

Two further defects were found only by reading an actual SSE response, which is worth
recording as a method note:

- `why_it_matches` arrived as the literal string `{}` on every card. The offline
  provider dispatched on its schema handlers and fell through to `json.dumps({})` for
  any call without a schema — which is every non-streaming prose call, and the card
  reason is one of those per card. 180 passing tests did not look at the text.
- MMR served **two Chardonnays** when the query named Chardonnay: relevance beat the
  diversity penalty. Defensible in isolation — oaked and unoaked Chardonnay are
  different wines — but `taste/diversify.py` caps lane 2 at one row per variety, so the
  two engines would have answered the same question differently on FR-7 with no setting
  that said so. The cap is now hard while unused varieties remain, and relaxes only to
  reach `results_min`, exactly as lane 2 does.

---

## 5. What is observable about a turn

| Where | What |
|---|---|
| `transaction_log` | one row per turn: intent, confidence, model, engine, tokens, cost, latency, status, cache hit |
| `retrieval_log` | one row per stage: `rewrite`, `retrieve.{dense,sparse,structured}`, `fuse.{group}`, `anchor`, `rerank`, `diversify` — with candidate ids, ranks and scores |
| `graph_checkpoint` | one row per node: `intent_router`, `rewrite`, `decompose`, `plan.{group}`, `diversify`, `pack`, `verify`, `empty_state`, `complete` |
| `intent_eval` | every utterance with the predicted intent and confidence — the confusion matrix's raw material, with the keyword router as the baseline |
| `usage` SSE frame | plus `degraded_reason`, a stable code the client maps to copy |
| `GET /readyz` | `serving`: the provider, the four model ids, and the loaded retrieval indexes. Readiness has to answer "ready to serve *what*" |
| structured log | one `turn_complete` line per turn carrying the per-call gateway trace: prompt id and version, model, tokens, cost, latency, per call |

A degradation is never silent. `degraded_reason` distinguishes `cost_ceiling`,
`turn_budget`, `generator_unavailable` and `verify_repair`, and the client renders the
matching sentence. An **abstention is deliberately not a degradation** — FR-13 requires
it, so it is reported through the empty-state copy and the checkpoint, and raises no
notice.

---

## 6. Degradation ladder

Every model call in the ask workflow has a non-model answer, so the failure modes
compose rather than cascade:

| Fails | Result |
|---|---|
| Router | Keyword router answers; every turn is routable without a model |
| Rewriter | Profile-derived HyDE query — worse, but it retrieves |
| Decompose | Treated as a single-intent turn |
| Generator (stream) | Templated lead-in from the profile, **only if nothing was streamed** |
| Generator (card reason) | `copytext.why_it_matches` from the row and the axis distances |
| Verifier | Structural check: a claim whose row id was not packed is unsupported by construction |
| Verifier says unsupported | That card's prose is replaced with copy drawn from the row — the card survives, the sentence does not |
| Per-turn budget | Stopped mid-stream, partial text kept, rest templated |
| Provider down (breaker open) | Fails fast; the turn completes on templated copy at $0.00 |
| Session or daily ceiling | Cost guard degrades the whole turn to the deterministic engine |

A turn in which the gateway is down, the budget is spent and the provider refuses still
produces the same cards, with flatter prose. That is the difference between a cost
control and an outage.

---

## 7. Running it

```bash
# the orchestrated engine, no key, no network
cd backend
WA_ENGINE=orchestrated \
WA_RATE_LIMIT_READS_PER_MIN=2000 WA_RATE_LIMIT_TURNS_PER_MIN=500 \
  .venv/bin/python -m uvicorn wines_ai.main:app --port 8011

# with the real models
uv sync --extra orchestrator
WA_ENGINE=orchestrated WA_LLM_PROVIDER=anthropic WA_ANTHROPIC_API_KEY=sk-... \
  .venv/bin/python -m uvicorn wines_ai.main:app --port 8011

# the frontend against either
cd frontend
VITE_USE_MOCKS=false VITE_BACKEND_ORIGIN=http://127.0.0.1:8011 npm run dev

# the frontend's real-backend suite against the orchestrated engine
WA_REAL_BACKEND=1 WA_BACKEND=http://127.0.0.1:8011 npx vitest run src/app/App.real.test.tsx
```

---

## 7a. The router on LangChain (2026-11-11)

The router's Haiku call is now made through LangChain
(`orchestrator/gateway/langchain_router.py`), with `orchestrator/intent_prompt.md` as
the route prompt, `route@2`. The other calls (rewrite, generator, card reason,
verifier) still use the Anthropic SDK provider.

- **Inside the gateway, not beside it.** `ModelGateway.complete_route()` runs the
  LangChain call under the same pre-call ceiling check, bounded retry, timeout, shared
  circuit breaker and cost record as every other call. LangChain's own retries are off
  (`max_retries=0`) so every failure reaches the breaker.
- **Offline is unchanged.** `build_router()` returns a router only when the live
  provider is `anthropic`; offline deployments route exactly as before, and a missing
  `langchain-anthropic` falls back to the SDK path with a logged warning.
- **Tokens are priced once.** LangChain's `input_tokens` already includes cache
  reads and writes; `_usage()` subtracts them before the gateway prices each count.
- **`reasoning` comes before `intent` in the tool schema.** With thinking off, field
  order is decision order: with `intent` first, the dessert-completion case answered
  `interview` 5/5 under reasoning that concluded "sufficient". Reasoning-first: 10/10.
- **Measured:** the 31-case harness suite through `route()` with the live gateway,
  28/28 on two runs; one live HTTP turn routed `recommend` (source `model`), 5 cards,
  `route@2` at $0.00065 and 1.5 s with 4,955 of 5,220 input tokens read from cache.
- `langchain-anthropic` is in the `orchestrator` extra beside `anthropic`; the base
  install is unchanged.

## 8. Verified

| | |
|---|---|
| Backend | **190 passed**, ruff clean (was 128 before this work) |
| Frontend | **62 passed**, `tsc -b` clean, eslint clean |
| Real-backend suite vs. **orchestrated** (offline) | **5/5**, including stream-drop-and-resume |
| Live `/readyz`, offline | `provider: offline`, four model ids, 45 rows indexed, 336 BM25 terms, build 3 ms |
| Live turn, offline, read frame by frame | 5 cards, 5 distinct varieties, real prose, honest hedging, `cost_usd: 0.0`, 27 ms |
| **Live turn, `anthropic`** | 5 cards, 5 distinct varieties, model-written prose with row-id citations and honest near-miss hedging ("you also said smooth, and this one is grippy"), 9 calls, **$0.0092**, **7.0 s** |
| Live prompt caching | **engaged**: 1,580 cache-read tokens against 59 fresh on the router prefix; 651 read on four of five card calls |
| Live cost accounting | per-call trace with tokens in/out, cache read/write, cost and latency per prompt version |

## 9. Not done

- **The `anthropic` path has now run** (interview, ask and the full A→K pipeline), and
  the four defects in §4 came out of it. What it has *not* done is run under load, or
  long enough to see a refusal, a rate limit, a mid-stream budget cut or an open circuit
  breaker in production rather than in a test. Those paths are still contract-and-test
  only.
- **The refine workflow has not been run on live models.** It delegates to the same ask
  workflow with an anchored candidate set, and it is covered against the offline
  provider, so the untested part is only the prose.
- **The frontend's real-backend suite has not been run against live models**, only
  against the offline provider. It would cost roughly ten turns of real spend; nothing
  about it is known to be provider-dependent.
- **No prompt eval sets.** The registry versions each prompt and the eval tap collects
  the data a gold set would be built from, but there is no "a prompt change that
  regresses its eval set does not ship" gate yet, because there is no eval set.
- **recall@k / nDCG@10 are NULL.** They need ~200 labelled queries. The functions are
  written and tested; nothing is labelled.
- **Band 4 is still not built.** The seed artifact stands in, and `example_producers` is
  empty for every seed row — which is why FR-11's caveat copy matters more than it looks.
- **No browser pass on the orchestrated engine.** The jsdom suites pass; nothing has been
  looked at with a real streamed generator, which is the case where the cursor and the
  no-layout-shift guarantees actually get tested. Carried over from
  [integration-TODO.md §5](integration-TODO.md).
