# Wines AI — Frontend

Lane 1 of `wines-ai-technical-architecture.excalidraw`: React 19 + TypeScript + Vite,
the conversation UI, the recommendation cards, and the trust surfaces that make the
dataset honest about itself.

**It runs with no backend, no API key and no network.** Every endpoint is mocked at the
network boundary by MSW, and the mock is a port of the real serving path over the real
45-row seed dataset — so the interview, the recommendations, the refine chips and
FR-13's abstention all actually work rather than replaying a canned transcript.

---

## Run it

```bash
npm install
npm run dev            # http://localhost:5180
```

Then: `/` to start a conversation, `/dev/styleguide` for every token, component and
state on one page (including a button that drops the SSE stream mid-sentence so the
resume path can be exercised on demand).

```bash
npm run build          # tsc -b && vite build
npm run typecheck
npm test               # 59 tests
npm run lint
npm run format
```

The suite is offline by default. To run the app tests against a real FastAPI as well:

```bash
cd ../backend && WA_RATE_LIMIT_READS_PER_MIN=2000 WA_RATE_LIMIT_TURNS_PER_MIN=500 \
  .venv/bin/python -m uvicorn wines_ai.main:app --port 8001
WA_REAL_BACKEND=1 WA_BACKEND=http://127.0.0.1:8001 npx vitest run src/app/App.real.test.tsx
```

**The rate-limit overrides are not optional.** The dev defaults are 120 reads/min and
30 turns/min per IP, and one pass of this suite plus the polling the app does on mount
(usage, dataset version, sidebar) gets close enough that a second consecutive run
starts taking 429s — which surfaces as unrelated-looking test failures rather than as a
rate-limit error. `backend/tests/conftest.py` raises the same two values for the same
reason.

### Point it at the real backend

```bash
cd ../backend && uv run python -m wines_ai     # http://127.0.0.1:8010
VITE_USE_MOCKS=false npm run dev
```

