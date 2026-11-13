# Wines AI — Backend

Lane 2 of `wines-ai-technical-architecture.excalidraw`: FastAPI, SQLite, the full
REST + SSE surface, persistence, and the frozen-dataset loader.

**It boots and works with no `ANTHROPIC_API_KEY`, no network, no orchestrator and no
frontend.** Confirm age, start a conversation, say what you like in plain words, and
you get streamed interview questions with option chips, then 3–5 recommendation cards
each citing the dataset row it came from. Every turn costs **$0.00**.

---

## Run it

```bash
cd backend
uv venv --python 3.12 && uv pip install -e ".[dev]"
mkdir -p var && uv run alembic upgrade head      # or let the app create the schema
uv run python -m wines_ai                        # http://127.0.0.1:8010
```

Then: `http://127.0.0.1:8010/docs` for the OpenAPI 3.1 surface.

```bash
curl -s localhost:8010/api/v1/readyz | jq        # dataset loaded?
curl -s -c j -X POST localhost:8010/api/v1/age-gate -d '{"confirmed":true}' -H 'content-type: application/json'
CID=$(curl -s -b j -c j -X POST localhost:8010/api/v1/conversations -d '{}' -H 'content-type: application/json' | jq -r .id)
curl -sN -b j "localhost:8010/api/v1/conversations/$CID/stream?after=0" &
curl -s -b j -X POST "localhost:8010/api/v1/conversations/$CID/messages" \
  -H 'content-type: application/json' -H "Idempotency-Key: $(uuidgen)" \
  -d '{"content":"a bold red, nothing too sweet"}'
```

Tests: `uv run pytest` (114 tests; the streaming ones start a real uvicorn process,
because httpx's `ASGITransport` buffers whole responses and cannot read an endless
stream). Lint: `uv run ruff check src tests`.

### Single worker, deliberately

The SSE bus, the in-flight turn registry and the seq allocator are in-process, and
SQLite takes one writer. **Run one worker.** Multi-worker needs Redis and buys nothing
at NFR-2's 20 concurrent sessions. This is a deployment constraint, written here rather
than left to be discovered.

---

## What is real and what is a seam

| | State |
|---|---|
| Routes, middleware, persistence, SSE, idempotency, cancellation, cost accounting | **built** |
| The recommender (interview → recommend → refine → out-of-scope) | **built**, deterministic, no model |
| The grounding guard | **built**, enforced at the engine boundary |
| Lane 3 — the orchestrator, the four workflows, the A→K pipeline | **built** (`orchestrator/`) |
| Lane 4 — model gateway, Anthropic client, prompt registry | **built** (`orchestrator/gateway/`, `prompts.py`) |
| Band 4 — offline authoring of the reviewed dataset | **not built**; `dataset/seed/` stands in |

`WA_ENGINE=deterministic | orchestrated` is the whole switch: the routes, the schemas,
the SSE frame set and the frontend do not know it was flipped. The frontend's
real-backend suite is written against the deterministic engine and passes unchanged
against the orchestrated one, stream-resume included.

### Two serving paths, both free by default

`WA_LLM_PROVIDER` decides what the orchestrated engine's gateway calls:

| | |
|---|---|
| `offline` (default) | Every stage runs — routing, hybrid retrieval, RRF, cross-pair rerank, MMR, token-budgeted packing, verification — and the three natural-language *judgements* are answered from structure instead of from a model. No key, no network, $0.00. A complete serving path, not a mock. |
| `anthropic` | The real models, behind one gateway: per-call timeout, bounded retry, circuit breaker, prompt caching, token accounting and a per-turn cost ceiling that refuses rather than reports. Needs `uv sync --extra orchestrator` and `WA_ANTHROPIC_API_KEY`; asking for it without either logs the reason and falls back to `offline` rather than failing to boot. |

Full map of the lane, and what each stage gives up relative to the diagram:
[docs/ai-layer.md](../docs/ai-layer.md).

### The Phase-1 engine is not a mock

