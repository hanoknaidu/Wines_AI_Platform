# Wines AI — Backend Implementation To-Do

> **Scope of this phase: lane 2 of the architecture diagram — the back end — and nothing else.**
> FastAPI, SQLite, the full REST + SSE surface, persistence, and the frozen-dataset loader.
> **No LangGraph, no orchestration workflows, no model calls.** Lane 3 and lane 4 sit behind one
> interface (§8). Band 2's RAG pipeline and band 4's authoring pipeline are not built here.
>
> The deliverable is a service that boots with **no `ANTHROPIC_API_KEY`, no network, no
> orchestrator and no frontend**, and answers every endpoint in §5 with real recommendations
> derived from a real frozen dataset — interview, recommend, refine and out-of-scope all
> reachable, every card carrying a genuine `row_id`.
>
> Source of truth: `wines-ai-technical-architecture.excalidraw` v0.1 · 2026-10-22.
> Where it and `wines-ai-brd-prd-frd.md` v1.1 disagree, the diagram wins (it supersedes §5 /
> FR-10 / NFR-1 / NFR-4 / NFR-9 by its own note).
>
> v0.2 · 2026-10-22 · **IMPLEMENTED.** All eight phases are built and verified:
> 114 tests green, `ruff` clean, 49/49 end-to-end checks against a real uvicorn
> process on a cold database. What changed during implementation is recorded in §16;
> the open questions in §15 are unchanged and still want your answers.

---

## 1. Ground Rules

1. **Standalone and end-to-end.** `uvicorn wines_ai.main:app` must be enough. Confirm age, start a
   conversation, type *"something smooth and not too sour"*, get streamed interview questions with
   chips, answer them, receive 3–5 recommendation cards each citing a dataset row, press *less
   sweet*, get a re-ranked set. Nothing stubbed at the network boundary; nothing requiring a
   service that is not in `pyproject.toml`'s base dependencies.
2. **The back end owns transport and persistence only.** The diagram states this in the lane
   itself: *no prompt, no retrieval and no ranking decision is made in this lane.* Routes,
   middleware, SQL, SSE, idempotency, ordering and logging are this phase's work. The Phase-1
   engine that produces turn content (§8) is a **separate, swappable module**, not logic smeared
   into the routes.
3. **The orchestration layer is a seam, not a stub.** The intent router, the four workflows, the
   grounding guard and the A→K pipeline sit behind one `TurnEngine` protocol. Phase 1 ships a
   deterministic local implementation (§8.2). Swapping in LangGraph changes no route, no schema,
   no SQL, no SSE frame.
4. **Session on every row, session in every query.** FR-12 is many concurrent anonymous sessions
   with no sign-up. `user_id` comes from one signed httpOnly cookie resolved in a single
   dependency; every repository takes `user_id` as a required argument. Phase 2 accounts replace
   the dependency and nothing else.
5. **Every served claim resolves to a dataset row, enforced at the engine boundary.** The runner
   validates each card's `row_id` against the loaded index *before the event leaves the process*.
   A card that fails is dropped and replaced with templated copy from the row. This is the
   diagram's grounding guard, deliberately placed in this lane — see §8.4 for why.
6. **Nothing is generated at request time in this phase.** No model runs, so NFR-1's original
   <100 ms and NFR-4's no-credentials posture are *both still true* for the whole of Phase 1. The
   architecture's amendment comes due when lane 3 lands, not now.
7. **Nothing fails silently.** No match is a 200 with an explicit empty state (FR-13), never
   silently relaxed filters. No stack trace reaches a user (NFR-7). Every failure path has a
   named `code`.
8. **Every turn is logged and costed** (NFR-8). `transaction_log` gets a row for every turn
   including the deterministic ones — `model: "deterministic"`, `tokens_in: 0`, `cost_usd: 0.0` is
   still a row. The observability path has to be exercised before the real models make it
   expensive to discover it was wrong.
9. **Nothing blocks the event loop.** Dataset load happens at lifespan startup. Ranking over a few
   hundred in-memory rows is microseconds, so it runs inline; if the corpus ever grows past that,
   it moves to a thread — the call site is already `await`ed so that change is local.

---

## 2. Starting Point — What Already Exists