If 8010 is taken (the backend's `__main__` hardcodes it), run uvicorn on another port
and point the proxy at it:

```bash
cd ../backend && .venv/bin/python -m uvicorn wines_ai.main:app --port 8001
VITE_USE_MOCKS=false VITE_BACKEND_ORIGIN=http://127.0.0.1:8001 npm run dev
```

To serve populated producer names instead of FR-11's empty lists, add the demo
artifact (see backend-todo §17 — the names are illustrative and report as `fixture`):

```bash
cd ../backend && WA_DATASET_PATH="$PWD/src/wines_ai/dataset/seed/wines.demo.json" \
  .venv/bin/python -m uvicorn wines_ai.main:app --port 8001
```

Vite proxies `/api` → `127.0.0.1:8010`, so there is no CORS in dev and no base URL to
switch in the client. `fetch` already sends `credentials: "include"` and `EventSource`
is already constructed with `withCredentials: true`, because the session and age-gate
cookies are httpOnly and the mocks were built to need the same thing.

---

## What the UI is made of

```
src/
├── app/            router (five routes), providers, AppShell
├── components/
│   ├── agegate/    FR-1, blocking, re-entered on a 403
│   ├── shell/      sidebar, top bar, error boundary, offline banner
│   ├── conversations/  grouped list, search, rename, archive, delete
│   ├── thread/     transcript, streaming text, turn details
│   ├── composer/   textarea, send/stop, character budget
│   ├── chips/      the live row (docked) and the record of older rows
│   ├── cards/      the recommendation card and its parts
│   ├── trust/      dataset badge, stale version, usage, degraded
│   ├── taste/      the profile panel and its provenance tags
│   └── states/     abstention, out of scope, 404, dataset unavailable
├── hooks/          queries, the stream, the send, shortcuts, breakpoints
├── lib/            api · sse · reducer · thread · problem · format
├── mocks/          engine/ · handlers/ · db · stream · fixtures
└── styles/         theme.css (every token) · globals.css
```

### Three rules the code keeps

1. **No wine vocabulary outside `src/mocks/`.** Every label, level, hedge, prompt and
   chip comes from `GET /meta/taste-axes` or from a `chips` frame. `src/mocks/` is the
   exception because it stands in for the server, not for the client — delete it and
   the app still works against FastAPI.
2. **No raw hex outside `styles/theme.css`.** Tokens are Tailwind v4 `@theme` entries,
   so each is both a custom property and a utility. `grep '#' src/components` is empty.
3. **No score, rating, rank, price, vintage or purchase path**, and never the word
   "dry" in anything a user reads. These are BRD §8, and a test asserts each of them
   against the rendered card rather than trusting the next person to remember.

---

## The four things that are subtle

All four come from the backend's actual behaviour, and all four are the kind of thing a
conventionally-built chat client gets wrong. `lib/reducer.ts` and `lib/sse.ts` carry
the long comments; the short version:

1. **The stream is per-conversation and long-lived.** `POST …/messages` returns
   `{turn_id}` and no content. Built the usual way — POST and read the response — this
   client would render nothing at all.
2. **A text run is keyed by its anchor seq.** Live it arrives as many `token` frames
   sharing one `anchor_seq`; persisted it is one text part at exactly that seq. Keying
   on the anchor is what lets the transcript and the live stream merge by seq with no
   flicker and no duplication, and resuming mid-run means `?after=anchor_seq - 1`
   **after discarding** what is held from the anchor on.
3. **`done` with `status: "idle"` is what stops the spinner** on a conversation that
   has already finished. It carries no `id:`, so it must not move the resume cursor.
4. **The resume cursor must never drop below the client's own last user part.** A
   replayed part carries no role, so a user's text replays as a `token` frame and
   would be rendered in the assistant's voice. The stream is therefore opened at the
   transcript's high-water mark, and a floor is raised on every send.

---

## Mocks

`src/mocks/engine/` is a port of `turns/deterministic.py`, `taste/ranking.py`,
`taste/interview.py`, `taste/refine.py` and `taste/copy.py` over
`fixtures/wines.seed.json` — the backend's seed artifact, copied in byte for byte. A
test asserts it still has 45 rows, every style, no producer names and no claim of
review, so a fixture edit that invents data fails loudly.

`src/mocks/stream.ts` mirrors `services/runner.py`: one seq allocator per conversation,
text coalesced into one part per run, the live buffer attached behind the replay, the
idle `done`, one in-flight turn per conversation, and cancellation that stops mid-word.

The seeded conversations are **generated by the engine**, not written by hand, and
between them cover a full three-question interview, a refine chain, the abstention, an
out-of-scope question, an interview still in progress with inferred slots, a stale
dataset version, and an archived conversation.

`window.waMock` (dev only) drives it: `dropStream()`, `forceNext(code)`,
`setReady(false)`, `reseed()`. The styleguide has a button for each.

---

## Known gaps

- Sidebar rename, archive and delete refetch rather than updating optimistically. They
  are correct and they report failure; they are just not instant.
- A blocked refine shares the abstention's frame. The two are structurally identical on
  the wire and the client will not guess between them by reading the text.
- Per-turn diagnostics only exist for a turn this client watched run: the transcript
  carries no usage, so a reloaded conversation shows none.
- The responsive layout, a real screen-reader pass and Lighthouse have not been run in
  a browser. Breakpoints, focus management and the live region are built; they are
  unverified against an actual screen.

## End-to-end tests (Playwright, real backend + LLM)

```bash
cd ../backend && WA_TURN_CACHE_ENABLED=false uv run python -m wines_ai   # :8010
VITE_USE_MOCKS=false npx vite --port 5181                              # real-backend UI
npm run e2e                                                            # e2e/*.spec.ts
```

Output goes to `$TMPDIR/wines-ai-e2e` (override with `E2E_OUT`). It must stay outside
`frontend/`: Vite watches this folder and reloads the page whenever a trace is written.
Card citations are checked against `backend/.../wines.seed.json` plus
`backend/data/ingested_tastes.jsonl`. Each run spends a few cents on the live provider.
