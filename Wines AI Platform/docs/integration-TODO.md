# Frontend ↔ Backend Integration — Plan

**Status: §3 (D1–D4) implemented and verified. §5, the browser pass, is still outstanding.**

Written after surveying both contracts and running the existing real-backend suite against a
live FastAPI on port 8001.

---

## 1. The headline: this is not a wiring job

The frontend was not built against ad-hoc fixtures. It was built against *this* backend, and
the seam was designed in from the start:

- **No base-URL switch exists or is needed.** Every call goes to `/api/v1` on the Vite origin
  ([lib/constants.ts:9](../frontend/src/lib/constants.ts#L9)) and
  [vite.config.ts](../frontend/vite.config.ts) proxies `/api` to the backend, with
  `x-accel-buffering: no` already set so SSE is not buffered into one lump.
- **Mocks are already a build-time branch, not a code path to remove.**
  [main.tsx:10](../frontend/src/main.tsx#L10) dynamically imports `./mocks/browser` only when
  `USE_MOCKS`, so `VITE_USE_MOCKS=false` drops MSW from the bundle entirely.
- **A real-backend test harness already exists** —
  [App.real.test.tsx](../frontend/src/app/App.real.test.tsx) (5 tests),
  [test/realBackend.ts](../frontend/src/test/realBackend.ts) (cookie jar + SSE passthrough),
  [test/eventSource.ts](../frontend/src/test/eventSource.ts) (an EventSource for jsdom).

So the work is **verifying parity and fixing what verification finds**, then looking at it in a
browser. Scope is much smaller than "integrate two systems".

---

## 2. What I verified before writing this

Against a live backend (`uvicorn wines_ai.main:app --port 8001`, seed artifact, 45 rows):

| Check | Method | Result |
|---|---|---|
| Response shapes | 11 payloads from the live server, key-by-key against the hand-written interfaces in [types/api.ts](../frontend/src/types/api.ts) | **11/11 exact.** No missing field, no extra field |
| SSE frames | drove a real turn, parsed every frame, compared against [types/sse.ts](../frontend/src/types/sse.ts) | **6/6 frame types match**; `id:` strictly increasing; no extra fields |
| Error envelope | 6 deliberate failures vs `ProblemBody` | **6/6 match**, each with a stable `code` |
| Route coverage | 15 MSW handlers vs 15 real routes | **1:1**, no mock-only or server-only route |
| Real-backend suite | ran it 5× | **passes, but flaky** — see D1 |

**Conclusion: the contract is already correct.** `wire_case=snake` matched, the hand-typed TS
never drifted, and casing — §15 Q1's biggest risk — is a non-issue. That is why this plan has no
"fix the contract" phase.

---

## 3. Defects found (fix these; they are the actual work)

### D1 — ~~P1 · The client stops receiving after a successful send~~ · **FIXED**

**My hypothesis in this document was wrong, and the real cause was worse.** Recorded in full
because the wrong answer was plausible and someone will reach for it again.

**What I predicted.** That `test/eventSource.ts` returns on a clean stream end without emitting
`error`, so `lib/sse.ts` could never fire its resume. **Ruled out:** `bus.publish` never sends
`None` and `publisher()` only exits on client disconnect, so the server never closes a stream on
its own. There was no clean close to mishandle.

**What it actually was.** Traced with `WA_SSE_DEBUG=1` on both the transport and the forwarder:

```
fwd #31 headers    200 text/event-stream
fwd #31 body-chunk 984B          <- the ENTIRE turn in one chunk
sse #2  frame      done id=      <- idle done
sse #2  frame      token id=4 .. chips id=6, usage id=7, done id=8
fwd #32 headers    202           <- the POST's own response, still being unwrapped
```

An interview turn is two tokens and a chip row, so the server finishes it — and the stream
delivers every frame including the terminal `done` — while the client is still unwrapping the
HTTP response to its own `POST .../messages`. `noteSend` then dispatches `turn-started`, which
**unconditionally re-armed `phase: "streaming"` on a turn that had already ended.** Nothing
remained to move the phase on. `ConversationScreen` disables the composer and the chip dock off
`isStreaming`, so the UI locked with a spinner up and nothing coming.

That is why it was intermittent, and why it hit **only** FR-13: every other test drives a
*recommend* turn (50 tokens, 5 cards, ~600 ms), so the POST always won the race. The fastest turn
in the product was the one that hung. Against instant mocks the frames always arrive after the
send resolves, so the ordering never occurred.

**Fixed in `lib/reducer.ts`.** `turn-started` no longer re-arms a turn whose terminal frame it has
already applied — answerable, not guessable, because `token` and `done` frames carry `turn_id`.

- [x] Instrument the transport — added `WA_SSE_DEBUG=1` tracing to `eventSource.ts` and
      `realBackend.ts`; env-gated and kept, since this class of bug is only visible as a timeline
- [x] Decide harness vs product — **product**, in the reducer. Reproduced at the pure transport
      level with no React, no MSW and no jsdom, which is what ruled the harness out
- [x] Fix the shim anyway: a clean body end now signals `error` through one `fail()` path. A
      latent defect rather than this one — real `EventSource` does fire on close — and the app's
      resume genuinely could not have fired without it
- [x] Close every source in `afterEach` so no stream leaks across tests
- [x] `clickChip` helper: `ChipDock` is correctly `disabled` between the `chips` and `done`
      frames, and `userEvent.click` on a disabled button silently does nothing, so the original
      test clicked into the void and waited out its own timeout. It now waits for *enabled* and
      re-queries, which turned a silent 45 s stall into an honest failure and was how the
      reducer bug became visible at all
- [x] **10 consecutive green runs** — slowest test 1,268 ms, down from 25,000–45,000 ms

**A side effect worth knowing:** I first "fixed" this by making the server's idle `done`
unconditional, which broke 10 SSE tests. Those tests are right — a reader that treats `done` as
terminal stops before the turn begins, exactly as the original comment in `turns.py` warns.
Reverted; `turns.py` is untouched.

### D2 — ~~P1 · Rate limits make the real suite non-repeatable~~ · **FIXED**

429s appeared once the accumulated request count climbed (`POST /conversations` → 429,
`GET /readyz` → 429). Defaults are `rate_limit_reads_per_min: 120` and `turns_per_min: 30`
([config.py](../backend/src/wines_ai/config.py)). The backend's own
[conftest.py](../backend/tests/conftest.py) already raises these to 2000/500 for exactly this
reason — but the command documented in [frontend/README.md](../frontend/README.md) does not.

- [x] Added to the documented command in `frontend/README.md` and §4 below, with a note that the
      overrides are not optional and why — 429s surface as unrelated-looking failures
- [x] Confirmed **not** the cause of D1: the stalls reproduced 3 runs in 6 with the limits raised
- [ ] **Still open:** whether the dev default of 120 reads/min is too tight for a real browser
      session, where the taste panel, sidebar and usage badge each poll. Needs §5

### D3 — ~~P2 · `title` is unbounded on the wire~~ · **FIXED**

`CreateConversationRequest.title` and `PatchConversationRequest.title`
([schemas.py:65-71](../backend/src/wines_ai/schemas.py#L65-L71)) are bare `str | None` with no
length constraint. Verified live: a 500-character title is accepted and stored at full length by
both `POST /conversations` (201) and `PATCH /conversations/{cid}` (200).

Meanwhile `title_max_chars = 52` is enforced only on *auto-generated* titles in
[turns.py](../backend/src/wines_ai/api/v1/turns.py), and the frontend caps its rename box at
`TITLE_MAX_CHARS = 52`. So the limit holds everywhere except where a client supplies the value —
which is the one place it needs to.

For contrast, `SendMessageRequest.content` **is** bounded (`max_length=2000`) and correctly
returns 422 on 5000 characters. Titles should match that pattern.

- [x] Validated in the route rather than via `Field`, so the configurable `title_max_chars` is
      honoured at runtime instead of being frozen into the schema
- [x] 422 `title_too_long` with a stable code, refused rather than truncated
- [x] **A second defect at the same site:** `repo.patch` writes any non-`None` title, so
      `{"title": ""}` blanked the sidebar entry with no way back. Now 422 `title_blank` —
      omitting the field is how you leave a title alone. Titles are also trimmed
- [ ] **Still open:** assert the sidebar renders a 52-char title without breaking layout. Needs §5

### D4 — ~~P3 · The real suite hardcodes the seed artifact~~ · **FIXED**

[App.real.test.tsx](../frontend/src/app/App.real.test.tsx) asserts `45 rows · seed-0.1`,
`/w-\d{4} · seed-0\.1/`, `not yet reviewed`, and the empty-producer copy. All correct against the
seed; **all fail against the `demo-0.1` artifact** added in backend-todo §17, where cards carry
producers and read `example data`.

- [x] The suite now reads `/meta/dataset-version` in `beforeAll` and derives the version, row
      count and expected review badge from it, mapping the status through the client's own
      `REVIEW_BADGE`. FR-11 is asserted as "the producer section is never blank, and unsigned
      names always carry the caveat", which holds for either artifact
- [x] Verified green against **both** `seed-0.1` and `demo-0.1`, 3 runs each
- [ ] **Still open:** wire the demo-artifact run into CI so both stay served

---

## 4. The commands (corrected)

```bash
# backend — note the rate limits, which the README currently omits (D2)
cd backend
WA_RATE_LIMIT_READS_PER_MIN=2000 WA_RATE_LIMIT_TURNS_PER_MIN=500 \
  .venv/bin/python -m uvicorn wines_ai.main:app --port 8001

# frontend against it, mocks off
cd frontend
VITE_USE_MOCKS=false VITE_BACKEND_ORIGIN=http://127.0.0.1:8001 npm run dev

# the real-backend suite
WA_REAL_BACKEND=1 WA_BACKEND=http://127.0.0.1:8001 npx vitest run src/app/App.real.test.tsx
```

Add `WA_DATASET_PATH=$PWD/src/wines_ai/dataset/seed/wines.demo.json` to the backend command to
serve populated producers.

---

## 5. The browser pass — still the biggest untested surface

Nothing in this project has ever been rendered in a browser. jsdom asserts structure; it cannot
see layout, contrast, focus rings, or a stream that visibly jitters. Every item below is
unverified, not merely unpolished.

- [ ] Run it. Age gate → interview → cards → refine → abstention, against the real backend
- [ ] Watch one real stream land: no layout shift as cards arrive, cursor behaves, Stop works
      mid-turn and the partial answer stays
- [ ] Pull the network mid-answer and watch resume: the lead-in must reappear **whole and once**
- [ ] Responsive at 375 / 768 / 1280 / 1920
- [ ] Keyboard-only: full interview without a mouse; visible focus throughout
- [ ] Screen-reader pass on streaming text and the card list
- [ ] Lighthouse; check the 525 KB / 165 KB-gzipped bundle against a cold load
- [ ] Known gaps carried over: sidebar rename/archive/delete refetch instead of updating
      optimistically; a blocked refine shares the abstention frame

---

## 6. Sequence

1. **D2** first — one line, and without it every later measurement is unreliable
2. **D1** next — instrument, then decide harness vs product, then fix, then 10 green runs
3. **§5 browser pass** — likely moves D1 from "suspected harness bug" to "proven"
4. **D3**, **D4** — small and independent; do them while the browser pass is open
5. Re-run everything: backend `pytest` + `ruff`, frontend `test` + `typecheck` + `eslint`, real
   suite 10×, both artifacts

## 7. Open questions

1. ~~**Does the stall reproduce in a real browser?**~~ **Moot — it was neither of the two things
   this question offered.** It was a genuine product bug in the reducer, reproduced at the pure
   transport level with no browser involved. `lib/sse.ts` was never touched. See D1.
2. ~~**Which artifact is the default for the browser pass?**~~ The suite no longer cares: it
   derives its assertions from whatever is served, and is verified against both. For a demo I
   would still serve `demo-0.1`.
3. ~~**Should an over-long title 422, or should the client just prevent it?**~~ **422**,
   implemented. Silently rewriting a name someone typed is worse than refusing it.
4. **Is 120 reads/min the right dev default** for a browser session where the taste panel,
   sidebar and usage badge each poll? Still open, and only §5 can answer it. The test overrides
   do not change the dev default, deliberately — raising it to make tests pass would have hidden
   a real question about the product.

---

## 8. What is left, and what I could not do

**I have no browser tooling in this session**, so every §5 item is untouched. That is now the
only material gap: the integration itself is done and holds under repetition, but nothing has
been *looked at*. Three §3 leftovers also need a screen — the 120 reads/min question (D2), the
52-character title in the sidebar (D3), and the CI wiring for the demo artifact (D4).

### Verified on completion

| | |
|---|---|
| Backend | **125 passed** (was 122), ruff clean |
| Frontend offline | **62 passed** (was 59), `tsc -b` clean, eslint clean, build 165.89 kB gzipped |
| Real-backend suite | **10/10 consecutive green**, slowest test 1,268 ms (was 25,000–45,000 ms) |
| Both artifacts | `seed-0.1` and `demo-0.1`, 3 runs each |

### Changed

| File | Why |
|---|---|
| `frontend/src/lib/reducer.ts` | **The fix.** `turn-started` no longer re-arms a finished turn |
| `frontend/src/lib/reducer.test.ts` | 3 tests pinning the late-`turn-started` ordering |
| `frontend/src/test/eventSource.ts` | `WA_SSE_DEBUG` trace; clean body end now signals `error` via one `fail()` path |
| `frontend/src/test/realBackend.ts` | `WA_SSE_DEBUG` trace on the forwarder |
| `frontend/src/app/App.real.test.tsx` | `clickChip` helper, `afterEach` stream cleanup, assertions derived from the served artifact |
| `frontend/README.md` | Rate-limit overrides, demo-artifact command, test count |
| `backend/src/wines_ai/api/v1/conversations.py` | `_checked_title`: 422 on too-long and on blank, trims |
| `backend/tests/test_api.py` | 3 title tests |

`backend/src/wines_ai/api/v1/turns.py` is **unchanged** — see the note at the end of D1.