It is **BRD v1.1's own serving path**: style hard filter → weighted distance across the
seven axes → diversify by grape variety → 3–5 rows → copy drawn from the row. So this
phase ships a working recommender at sub-10 ms per turn, and lane 3 later replaces
*how* the profile is built, not whether the app works.

---

## The dataset is honest about itself

`dataset/seed/wines.seed.json` — 45 rows, five styles, every sweetness level.

- `review_status` is `unreviewed` on **every** row, and `/api/v1/meta/dataset-version`
  says so. These rows have not been through band 4's human review.
- `example_producers` is **empty on every row**. Producer names are the weakest point
  in the system (BRD §8) and the one field a model confabulates; writing plausible ones
  into a fixture would commit exactly the failure this product exists to prevent, and
  it would look like real data the moment it rendered.

Swapping in the reviewed artifact is `WA_DATASET_PATH=/path/to/artifact.json` plus a
`dataset_version` bump. No code changes: the loader validates against the real schema
already, and refuses to boot `readyz` on a bad row.

---

## Cost

The default configuration spends nothing — `WA_LLM_PROVIDER=offline` runs the whole
pipeline without calling a model. Everything below bounds the spend *once a key is
set*, by construction rather than by hope.

| Lever | Where | Effect |
|---|---|---|
| **Model tiering** | `config.py` | Haiku 5.5 ($0.10/$0.50 per MTok) carries the router, rewriter and verifier — the highest call volume. Sonnet 5.5 ($2/$10) only ever writes the final copy |
| **Token budget** | `context_token_budget` = 8K | Also keeps Haiku prompts under its **100K tier break**, beyond which input costs 5× ($0.50/MTok) |
| **Cache-stable prefixes** | `orchestrator/prompts.py` | A Sonnet 5.5 cache read is $0.10/MTok against $2.00 fresh — 20×. Instructions first, per-turn payload last, and `ModelRequest.validate_cache_order()` **raises** if that ever inverts: a silently uncached prefix is a bug that only shows up on the bill |
| **Per-turn ceiling** | `gateway/gateway.py` `TurnLedger` | Checked before each call *and* as streamed output accrues, so a runaway generator is stopped mid-stream rather than after it has finished spending |
| **Circuit breaker** | `gateway/gateway.py` | A broken upstream fails fast instead of becoming a queue of 20-second timeouts, and the turn degrades to templated copy at $0.00 |
| **Skipped calls** | `pipeline/query.py` | Stage B is not called at all unless the utterance contains a coordinating "and"; a chip answer is never sent to the router. The cheapest call is the one not made |
| **Turn cache** | `turns/cost.py` | A repeated question against the same profile and dataset version replays for free. Keyed on content, so it is always safe |
| **Cost ceilings** | per-turn / per-session / global-daily | Exceeding one **degrades to the free engine**, never errors — a demo that stops working is worse than a demo that is cheap. Primed from `transaction_log` at boot so a restart does not reset it |
| **Idempotency** | required on every send | A retried send cannot pay twice |
| **One in-flight turn** | per conversation | A double-click cannot start a second paid turn |
| **Cancellation** | on cancel and on disconnect | An abandoned turn stops costing immediately |
| **Rate limit** | 30 turns/min per IP | A hard bound on how fast one client can run up a bill |
| **Batch API** | `pricing.BATCH_DISCOUNT` | 50% off, for band 4's offline authoring pass |

Infrastructure cost is deliberately near-zero too: SQLite rather than Postgres, one
process, in-memory indexes, **no vector database, no Redis, no `torch`, no
`sentence-transformers`, and no `anthropic` in the base install**. At 45 rows a
brute-force scan is microseconds, so Phase 1 needs none of it.

`GET /api/v1/meta/usage` reports session spend, because cost is only ever controlled if
something reports it. Every turn writes a `transaction_log` row — a cost of `$0.00` is
still a row, so the accounting path is exercised before it gets expensive to find it
wrong.

---

## Notes for the frontend