| Thing | State | Note |
|---|---|---|
| `wines-ai-technical-architecture.excalidraw` | ✅ v0.1 | The contract. Lane 2 and band 3 are this phase |
| `wines-ai-brd-prd-frd.md` | ✅ v1.1 | FR/NFR ids referenced throughout; five decisions now reversed by the diagram |
| `ideas.md` | ✅ | Superseded; kept for the dead ends recorded in §7.5 and §11 |
| `backend/` | **not built** | Everything in §4 |
| The frozen dataset (band 4's output) | **not built** | Out of scope. §9 ships a schema-identical seed so this phase is end-to-end |
| Frontend | in progress, separate | Not touched. §14 is the integration note |

Unlike Legal Lens, nothing is pre-provisioned here — this phase writes the backend from an empty
directory.

---

## 3. Decisions Made — Overrule Any of These

| Area | Choice | Why |
|---|---|---|
| Package / path | `backend/src/wines_ai/`, `uv`, Python 3.12 | Matches the diagram's lane-2 stack line and the Legal Lens layout, so one set of conventions covers both projects |
| Server | uvicorn, **single worker** | The SSE bus and the in-flight turn registry are in-process, and SQLite takes one writer. Multi-worker needs Redis and buys nothing at NFR-2's 20 sessions. Documented in the README as a deployment constraint rather than left to be discovered |
| Database | SQLite (WAL) via `aiosqlite` | Diagram, band 3. `Phase 2 → Postgres: same schema, swap the SQLAlchemy URL` |
| Data access | **SQLAlchemy Core** + Alembic, no ORM | The diagram specifies both. Core keeps the SQL visible and the `user_id` filter explicit; it is not an ORM, so §1.4 stays auditable. *This deliberately differs from Legal Lens's raw-SQL choice — the diagram's Postgres path is the reason* |
| Wire casing | **`snake_case`** | The diagram writes `turn_id`, `row_id`, `dataset_version` on the wire. One `alias_generator` line flips the whole surface to camelCase if the frontend wants it — **§15 Q1, answer this first, it is the only decision that can cost you a rename** |
| API version | `/api/v1` prefix, OpenAPI 3.1 | Diagram |
| Turn content | `TurnEngine` protocol; Phase 1 = `DeterministicEngine` | §8. Real slot filling, real filtering, real ranking, real diversification, real citations, zero network |
| Intent routing | Keyword + slot-state router, mirroring the four lane-3 intents exactly | The Haiku router is orchestration. Mirroring the intent *names and semantics* means the UI behaves identically after the switch |
| Interview logic | Lives behind the engine, replaced wholesale by lane 3 | A backend that cannot ask question 1 cannot be integrated against. §8.2 |
| Streaming | SSE, per-conversation stream, resume by `?after={seq}` | Diagram. §6 pins the exact frames and the resume semantics |
| Idempotency | Required `Idempotency-Key` on `POST …/messages`, 24 h retention | The diagram's client sends one. §5.2 |
| Age gate | Signed httpOnly cookie, re-checked server-side in middleware on every chat route | Diagram, lane 1 + lane 2 |
| Rate limit | In-process per-IP token bucket | Band 3: *in-process TTL map for Phase 1; Redis once there is more than one process* |
| Middleware order | request-id → logging → exception shield → CORS → session → age gate → rate limit → idempotency | **Deviates from the diagram's drawn order.** The diagram puts request-id and logging innermost, which means a 429 or an age-gate 403 would carry no request id and never be logged. Request-id outermost makes every response traceable. §10.1 |
| Errors | RFC 9457 `application/problem+json` + `X-Request-Id` on every response | A user-visible failure traces to a log line traces to a `transaction_log` row |
| Grounding guard | Enforced in this lane, at the engine boundary | §8.4 — placing it here protects against the *future* orchestrator too, not just the current engine |
| Model gateway / Anthropic client | **Not built.** Lane 4 ships with lane 3 | Same reasoning as Legal Lens: a half-crossed boundary is worse than a visible one. §15 Q8 |
| `graph_checkpoint` | Table + repository built; the deterministic engine writes its stage snapshots | Exercises replay and audit before LangGraph exists |
| Tests | pytest + `httpx.ASGITransport`, temp SQLite per test, no network | §12 |

---

## 4. Module Layout

```
backend/
├── pyproject.toml · .env.example · README.md · alembic.ini
├── alembic/versions/
└── src/wines_ai/
    ├── main.py                 app factory · lifespan · middleware chain · router mount
    ├── config.py               Settings: db url, cors origins, cookie secret, limits, k values,
    │                           dataset path, confidence thresholds, model ids (unused in P1)
    ├── schemas.py              the whole wire contract, Pydantic v2
    ├── errors.py               ApiProblem + handlers → problem+json
    ├── deps.py                 get_db · get_services · current_user_id · require_age_confirmed
    ├── observability.py        structured JSON logs (request-id → turn-id) · metrics sink
    ├── middleware/
    │   ├── request_id.py · logging.py · shield.py
    │   ├── session.py          anonymous signed cookie → user_id, minted on first request
    │   ├── age_gate.py         blocks every chat route until confirmed
    │   ├── rate_limit.py       per-IP token bucket over the TTL map
    │   └── idempotency.py      key → stored response, replay-safe
    ├── api/v1/
    │   ├── conversations.py    POST · GET(list) · GET(transcript) · PATCH · DELETE
    │   ├── turns.py            POST …/messages · GET …/stream · POST /turns/{id}/cancel
    │   ├── feedback.py         POST /messages/{mid}/feedback
    │   ├── meta.py             /meta/taste-axes · /meta/dataset-version
    │   ├── age_gate.py         POST /age-gate
    │   └── health.py           /healthz · /readyz
    ├── services/
    │   ├── conversations.py    ConversationService — create, list, rename, archive, soft delete
    │   ├── messages.py         MessageService — seq allocation, parts, transcript hydration
    │   ├── profile.py          ProfileService — taste_profile read/merge, confidence tracking
    │   ├── feedback.py         FeedbackService
    │   ├── transactions.py     TransactionLog — turn rows, retrieval rows, checkpoints
    │   └── bus.py              SseEventBus — per-conversation fan-out, replay, keep-alive
    ├── db/
    │   ├── engine.py           async engine, WAL + foreign_keys pragmas
    │   ├── tables.py           MetaData / Table definitions (§7)
    │   └── repositories/       conversations · messages · parts · profile · feedback
    │                           · transaction_log · retrieval_log · checkpoints · idempotency
    ├── turns/
    │   ├── engine.py           TurnEngine protocol · TurnRequest · TurnEvent union
    │   ├── runner.py           drives the engine → grounding guard → persist part → publish
    │   ├── registry.py         in-flight turns, cancellation tokens, 120 s expiry
    │   ├── grounding.py        row_id resolution + templated-copy fallback
    │   ├── deterministic.py    the Phase-1 engine (§8.2)
    │   └── orchestrated.py     seam: constructed, raises ApiProblem if selected (§8.5)
    ├── taste/
    │   ├── axes.py             the 7 axes, levels, consumer labels, confidence chip labels
    │   ├── interview.py        which slot to ask next, phrased as sensation; 3-question cap
    │   ├── ranking.py          style hard filter → weighted distance across axes
    │   ├── diversify.py        spread across grape variety (FR-7)
    │   ├── refine.py           delta parsing → single-axis profile mutation
    │   └── copy.py             templated "what it tastes like" / "why it matches" from the row
    ├── dataset/
    │   ├── schema.py           the frozen-row Pydantic schema + validator (NFR-6)
    │   ├── loader.py           load · validate · build in-memory indexes at startup
    │   └── seed/wines.seed.json
    └── tests/                  §12
```

---

## 5. The API Contract

Base path `/api/v1`. Bodies `snake_case` (§15 Q1). Timestamps ISO-8601 UTC with `Z`.
Every response carries `X-Request-Id`.

### 5.1 Age gate

| Method | Path | Request | Response |
|---|---|---|---|
| POST | `/age-gate` | `{confirmed: true}` | `204` + `Set-Cookie: wa_age=…` (httpOnly, SameSite=Lax, 30 d) · `400` if `confirmed` is not true |

FR-1. The cookie is signed, not a bare flag — a client-set `wa_age=1` must not pass. Re-checked
server-side by middleware on every chat route; the cookie is convenience, the guard is the
control. Routes **open** without it: `/age-gate`, `/meta/*`, `/healthz`, `/readyz`, the OpenAPI
docs. Everything else returns `403 code: "age_not_confirmed"`.

### 5.2 Conversations

| Method | Path | Request | Response |
|---|---|---|---|
| POST | `/conversations` | `{title?}` | `201` `Conversation` |
| GET | `/conversations?cursor=&limit=20&archived=false&q=` | — | `200` `{items: ConversationSummary[], next_cursor: str\|null}` |
| GET | `/conversations/{cid}` | — | `200` `ConversationDetail` (transcript + taste profile) · `404` |
| PATCH | `/conversations/{cid}` | `{title?, archived?}` | `200` `Conversation` · `404` |
| DELETE | `/conversations/{cid}` | — | `204` (soft delete) · `404` |

- **Ordering** `updated_at DESC`, newest first, matching `idx conversation(user_id, updated_at DESC)`.
- **Cursor** is an opaque base64 of `(updated_at, id)` — keyset, not offset, so the sidebar's
  infinite scroll cannot skip or duplicate a row while new turns are bumping `updated_at`.
- **`q`** filters on title substring, case-insensitive. The diagram's sidebar has a search box but
  the endpoint list has no search endpoint; this is the smallest thing that satisfies it.
  Full-text over message bodies would need an FTS table over `message_part` — deferred, §15 Q6.
- **Grouping** (*Today / Last 7 days / Older*) is the client's job from `updated_at`; the backend
  does not guess the viewer's timezone.
- **Title** omitted → `"New conversation"`, replaced by the first user turn truncated to 52 chars
  + ellipsis. Auto-naming from turn 1 is the diagram's behaviour.
- **`dataset_version`** is pinned on the row at creation, so a transcript records which artifact
  it was served from. If the loaded version has moved on since, `ConversationDetail` returns both
  and sets `dataset_version_stale: true` rather than quietly re-serving.
- `DELETE` sets `deleted_at`; deleted conversations vanish from the list and 404 on fetch. Rows are
  kept because `transaction_log` and `feedback` reference them and the eval sets are the point.

### 5.3 Turns

| Method | Path | Request | Response |
|---|---|---|---|
| POST | `/conversations/{cid}/messages` | `{content, selected_chip_id?}` + `Idempotency-Key` header | `202` `{turn_id, user_message_id, seq}` · `404` · `409` turn already in flight · `422` |
| GET | `/conversations/{cid}/stream?after={seq}` | — | `200 text/event-stream` (§6) · `404` |
| POST | `/turns/{turn_id}/cancel` | — | `204` · `404` unknown/expired turn |

`POST …/messages` persists the user turn, allocates its `seq`, registers an in-flight turn and
returns **immediately**. No content is generated on this request — generation runs as a task that
publishes to the bus and persists parts as it goes. The client already holds an open stream for the
conversation, so there is no race between the POST returning and the first `token` landing.

- **`Idempotency-Key` is required.** A replay inside 24 h returns the original `202` body and
  starts nothing. Missing header → `400 code: "idempotency_key_required"`. Same key with a
  different body → `409 code: "idempotency_key_reused"`.
- **One in-flight turn per conversation.** A second send while one is running is a `409` naming
  the live `turn_id`, not a queue — two concurrent turns writing to one `seq` sequence is a
  correctness problem, and the UI has no affordance for it.
- **`selected_chip_id`** is how a chip click arrives: the content is still sent as text (so the
  transcript reads naturally), and the chip id tells the engine which slot was being answered,
  so the novice's tap is not re-parsed from prose.
- **Cancel** marks the turn cancelled, stops the task, persists whatever parts already committed,
  and emits `done` with `status: "cancelled"`. `transaction_log.status = "cancelled"`. Pending
  turns expire after 120 s regardless.

### 5.4 Feedback

| Method | Path | Request | Response |
|---|---|---|---|
| POST | `/messages/{mid}/feedback` | `{row_id, vote: "up"\|"down"}` | `204` · `404` message or row · `409` row not cited by that message |

FR-9. The `409` matters: a vote against a row the message never cited is either a client bug or a
forged request, and silently accepting it poisons the only honest signal the demo collects.
Re-voting the same `(message_id, row_id)` overwrites. Nothing consumes feedback yet — logging it
from day one means personalisation starts with a dataset instead of starting with a wait.

### 5.5 Meta

| Method | Path | Response |
|---|---|---|
| GET | `/meta/taste-axes` | `200` `TasteAxesResponse` |
| GET | `/meta/dataset-version` | `200` `{dataset_version, row_count, review_status_counts, built_at, checksum}` |

`/meta/taste-axes` is the **single source of truth for vocabulary**, so no wine word is hardcoded
in the frontend:

```json
{ "axes": [
    { "id": "sweetness", "asked": true, "question_order": 2,
      "prompt": "How sweet?",
      "levels": [ {"value": "dry",     "label": "Not sweet at all",       "hedged_label": "probably not sweet"},
                  {"value": "off_dry", "label": "Just a hint of sweetness","hedged_label": "maybe a hint of sweetness"},
                  {"value": "sweet",   "label": "Properly sweet",          "hedged_label": "likely sweet"} ] } ],
  "refine_chips": [
    {"id": "less_sweet", "label": "less sweet", "axis": "sweetness", "delta": -1} ],
  "confidence_threshold": 0.75 }
```

`hedged_label` is what delivers the diagram's *"'likely dry' is not 'dry'"* rule: below
`confidence_threshold` the card renders the hedged label, and the decision is the backend's, not
the frontend's.

### 5.6 Platform

| Method | Path | Response |
|---|---|---|
| GET | `/healthz` | `200 {status: "ok"}` — liveness, no dependency checks |
| GET | `/readyz` | `200 {status, dataset_version, row_count, indexes: {...}, db: "ok"}` · `503` if the dataset failed to load |

Split deliberately, per the diagram: *liveness · index-loaded readiness*. A process that is up but
has no dataset must fail `readyz` — serving a conversation with no rows to cite would produce
exactly the uncited answer the whole design exists to prevent.

### 5.7 Errors

```json
{ "type": "about:blank", "title": "Age confirmation required",
  "status": 403, "detail": "Confirm you are 21 or older before starting a conversation.",
  "request_id": "req-4b81…", "code": "age_not_confirmed" }
```

`code` is the stable machine-readable string; `detail` is user-presentable prose. `422` keeps
FastAPI's validation payload under `errors`. Codes: `age_not_confirmed` · `rate_limited` ·
`idempotency_key_required` · `idempotency_key_reused` · `turn_in_flight` · `turn_not_found` ·
`conversation_not_found` · `row_not_cited` · `dataset_unavailable` · `engine_unavailable`.

---

## 6. The SSE Protocol

The diagram's event set, exactly: `token · card · chips · citation · usage · done | error`.
One long-lived `EventSource` per conversation, not per turn.

```
id: 41
event: token
data: {"turn_id":"t-9f21","text":"Grenache "}

id: 42
event: card
data: {"turn_id":"t-9f21","row_id":"w-0104","variety":"Grenache","style":"red",
       "axes":{"sweetness":{"value":"dry","confidence":0.93,"label":"not sweet"},
               "body":{"value":"medium","confidence":0.71,"label":"probably medium-bodied"},
               "tannin":{"value":"smooth","confidence":0.88,"label":"smooth"}},
       "description":"Ripe red fruit, soft and warm, very little grip.",
       "why_it_matches":"You asked for smooth and not too sour — this is low in tannin and gentle in acidity.",
       "typical_regions":["Southern Rhône","Priorat"],"example_producers":[],
       "review_status":"unreviewed","dataset_version":"seed-0.1"}

id: 43
event: chips
data: {"turn_id":"t-9f21","kind":"refine",
       "options":[{"id":"less_sweet","label":"less sweet"},{"id":"lighter","label":"lighter"}]}

id: 44
event: citation
data: {"turn_id":"t-9f21","row_ids":["w-0104","w-0231","w-0077"],"dataset_version":"seed-0.1"}

id: 45
event: usage
data: {"turn_id":"t-9f21","intent":"recommend","intent_confidence":1.0,
       "model":"deterministic","tokens_in":0,"tokens_out":0,"cost_usd":0.0,"latency_ms":11}

id: 46
event: done
data: {"turn_id":"t-9f21","status":"ok","assistant_message_id":"m-5533","seq":46}
```

- **`id:` is a per-conversation monotonic `seq`**, and it is the same number `?after=` takes. This
  is what makes resume exact rather than approximate, and it is why `message_part` gains a `seq`
  column (§7, §15 Q3).
- **Resume** replays committed parts with `seq > after`, **then** attaches to the live buffer of
  any in-flight turn, **then** tails. The in-flight turn's partial token text is held in memory
  with its seq range, so a client that drops mid-stream and reconnects gets no gap and no
  duplicate. Without that buffer there is a hole between the last committed part and the live
  tail, which is the bug this design exists to avoid.
- **Tokens are coalesced on commit.** Live subscribers get one `token` event per chunk; the
  database gets **one** `text` part per message when the turn ends. Persisting a row per token
  would turn a 300-word answer into 400 writes for no readable benefit.
- **`chips` carries both kinds** — `kind: "interview"` with `axis`, `prompt` and option values
  during the interview, `kind: "refine"` after results. Same event, so the client has one
  renderer.
- **`usage` carries the turn's metadata** (intent, model, tokens, cost, latency) because the
  diagram's event list has no `meta` frame and inventing one would put the protocol out of step
  with the drawing. It is emitted once, immediately before `done`.
- **`done` always arrives**, with `status: "ok" | "cancelled" | "error"`. `error` frames carry a
  `ProblemDetail`. A client disconnect cancels the generation task; it does not leave an orphan
  writing to the database.
- Headers: `text/event-stream`, `Cache-Control: no-cache`, `X-Accel-Buffering: no`. A
  `: keep-alive` comment every 15 s so no proxy closes an idle conversation stream.

---

## 7. Data Layer

The diagram's band-3 schema, with four additions marked **＋**. Alembic from the first migration —
`create_all` would make the Postgres path in §3 a rewrite instead of a URL change.

```sql
conversation     (id, user_id, title, created_at, updated_at, archived_at, ＋deleted_at,
                  dataset_version)
message          (id, conversation_id, role, seq, turn_id, created_at)
                  UNIQUE(conversation_id, seq)
message_part     (id, message_id, kind, text, card_json, row_id, citation_json, ＋seq)
                  kind: text|card|chips|citation|error     UNIQUE(message_id, seq)
taste_profile    (conversation_id, style, sweetness, body, oak, tannin, acidity,
                  fruit_savoury, confidence_json)
feedback         (id, message_id, row_id, vote, created_at)  UNIQUE(message_id, row_id)
transaction_log  (id, conversation_id, turn_id, intent, intent_confidence, model, tokens_in,
                  tokens_out, cost_usd, latency_ms, status, error_code)
retrieval_log    (id, turn_id, stage, query_text, candidate_row_ids, ranks, scores)
graph_checkpoint (turn_id, node, state_json, created_at)
＋idempotency_key (key, endpoint, request_hash, response_json, turn_id, created_at, expires_at)
                  PRIMARY KEY(key, endpoint)
＋gold_set         (row_id, axis, true_value, labeller)            — migration only, no writer yet
＋retrieval_eval   (query, relevant_row_ids, recall_at_k, ndcg_at_10)  — migration only
＋intent_eval      (utterance, true_intent, predicted, confidence)     — migration only

idx: conversation(user_id, updated_at DESC) · message(conversation_id, seq)
   · transaction_log(turn_id) · message_part(message_id, seq) · feedback(row_id)
```

**Why each addition.** `deleted_at` — the diagram calls `DELETE` a soft delete but gives only
`archived_at`, and archive and delete are two different user actions that both appear in the
sidebar. `message_part.seq` — §6's exact resume needs a monotonic per-conversation event id.
`idempotency_key` — the client sends the header; something has to store it. The three eval tables
are band 3's eval store: created now so the band-2 work has somewhere to write, with no writer in
this phase except `feedback`, which band 1 feeds today.

**Rules.**
- Every repository method takes `user_id`; there is no unscoped read of a conversation row.
- `seq` is allocated inside the write transaction (`SELECT MAX(seq)+1 … ` under the single
  writer), never from application state — a gap or a duplicate breaks `?after=`.
- `message` + its `message_part` rows commit in one transaction. A card persisted without its
  citation would render as an uncited assertion.
- `taste_profile` is one row per conversation, upserted; `confidence_json` holds per-axis
  confidence and provenance (`asked` vs `inferred` vs `refined`), which is what lets the interview
  know not to re-ask and the refine step know which axis the user has actually touched.
- Pydantic schemas at every boundary; no raw row dict escapes a repository.

---

## 8. The Turn Engine Seam

### 8.1 The interface

```python
class TurnEngine(Protocol):
    async def run(self, req: TurnRequest) -> AsyncIterator[TurnEvent]: ...
```

`TurnRequest` carries exactly what the diagram's **turn context builder** assembles: the current
utterance, the selected chip id, the last N turns (windowed), the filled taste-profile slots with
their confidence, the previous result set and its row ids, and the conversation's
`dataset_version`. `TurnEvent` is `Token | Card | Chips | Citation | Usage | Done | Error`.

Everything above this interface — routes, SSE, seq allocation, persistence, idempotency,
cancellation, logging, cost — is written once in this phase and does not change when the
implementation does.

### 8.2 `DeterministicEngine` — the Phase-1 implementation

Not a mock returning canned text. **It is BRD v1.1's original serving path**, which is a complete
product in its own right:

```
answers → target profile → hard filter on style → weighted distance across the 7 axes
        → diversify by grape variety → top 3–5 rows → copy drawn from the row
```

That is the happy accident of this plan: the architecture's Phase-1 fallback is not a placeholder,
it is the thing the BRD originally specified — so the backend ships a working recommender with no
key, no network and sub-10 ms turns, and lane 3 later replaces *how* the profile is built, not
whether the app works.

The four lane-3 workflows, all reachable:

- **Intent routing.** Keyword + slot-state rules returning the same four intents lane 3 returns —
  `interview | recommend | refine | out_of_scope` — with a confidence. Logged to
  `transaction_log.intent` from day one, so the intent confusion matrix has data before the Haiku
  router exists.
- **1 · Interview.** Slots unfilled → ask, never guess. Picks the next most-discriminating
  question given what is known (style first, because it gates which axes apply at all; body for
  reds, oak for whites/rosé/sparkling; nothing further for dessert — FR-4), phrases it as a
  physical sensation with no wine jargon and never the word *dry*, emits option chips from
  `/meta/taste-axes`, writes the answer back to `taste_profile`. **Hard cap: 3 questions** (FR-2–4).
- **2 · Recommend.** Style as a hard pre-filter (FR-2). Weighted distance across the axes, with
  sweetness weighted heaviest (BRD §4). MMR-style spread across grape variety so the set spans at
  least two varieties wherever the match set allows (FR-7). 3–5 cards (FR-5), each with
  `why_it_matches` composed from the axes the user actually selected, in their words (FR-6), and
  per-axis hedged labels where confidence is below threshold. **No match → the FR-13 empty state**,
  never a silently widened filter: a `text` part saying so, plus chips offering the one axis whose
  relaxation would help.
- **3 · Refine.** Parses the delta against the **previous result set** — `less sweet`, `lighter`,
  `smoother`, `less oaky`, `more fruit`, `more earthy` — mutates that one axis only, and re-ranks
  over the previous candidates plus a widened set, so the correction is anchored to what the user
  actually saw. Never re-interviews (FR-8).
- **4 · Out-of-scope / safety.** Templated reply, no retrieval: no price, no availability, no
  health claims in either direction, no purchase path, no marketing to minors (BRD §8). The
  prompt-injection branch is moot while no model runs, but this is the function it will live in.

It writes real `retrieval_log` rows per stage (filter → rank → diversify) and real
`graph_checkpoint` snapshots per stage, so both tables are exercised and the audit trail is
provable before LangGraph produces one.

### 8.3 Streaming behaviour

The engine yields `token` events word-by-word on an uneven cadence with a small configurable
delay, not one atomic blob. The frontend's cursor, its stop button and its no-layout-shift
guarantees have to be tested against something that behaves like a stream, and the resume path in
§6 cannot be tested at all against an instant response.

### 8.4 Where the grounding guard sits, and why it is here

The diagram draws the grounding guard in lane 3. **This plan implements it in lane 2, at the
engine boundary**, in `turns/grounding.py`: every `Card` event is checked against the loaded
dataset index before it is persisted or published; an unresolvable `row_id` means the card is
dropped and replaced by templated copy built from the row that *does* resolve, and the drop is
logged as `grounding_drop`.

The reason is that lane 2 is the only lane that every engine must pass through. A guard inside the
orchestrator protects against the orchestrator's mistakes; a guard at the boundary protects
against **any** engine, including the Sonnet generator that lands next phase and is the one thing
in the system actually capable of inventing a bottle. *No invented bottle* becomes a structural
property of the transport rather than a promise made by the component most likely to break it.
Lane 3 keeping its own guard later is additive, not a conflict.

### 8.5 Where lane 3 plugs in

`turns/orchestrated.py` is written as the protocol implementation plus the `TurnRequest` assembly
shape, and raises `ApiProblem(503, code="engine_unavailable")` if selected without the orchestrator
extra installed. Its body — the LangGraph invocation, the model gateway, the A→K pipeline — is
**the next phase's work**. Deliberately empty here, so the boundary is visible rather than
half-crossed.

`config.engine = "deterministic" | "orchestrated"`, defaulting to deterministic. That one setting
is the whole switch.

---

## 9. The Dataset

Band 4 produces the frozen artifact and is **out of scope**. But a backend with nothing to cite
cannot be built end-to-end, so this phase ships:

- **`dataset/schema.py`** — the real frozen-row schema, validated strictly (NFR-6):
  `row_id · variety · style · sweetness · body · tannin · acidity · fruit_savoury · oak ·
  confidence per axis · description · typical_regions[] · example_producers[] · review_status ·
  reviewed_by · reviewed_at · dataset_version`.
- **`dataset/loader.py`** — loads at lifespan startup, validates every row, fails `readyz` on a
  bad row rather than booting with a half-loaded index. Builds the in-memory indexes the
  deterministic engine reads: by style, by axis tuple, and a flat list for distance scoring. A
  few hundred rows scan in single-digit milliseconds, so Phase 1 needs no vector store, no FTS and
  no sqlite-vec — exactly as band 3 says.
- **`dataset/seed/wines.seed.json`** — roughly 30 rows covering all five styles and all three
  sweetness levels, enough that every branch of the interview reaches a real result.

**Two honesty constraints on the seed, which are not negotiable:**

1. `review_status: "unreviewed"` on every seed row, surfaced by `/meta/dataset-version`. These
   rows have not been through band 4's human review, and the API must say so rather than let an
   unreviewed artifact masquerade as a frozen one.
2. **`example_producers: []` on every seed row.** Producer names are the weakest point in the whole
   system (BRD §8) and the one thing a model confabulates. Writing plausible producer names into a
   fixture would be committing exactly the failure the product exists to prevent — and it would
   look like real data the moment it rendered. Empty arrays also force the frontend to build
   FR-11's empty-producer state, which it needs regardless. Varieties, styles, axes and regions
   are stable documented knowledge and are populated.

Swapping in band 4's real artifact is then a path change in config plus a `dataset_version` bump —
no code change, because the loader validates against the real schema from day one. §15 Q2.

---

## 10. Cross-Cutting

### 10.1 Middleware chain

Built in this order, outermost first:

```
request-id → access log → exception shield → CORS → session cookie
          → age-gate guard → per-IP rate limit → idempotency → route
```

The diagram draws request-id and logging innermost. Taken literally, a rate-limited request or an
age-gate rejection would return no `X-Request-Id` and leave no log line — the two failures most
likely to need tracing in a group demo. Request-id outermost, with the shield just inside it, makes
**every** response traceable and every rejection logged. Flagged as a deviation, §15 Q4.

- **Session cookie** mints an anonymous `user_id` on first contact (signed, httpOnly, SameSite=Lax,
  30 d) and attaches it to the request. No sign-up (FR-12); a cleared cookie is a clean restart.
- **Rate limit** is a per-IP token bucket in the TTL map: a generous default for reads, a tighter
  one for `POST …/messages`. `429` with `Retry-After` and `code: "rate_limited"`.
- **Idempotency** only engages on `POST …/messages`.
- **Exception shield** converts anything unhandled into a `500` problem+json with the request id
  and logs the traceback server-side. No stack trace reaches a user, ever (NFR-7).

### 10.2 Observability

Structured JSON lines, `request_id → turn_id → stage`, which is the join key across
`transaction_log`, `retrieval_log` and `graph_checkpoint`. One `transaction_log` row per turn
without exception (§1.8). Per-stage latency recorded so p50/p95 per stage exists before the
stages get expensive. An in-process metrics sink; no Prometheus in Phase 1.

### 10.3 Configuration

Everything the diagram lists under config & secrets is a setting, env-injected: db url, CORS
origins, cookie secret, rate limits, confidence threshold, token budget, k per retriever, RRF k,
MMR lambda, model ids. **The lane-3 and lane-4 settings exist and are unused in Phase 1** — they
are read by the orchestrated engine, so the config surface does not change when it lands.
`ANTHROPIC_API_KEY` is optional and absent by default; the service must boot without it and
`readyz` must not care.

---

## 11. Build Phases

### Phase 0 — App assembly
- [x] `pyproject.toml` (fastapi, uvicorn, pydantic v2, pydantic-settings, sqlalchemy, aiosqlite, alembic, itsdangerous; `dev` extra: pytest, pytest-asyncio, httpx, ruff; `orchestrator` extra declared but unused)
- [x] `config.py`, `observability.py`, `errors.py` + problem+json handlers
- [x] `main.py`: app factory, lifespan, the §10.1 middleware chain, router mount under `/api/v1`
- [x] `/healthz` and `/readyz` answering; `.env.example`; README with the single-worker constraint
- [x] Service boots clean with no API key and no dataset (readyz red, healthz green)

### Phase 1 — Data layer
- [x] `db/engine.py` with WAL + foreign-keys pragmas; `db/tables.py` for all 13 tables
- [x] Alembic initial migration; `alembic upgrade head` on an empty file produces the schema
- [x] Repositories, every method `user_id`-scoped; `utcnow()` and row→model mappers
- [x] Session-cookie middleware + `current_user_id` dependency

### Phase 2 — Dataset
- [x] `dataset/schema.py` strict validator + unit tests for a bad row (NFR-6)
- [x] `dataset/loader.py`, in-memory indexes, `readyz` gated on a clean load
- [x] `seed/wines.seed.json` — ~30 rows, five styles, three sweetness levels, no producers (§9)
- [x] `taste/axes.py`; `GET /meta/taste-axes` and `GET /meta/dataset-version`

### Phase 3 — Age gate + conversations
- [x] `POST /age-gate`, signed cookie, middleware guard, open-route allowlist, `403` code
- [x] All five conversation endpoints; auto-title from turn 1; keyset cursor; `q`; archive; soft delete
- [x] `ConversationDetail` hydrating transcript parts in `seq` order + taste profile

### Phase 4 — Turns + SSE  ← *the core*
- [x] `SseEventBus`: per-conversation fan-out, replay from `?after=`, live-buffer handoff, keep-alive
- [x] `GET …/stream` with the §6 headers and frames; `id:` = part `seq`
- [x] `POST …/messages`: persist user turn, allocate seq, register turn, return `202`
- [x] Idempotency middleware + table; replay returns the original body
- [x] `registry.py`: one in-flight turn per conversation, `409`, 120 s expiry, cancellation tokens
- [x] `POST /turns/{id}/cancel`; disconnect cancels the task; `runner.py` persisting parts as it goes

### Phase 5 — The deterministic engine
- [x] `turns/engine.py` protocol, `TurnRequest`/`TurnEvent`
- [x] Intent router (four intents + confidence); `taste/interview.py` with the 3-question cap
- [x] `taste/ranking.py`, `diversify.py`, `copy.py` — cards with `why_it_matches` and hedged labels
- [x] `taste/refine.py` against the previous result set
- [x] Out-of-scope / safety templates
- [x] FR-13 empty state
- [x] `turns/grounding.py` enforced at the boundary (§8.4)
- [x] `turns/orchestrated.py` seam raising `engine_unavailable`

### Phase 6 — Feedback + logs
- [x] `POST /messages/{mid}/feedback` with the `409` not-cited check
- [x] `transaction_log` row per turn; `retrieval_log` per stage; `graph_checkpoint` per stage

### Phase 7 — Tests (§12)

### Phase 8 — Hardening
- [x] Rate limits tuned; OpenAPI 3.1 descriptions and examples on every route
- [x] README: run commands, the single-worker constraint, the BRD-amendment note, what is a seam
- [x] `ruff` clean; 20-concurrent-session check (NFR-2)

---

## 12. Testing Plan

pytest + `httpx.ASGITransport`, a temp SQLite file per test, no network, no key.

**Contract and transport**
- Age gate: every chat route `403`s before confirmation and passes after; a forged `wa_age` cookie fails
- Session isolation: session B cannot read, rename or delete session A's conversation (404, not 403 — existence is not leaked)
- 20 concurrent sessions each completing a full flow (NFR-2)
- Keyset pagination: no skipped or duplicated conversation while turns bump `updated_at` mid-scroll
- Idempotency: same key twice → one turn, identical body; same key different body → `409`
- Second send while in flight → `409` naming the live turn
- **SSE resume**: drop at seq N mid-turn, reconnect `?after=N` → no gap, no duplicate, `done` still arrives
- Cancel mid-turn → partial parts persisted, `done status:"cancelled"`, `transaction_log` cancelled
- No endpoint returns a stack trace; every error carries `code` + `request_id` (NFR-7)

**Behaviour**
- Interview asks style first, caps at 3 questions, skips Q3 for dessert (FR-4), never emits the word *dry*
- Chip answer and the equivalent typed answer reach the same profile
- Recommend returns 3–5 cards (FR-5) spanning ≥2 varieties where the match set allows (FR-7)
- Refine mutates one axis only and re-ranks against the previous set without re-interviewing (FR-8)
- Out-of-scope asks (price, where to buy, health) get the templated reply and **no** cards
- No-match → FR-13 empty state, filters provably unchanged
- Hedged label appears below the confidence threshold and not above it

**Grounding — the property test that matters**
- Every `card` event's `row_id` exists in the loaded dataset, across a generated sweep of profiles (FR-10, NFR-9)
- An engine stubbed to emit a bogus `row_id` has its card dropped and replaced, and the drop is logged (§8.4)
- No seed row carries a producer name (§9)

**Units**
- Ranking: ordering, sweetness weighting, style hard filter; diversification; refine deltas
- Dataset validator rejects a missing axis, a bad level, a bad confidence, a duplicate `row_id`
- `seq` allocation under concurrent writes produces no gap or duplicate

---

## 13. Definition of Done

1. `uvicorn wines_ai.main:app` boots with no API key, no network, no orchestrator, no frontend.
2. `POST /age-gate` → `POST /conversations` → open the stream → send *"something smooth, nothing too sour"*
   → streamed interview question with chips → two chip answers → **3–5 cards, each citing a real
   `row_id`** → `less sweet` → a re-ranked set anchored to the previous one.
3. Ask for a style that cannot match the profile → FR-13 empty state, no silently widened filter.
4. Ask for the price or where to buy → the templated out-of-scope reply, no cards.
5. Kill the stream mid-turn and reconnect with `?after=` → the turn completes with no gap and no duplicate.
6. Every turn has a `transaction_log` row; every card has a `retrieval_log` trail; a thumbs-down writes `feedback`.
7. `/meta/dataset-version` reports `seed-0.1`, `review_status: unreviewed`, and the row count.
8. Swapping `config.engine = "orchestrated"` fails with `engine_unavailable` and changes nothing else.
9. `ruff` clean, tests green, OpenAPI 3.1 renders every route.

---

## 14. Frontend Integration — What You'll Need

Not this phase's work, and the frontend does not exist here to diff against. Three things to know
while you build it against mocks:

1. **Dev proxy** `/api` → `http://127.0.0.1:8000`, so there is no CORS in dev and no base-URL
   switch in the client.
2. **Cookies are load-bearing, and this bites.** The session and age-gate cookies are httpOnly, so
   `fetch` needs `credentials: "include"` **and** `EventSource` needs `new EventSource(url, {
   withCredentials: true })`. With credentials on, the server cannot answer
   `Access-Control-Allow-Origin: *` — `config.cors_origins` must name the Vite origin explicitly.
   A dev proxy (1) sidesteps the whole problem; it is worth doing for that reason alone.
3. **The stream is per-conversation and long-lived**, not per-turn. Open it when the conversation
   mounts, keep the last seen `id:` and reconnect with `?after={seq}`; `POST …/messages` returns
   only `{turn_id}` and the content arrives on the stream already open. Send an
   `Idempotency-Key` (a uuid per send, reused on retry) or the POST is rejected.

No wine vocabulary belongs in the client: every label, level, hedge and refine chip comes from
`GET /meta/taste-axes`, and every claim on a card arrives with a `row_id` and a `dataset_version`
attached.

---

## 15. Open Questions

1. **Wire casing — answer this one first.** The diagram writes `turn_id`, `row_id`,
   `dataset_version`, so I have taken **`snake_case` on the wire**. Legal Lens went camelCase with
   a `Wire` translator. It is a one-line `alias_generator` change here, but only until you have
   typed the frontend against one of them — so if you want camelCase, say so now and it costs
   nothing.
2. ~~**The seed dataset.** Is ~30 unreviewed rows with **empty producer lists** (§9) the right
   stand-in for band 4's artifact?~~ **Answered — see §17.** The seed keeps its empty producer
   lists unchanged; a *second* artifact carries illustrative names under a new
   `review_status: "fixture"` that cannot be signed. Cards look full in a demo without any
   surface claiming a review that did not happen.
3. **`message_part.seq`** (§7). One added column, and the thing that makes `?after=` exact instead
   of replay-the-whole-message. Confirm, or tell me to resume at message granularity.
4. **Middleware order** (§3, §10.1). I have moved request-id and logging outermost against the
   drawn order, so a 429 or a 403 is still traceable. Confirm, or I follow the diagram literally.
5. **One in-flight turn per conversation** (§5.3) — a second concurrent send is a `409`, not a
   queue. Right call for this UI?
6. **Sidebar search.** The sidebar has a search box; the endpoint list has no search endpoint. I
   have added `?q=` as a title filter. Should it search message bodies too? That needs an FTS5
   table over `message_part`, which is real work and a second index to keep in sync.
7. **The three eval tables** (`gold_set`, `retrieval_eval`, `intent_eval`) — migration-only in this
   phase, no writers. Correct, or should the deterministic engine start populating `intent_eval`
   from its own routing decisions now?
8. **Does the Anthropic client belong here?** My read of "only build the backend, no orchestration"
   is no — the model gateway is lane 4 and ships with lane 3, so §8.5 is a seam. If you would
   rather this phase ended with one real streamed Sonnet call behind
   `config.engine = "single_call"` — no router, no graph, no RAG — say so and I will add it as
   Phase 5b.
9. **The BRD amendment.** The diagram says one is required and lists the five reversals. Should I
   write `docs/brd-amendment.md` as part of this phase, or does that belong with the lane-3 work
   that actually causes the reversals? Note that for all of Phase 1, FR-10, NFR-1, NFR-4 and NFR-9
   are **still satisfied** — no model runs yet.
10. **Dessert + Q3.** FR-4 skips the third question for dessert, so a dessert conversation fills
    two slots. Should the engine then recommend from two axes, or ask a different third question
    the diagram does not specify? I have taken the former: recommend from what FR-4 allows.

---

## 16. Implementation Log — What Changed, and Why

Written after the build. Everything in §1–§14 shipped; these are the places where
contact with a running system changed the plan.

### Defects the build surfaced (each found by a test, each fixed)

| # | Defect | Why it mattered |
|---|---|---|
| 1 | **The empty state was unreachable.** Style was a hard filter but sweetness was only weighted, so "a dessert wine, not sweet at all" returned five properly-sweet dessert wines | The exact failure FR-13 names — silently relaxing the filter. Fixed with a **sweetness tolerance** (more than one level away is not a match), not a distance threshold: a weighted distance is normalised over whichever axes are filled, so the same one-step miss scores 0.33 for a red (three questions) and 0.50 for a dessert (two), and no single threshold fits both |
| 2 | **"nothing too sweet" was read as `sweet`** | A longest-match phrase table has no negation handling: the string contains "sweet" but not the phrase "nothing sweet". It failed in the worst direction — serving dessert wine to someone refusing it. Fixed with explicit negation cues plus an off-dry allow-list so "just a hint of sweetness" is still off-dry |
| 3 | **`usage.intent` logged `interview` for turns that served cards** | `transaction_log.intent` feeds the intent eval set; a turn mislabelled while serving five cards corrupts the baseline the Haiku router will be measured against. `Usage` now reports the **effective** intent, emitted at the end of the turn |
| 4 | **`recommend` was dispatched with the stored profile**, losing the slots the router had just read out of the utterance | With an empty stored profile this landed in the empty state instead of answering. Both `interview` and `recommend` now go through the interview path, which harvests first and then decides |
| 5 | **Replay ordering was inverted.** The coalesced text part was written at the end of the turn, so it got a higher seq than the cards that followed it live | A resuming client saw text *after* cards. Text runs are now flushed when a non-token event arrives, stamped with the run's **first** token seq |
| 6 | **`database is locked` under 20 concurrent sessions** | A direct NFR-2 failure. SQLAlchemy's DEFERRED transactions return `SQLITE_BUSY` on upgrade, which `busy_timeout` cannot wait out. Writes now serialise behind one in-process lock using `BEGIN IMMEDIATE` (`db/database.py`); reads stay concurrent |
| 7 | **A caught-up client waited forever.** `usage` and `done` are transport frames and are not persisted, so replaying a finished conversation never produced a terminal frame | The client would render the transcript and spin. A catch-up replay now ends with `done status:"idle"`, **and that frame carries no `id:`** so it cannot move the resume cursor — `id:` stays strictly increasing |
| 8 | **12 turns/min was too tight** | Three interview answers plus a few refine taps clears it. Raised to 30/min, still a hard bound on spend |

### Decisions settled rather than left open

- **§15 Q1, wire casing — removed as a risk instead of decided.** `WA_WIRE_CASE=snake`
  (the diagram's spelling) or `camel`, and **input accepts both spellings either way**.
  A frontend typed against the wrong one still posts successfully; only responses
  change shape. Verified both directions against a running server.
- **§8.4, the grounding guard stays in lane 2** — and does more than resolve the id. It
  **rewrites every row-owned field from the row itself** (variety, description,
  regions, producers, review_status), so an engine cannot smuggle a claim through by
  attaching it to a real `row_id`. A card that does not resolve is dropped and replaced
  with templated copy. Proven by a property sweep over every reachable profile.
- **§8.2, the deterministic engine is BRD v1.1's serving path**, as planned — a working
  recommender at sub-10 ms per turn with no key and no network.

### Cost work (added beyond the original plan)

Phase 1 spends nothing, so this is all about bounding the *eventual* bill:

- `pricing.py` — rates from the Anthropic reference, so `cost_usd` is computed. Encodes
  two traps: **Haiku's 100K tier break** (input jumps 5×, which is what
  `context_token_budget` = 8K guards) and the **10× gap between a Sonnet cache read and
  fresh input**, which makes cache-stable prefix ordering a cost requirement.
- `turns/cost.py` — a **turn cache** (a repeated question against the same profile and
  dataset version replays free) and a **cost guard** with per-turn, per-session and
  global-daily ceilings that **degrade to the free engine rather than erroring**, primed
  from `transaction_log` at boot so a restart does not reset them.
- `GET /api/v1/meta/usage` — session spend, because cost is only ever controlled if
  something reports it.
- Base install carries **no `anthropic`, no `langgraph`, no `torch`, no
  `sentence-transformers`, no vector DB and no Redis**.

### Verification

| | |
|---|---|
| Unit + contract + streaming tests | **114 passed** (`pytest`), ruff clean |
| End-to-end against a real uvicorn process, cold DB | **49/49 checks**, 0 server errors |
| Concurrency | 20 simultaneous sessions each completing a full flow (NFR-2) |
| Grounding | property sweep across every reachable profile: every card resolves, no producer invented |
| Cold boot | builds and serves with an empty environment and no `ANTHROPIC_API_KEY` |
| Migrations | `alembic upgrade head` on an empty file produces all 12 tables |

---

## 17. The Demo Artifact (resolves §15 Q2)

The seed's empty producer lists are correct and stay exactly as they are — §9's two honesty
constraints are not negotiable, and five test assertions pin them. What was missing is that a
demo of a *recommendation card* showed an explanatory sentence where its producer names belong,
so the product looked thinner than it is.

Fixed by adding an artifact, not by editing the seed.

### `review_status: "fixture"` — a fourth state

`dataset/schema.py` now accepts `unreviewed · reviewed · corrected · fixture`. `fixture` is the
only state that carries producer names **without** a human signature: the names are
illustrative, generated rather than verified.

Two validators guard it, in both directions:

| Guard | Rule |
|---|---|
| Pre-existing | `reviewed`/`corrected` **require** `reviewed_by` — an unsigned review is rejected |
| **New** | `fixture` **forbids** `reviewed_by` — a fixture row is unverified by definition |

The second one is the point. Populating producers and then stamping a reviewer name would forge
precisely the signature §9 and BRD §8 exist to protect, so the schema makes it impossible rather
than leaving it to discipline.

### `dataset/build_demo.py` → `seed/wines.demo.json`

```bash
python -m wines_ai.dataset.build_demo     # rebuild after any seed change
```

A script, not a hand-written file: it reads the seed and changes **exactly three fields** per row
— `example_producers`, `review_status`, `dataset_version` (`demo-0.1`). Everything else is copied
through byte-identically, so the demo can never drift from the seed on a taste axis, a
description or a region. `test_units.py` asserts that delta, so a later edit that causes drift
fails the suite instead of shipping two disagreeing datasets. 135 producer names over 45 rows,
each inside the regions already on its row.

**The names are unverified.** They were written from model knowledge and no person has checked
them against a label, an importer or a registry. That is the entire reason for the `fixture`
status. Promoting a row to `reviewed` means a person checks the names and signs it — that is the
review pipeline, and it is still unbuilt.

### Running it

Serving the demo artifact is a **path change and nothing else**, as §9 promised:

```bash
# backend
WA_DATASET_PATH="$PWD/src/wines_ai/dataset/seed/wines.demo.json" \
  .venv/bin/python -m uvicorn wines_ai.main:app --port 8000

# frontend — mocks OFF, or the UI never reaches the backend
VITE_USE_MOCKS=false npm run dev
```

Omit `WA_DATASET_PATH` and you are back on the honest, producer-free seed. Both paths are tested.

### The frontend half, which was the actual risk

Three surfaces render the reviewed/unreviewed distinction, and each tested
`status === "reviewed"` independently. Left alone, a `fixture` artifact would have read as
*reviewed* in one place and *unreviewed* in another — and worse, `DatasetBadge` keys its tone off
the `unreviewed` count alone, so **45 fixture rows would have turned the trust badge green and
dropped its warning entirely.** That is the dishonest outcome this whole exercise exists to
avoid, and it was one `?? 0` away.

Now centralised in `lib/review.ts`:

- `isSigned()` — only `reviewed`/`corrected`. An unrecognised status degrades to `unreviewed`,
  the cautious end, so a future status the client does not know yet can never arrive looking
  checked.
- `ProvenanceFooter` — four-state badge. A fixture row reads **"example data"** in caution tone.
- `ProducerList` — names present is no longer enough. Unsigned names ship with *"Example names,
  not yet checked by a person"* attached, because bare pills say "verified" by omission.
- `DatasetBadge` — tone and warning key off `unverified` (`fixture + unreviewed + unknown`), not
  `unreviewed`. The warning text is **derived**: it used to hardcode that no producer names were
  listed anywhere, which was true of the seed and would have become a lie the moment any artifact
  carried names.

### Verification

| | |
|---|---|
| Backend | **120 passed** (was 114), ruff clean |
| Frontend | **56 passed** (was 49), `tsc -b` clean, eslint clean, build 165.86 kB gzipped |
| Real uvicorn on the demo artifact | `readyz` → `demo-0.1`, 45 rows, `{"fixture": 45}`; full interview served 5 cards, every one with producers, every one reporting `fixture` |
| Seed regression | untouched; all five original empty-producer assertions still pass |

### Still open

Producer names are **unverified** until someone signs them. The review pipeline — walk the rows,
check the names, stamp `reviewed_by` and `reviewed_at`, emit a signed artifact — is the real fix
for production and is not built. `fixture` is a demo state, not a destination.