1. **Dev proxy** `/api` → `http://127.0.0.1:8010`. Avoids CORS entirely in dev.
2. **Cookies are load-bearing.** Session and age-gate cookies are httpOnly and signed,
   so `fetch` needs `credentials: "include"` **and** `EventSource` needs
   `{ withCredentials: true }`. With credentials on, the server cannot send
   `Access-Control-Allow-Origin: *`, so `WA_CORS_ORIGINS` must name your Vite origin.
   The dev proxy sidesteps this.
3. **Casing is free.** `WA_WIRE_CASE=snake` (default, matches the diagram) or `camel`.
   Input accepts **both** spellings either way, so a frontend typed against the wrong
   one still posts successfully — only responses change shape.
4. **The stream is per-conversation and long-lived**, not per-turn. Open it when the
   conversation mounts; `POST …/messages` returns only `{turn_id}` and the content
   arrives on the stream already open. Send an `Idempotency-Key` (a uuid per send,
   reused on retry) or the POST is rejected.
5. **Resuming.** Keep the last `id:` you saw and reconnect with `?after={seq}`.
   - Mid text run: token frames carry `anchor_seq`; reconnect with
     `?after={anchor_seq - 1}` and the whole run replays as one text frame.
   - A catch-up replay ends with `done` carrying `status: "idle"`, which means the
     stream is up to date and nothing is pending. Without it a client would render the
     transcript and then wait on a spinner forever.
6. **No wine vocabulary in the client.** Every label, level, hedge and refine chip comes
   from `GET /api/v1/meta/taste-axes`. `'likely dry' is not 'dry'` — the hedge is the
   backend's decision, served as `hedged_label`.
7. Every card carries `row_id`, `dataset_version` and `review_status`. An empty
   `example_producers` is a real state to design for (FR-11), not missing data.

---

## Deviations from the diagram, and why

1. **Middleware order.** Request-id and access logging are **outermost**, not innermost
   as drawn. Taken literally, a 429 or an age-gate 403 would carry no `X-Request-Id`
   and leave no log line — the two failures most likely to need tracing in a demo.
2. **The grounding guard sits in lane 2**, not lane 3. Lane 2 is the only lane every
   engine must pass through, and the component most capable of inventing a bottle is
   the Sonnet generator that lands next phase. The guard resolves every card's `row_id`
   and **rewrites the row-owned fields from the row itself**, so "no invented bottle"
   is a property of the transport rather than a promise from the component most likely
   to break it. Lane 3 keeping its own guard later is additive.
3. **Four schema additions**: `conversation.deleted_at` (the diagram calls DELETE a soft
   delete but gives only `archived_at`), `message_part.seq` (exact SSE resume),
   `idempotency_key`, and the three eval tables (`gold_set`, `retrieval_eval`,
   `intent_eval` — created now, only `intent_eval` has a writer yet).
4. **`?q=`** on the conversation list: the sidebar has a search box but the endpoint list
   had no search endpoint. Title substring only; message-body search needs an FTS5 table.
5. **`GET /meta/usage`** added, so spend is observable.
6. **Writes are serialised** behind one in-process lock using `BEGIN IMMEDIATE`
   (`db/database.py`). SQLAlchemy's deferred transactions return `SQLITE_BUSY` on
   upgrade — which `busy_timeout` cannot wait out — and that surfaced as "database is
   locked" under the 20 concurrent sessions NFR-2 requires. Reads stay concurrent.
7. **The abstention gate is a sweetness tolerance, not only a distance.** A candidate
   more than one sweetness level from what was asked is not a match. A pure distance
   threshold could not carry this: the weighted distance is normalised over whichever
   axes are filled, so the same one-step miss scores 0.33 for a red (three questions)
   and 0.50 for a dessert (two). Without it, asking for a dessert wine that is "not
   sweet at all" returned five properly-sweet dessert wines — the exact failure FR-13
   names.

## Still open

`docs/backend-todo.md` §15. The ones that matter: whether the wire should be camelCase
(one setting, free until your types are written), whether the ~45-row unreviewed seed
is the right stand-in for band 4's artifact, and whether the Anthropic client belongs
here or with the orchestrator.
