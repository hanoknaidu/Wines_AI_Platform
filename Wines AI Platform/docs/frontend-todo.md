# Wines AI — Frontend Implementation To-Do

> **Status: built. Phases 0–9 complete.** `cd frontend && npm install && npm run dev`. 49 tests pass offline (`npm test`), typecheck and lint are clean, and the production build is 165 KB gzipped with the mock layer and the dataset stripped out of it. Seven of those tests drive the whole app end to end against the mocks — age gate, sidebar, a typed opener, a streamed turn, a refine, the abstention, a rename.
>
> **It has also been run against the real FastAPI backend** (§14), which is where the "swapping is one flag" claim stops being a claim. What is **not** done is listed in §12, and `frontend/README.md` repeats it for whoever opens the folder next.
>
> **Scope of this phase: UI only.** No backend work, no orchestration, no AI layer. Every network call is mocked at the network boundary, and the mock answers the endpoints the FastAPI backend in `backend/` already serves — so pointing the finished UI at the real thing is one env flag, not a refactor.
>
> **Lane 1 of `wines-ai-technical-architecture.excalidraw`.** The diagram specifies this client in some detail (React 19 + TS + Vite, the sidebar's grouping, the card's contents, the chip vocabulary, the four routes, the resume rule). Where it is specific I follow it; where it is silent I decide and say so.
>
> v0.1 · 2026-10-22 · supersedes nothing

---

## 1. Ground Rules

1. **Light theme only, and warm rather than clinical.** Your one constraint. Tokens are structured so dark can be added later without touching a component, but no dark mode ships in this phase.
2. **Mock at the network boundary, not in components.** Components call the same surface the real backend exposes (§7). No component imports a fixture, ever.
3. **No wine vocabulary in the client.** Every label, level, hedge, prompt and refine chip arrives from `GET /meta/taste-axes` or from the `chips` SSE frame. `"Not sweet at all"` is never a string literal in a component. This is the backend's rule (`taste/axes.py`, README note 6) and it is the one rule that survives lane 3 replacing the engine.
4. **Nothing fake-looking, and nothing invented.** The fixtures *are* the real seed dataset — `backend/src/wines_ai/dataset/seed/wines.seed.json`, copied in verbatim, 45 rows. Which means `example_producers` is empty on every row and `review_status` is `unreviewed` on every row, exactly as it will be in the demo. I will not hand-write a producer name to make a card look fuller; that is the one field the BRD calls the weakest link (§8, FR-11), and a plausible fake would look like real data the moment it rendered.
5. **Every state gets designed**, not just the happy path: empty, loading, streaming, stopped, resumed-after-drop, no-match abstention (FR-13), out-of-scope, blocked refine, unreviewed dataset, stale dataset version, rate-limited, dataset-unavailable, age-expired, offline.
6. **Keyboard-first, WCAG 2.1 AA.** Chips are real buttons, the stream is announced through a live region, focus is managed on every overlay.
7. **The UI never implies a verdict.** See §3.6 — the prohibitions matter more here than the palette.

---

## 2. Decisions Made — Overrule Any of These

You gave me a free hand, so these are decided rather than asked. Each is cheap to reverse now and expensive after Phase 5.

| Area | Choice | Why |
|---|---|---|
| Framework | **React 19 + TypeScript + Vite**, strict | The diagram's lane 1, verbatim |
| Styling | **Tailwind CSS v4 `@theme`**, no `theme.ts` | One source of truth consumed two ways. Same call as Legal Lens, for the same reason |
| Components | **Radix primitives, copied in** (shadcn-style) | Focus traps, ARIA and keyboard nav come free; not a dependency we are locked into |
| Server state | **TanStack Query** | The diagram names it. Conversation list, transcript, taste-axes, dataset-version, usage |
| Client state | **Zustand** | Sidebar collapse, panel state, composer draft, the SSE reducer's live buffer |
| Routing | **React Router** | Conversation URLs must be shareable |
| API mocking | **MSW**, including a real streamed SSE response | Swapping to FastAPI is a base-URL change. A fake transport inside the app would let the resume logic go untested, and resume is the subtlest thing in this client |
| Mock recommender | **A ~150-line TS port of the deterministic engine** | So interview → recommend → refine → abstain all actually work against the 45 real rows. A canned transcript cannot exercise refine, and refine is a core feature |
| Wire casing | **`snake_case`** | Answers backend §15 Q1. The diagram writes `turn_id`, `row_id`, `dataset_version`; I type `types/api.ts` against that and we leave `WA_WIRE_CASE` alone |
| Markdown | **None** | Assistant prose from this engine is plain sentences, and cards are structured data, not markdown. Adding a renderer would be the only place XSS could enter. Revisit when lane 3's Sonnet copy lands |
| Fonts | **System stacks only**, no webfont | NFR-4's posture is no outbound calls at runtime; a Google Fonts link would break that in the client while the backend holds the line. A serif is used for tasting notes — `ui-serif, Georgia` is good enough and costs nothing |
| Motion | CSS transitions, no animation library | This UI needs restraint |
| Icons | `lucide-react` | Consistent 1.5px stroke, tree-shaken |
| Tests | Vitest + RTL on the logic-bearing parts: the SSE reducer, the resume cursor, the mock engine's ranker | Full E2E waits for a backend to point at |

---

## 3. Design System

**Direction: warm, editorial, quiet.** A wine recommendation is a suggestion from someone who knows more than you, offered without condescension — so the surface should feel like good printed matter, not a dashboard. Closer to Claude's warm canvas than to OpenAI's cool grey, and much closer to both than to anything with a bottle-shaped logo and a gold foil gradient. Generous whitespace, 1px borders instead of drop shadows, one accent colour used sparingly.

The thing to avoid is wine-kitsch: maroon chrome, serif everything, grape imagery. The palette is warm and the accent is garnet, but it appears on roughly 5% of the pixels.

### 3.1 Colour tokens

```css
/* neutrals — warm, paper-like */
--canvas:         #FAF8F5;   --surface:        #FFFFFF;
--surface-sunken: #F2EEE8;   --border:         #E6E0D8;
--border-strong:  #D2C9BC;
--text:           #1C1917;   --text-muted:     #57534E;   --text-subtle: #857E75;

/* brand — garnet: warmth and authority, no purple */
--brand-900: #4A1324;  --brand-700: #6B1B30;  --brand-600: #8A2440;
--brand-500: #A8384F;  --brand-100: #F7E4E7;  --brand-50:  #FCF3F4;

/* style accents — dots, tints and borders ONLY (see the rule below) */
--style-red:       #8A2440;
--style-white:     #96761B;
--style-rose:      #C05470;
--style-sparkling: #46707F;
--style-dessert:   #8A5520;

/* semantic */
--ok-fg:      #15803D;  --ok-bg:      #F0FDF4;  --ok-br:      #BBF7D0;
--caution-fg: #92400E;  --caution-bg: #FFFBEB;  --caution-br: #FDE68A;
--danger-fg:  #991B1B;  --danger-bg:  #FEF2F2;  --danger-br:  #FECACA;
--info-fg:    #1D4ED8;  --info-bg:    #EFF6FF;  --info-br:    #BFDBFE;

/* shadows — two, both subtle */
--shadow-sm: 0 1px 2px rgb(28 25 23 / 0.06);
--shadow-md: 0 8px 24px rgb(28 25 23 / 0.12);
```

Two rules this palette exists to enforce:

**Style accents never carry text.** `--style-rose` is 4.0:1 on white, under AA for small text, and relying on five hues to distinguish five styles fails anyone colour-blind regardless of contrast. So an accent only ever tints a 8px dot, a 1px border or a 6%-alpha background, and the style is *always* also spelled out in words beside it. Colour never carries meaning alone.

**Amber means "needs your attention", so a hedge must not borrow it.** `review_status: unreviewed` and a degraded engine are amber. A low-confidence axis reading is *not* — it is the system being honest on a normal day, and painting it amber would teach the user that honesty is a warning. Hedged readings get a dotted underline and `--text-subtle`; see §3.6.

### 3.2 Type

System stacks, two of them, used for different jobs.

```css
--font-ui:    ui-sans-serif, -apple-system, "Segoe UI", Inter, Roboto, sans-serif;
--font-note:  ui-serif, Georgia, "Iowan Old Style", "Times New Roman", serif;
```

| Role | Size / line-height / weight |
|---|---|
| Variety name (the primary answer) | 22 / 1.25 / 600 |
| Thread prose, assistant and user | 16 / 1.65 / 400 |
| Tasting note — "what it tastes like" | 16 / 1.6 / 400, `--font-note` |
| Why it matches | 15 / 1.6 / 400 |
| Chip, axis label, pill | 13 / 1.4 / 500 |
| Provenance footer, row id | 12 / 1.4 / 400, tabular numerals |

The serif is load-bearing, not decoration: the tasting note is the one field drawn verbatim from the dataset, and setting it in a different voice from the generated-sounding prose around it tells the user — without a label — that it was written down beforehand.

### 3.3 Space, shape, motion

4px base; the scale is 4/8/12/16/24/32/48. Radii: controls 8, cards 12, chips 999, modal 16. Borders over shadows everywhere except popovers (`--shadow-sm`) and modals (`--shadow-md`). Transitions 140ms ease-out, the streaming cursor blinks at 1s, and `prefers-reduced-motion: reduce` disables all of it including the cursor.

### 3.4 Layout

```
┌────────────┬──────────────────────────────────────┬──────────────┐
│  SIDEBAR   │  TOP BAR  52px                       │  TASTE PANEL │
│  288px     ├──────────────────────────────────────┤  300px       │
│            │                                      │              │
│  + New     │   THREAD  —  760px max, centred      │  Your taste  │
│  search    │   · prose, chips, cards              │  so far      │
│  Today     │                                      │              │
│  Last 7d   │                                      │  Dataset     │
│  Older     ├──────────────────────────────────────┤  This turn   │
│            │   COMPOSER  sticky, 760px max        │              │
└────────────┴──────────────────────────────────────┴──────────────┘
```

- **Sidebar** 288px, collapsible to nothing; a drawer below 900px.
- **Thread** capped at 760px — a reading measure, not a full-width stretch. Cards fill the column as a single vertical list; a grid would cramp 3–5 cards that are meant to be read, and would invite a side-by-side comparison the product deliberately does not offer.
- **Taste panel** 300px right rail, open by default ≥1280px. Below that the same panel opens as a right-hand drawer from the top-bar toggle, so the control always does something rather than going dead on a laptop.
- **Top bar** 52px: sidebar toggle · conversation title with inline rename · dataset badge · taste-panel toggle.

### 3.5 Styling architecture — Tailwind `@theme`, not a `theme.ts`

Tokens live once, in `styles/theme.css` under `@theme`, which makes each one both a CSS custom property and a Tailwind utility (`bg-canvas`, `text-muted`, `border-strong`). A parallel `theme.ts` would be a second source of truth that drifts the first time someone is in a hurry. The rule: **components use utilities; raw hex never appears outside `theme.css`.** A grep for `#` in `src/components` returning anything is a bug, and `/dev/styleguide` renders every token so drift is visible rather than theoretical.

### 3.6 What this UI must never do

Design prohibitions, each from BRD §8. These are not stylistic preferences; getting one wrong turns the product into the thing it was built to replace.

| Never | Because |
|---|---|
| A match score, a star rating, a "94% fit" badge, or a points number | The product recommends **fit, not quality**, and a number reads as a verdict. The ranking distance exists in the engine and must not surface as a figure |
| Ordinal ranking language — "best match", "#1", "top pick" | Same reason. The cards are a set of starting points, not a leaderboard. They are a list, and the list is not numbered |
| A price, a price range, or a currency symbol | Out of scope entirely (BRD §8). There is no field for it and no placeholder for it |
| A buy button, a cart, a "find a shop" link, a stockist | No purchase path. DTC alcohol shipping is a compliance project |
| A vintage year on a card | Not in the dataset. A card names a grape and a producer to look for |
| The word "dry" in any user-facing string | `taste/axes.py` enforces this server-side and a unit test asserts it. The client must not reintroduce it in a tooltip, a placeholder or an empty state |
| Health framing, in either direction | No "good for your heart", no lecture |
| Any imagery of a person drinking, or anything that reads as marketing to minors | Regulated-product posture |
| An invented producer name, even in a loading skeleton | The skeleton shows shaped grey blocks, never sample text |

---

## 4. Feature Inventory

Derived from the diagram's lane 1, the BRD's FRs, and the endpoints the backend actually serves.

**A · Age gate (FR-1)** — `/age`, blocking, not dismissible. Explicit 21+ confirmation, a responsible-consumption line, no imagery. Re-entered automatically on a `403 age_not_confirmed` from any call, because the cookie can expire mid-session.

**B · Shell** — collapsible sidebar, top bar, taste panel, toast host, error boundary, offline banner, readiness gate.

**C · Conversations** — list grouped Today / Last 7 days / Older, title auto-named from turn 1 (52 chars then `...`), search box, new chat, inline rename, archive, delete with confirm, archived view, active highlighting, cursor-paged infinite scroll at 20.

**D · Thread** — user and assistant turns rebuilt from message parts, streaming prose with a cursor, stop, scroll-to-bottom when the user has scrolled up, per-turn intent and latency available but not shouted, and a first-run empty state that says what this is and what it will ask.

**E · Composer** — auto-growing textarea, `Enter` to send and `Shift+Enter` for a newline, 2000-char limit with a counter that appears at 1800, send/stop toggle, and every disabled reason surfaced in words ("a turn is already running", not a dead button).

**F · Interview chips** — option buttons emitted by the interview step, so a novice never types a wine word. The latest message's chips are live; chips on older messages render as a record of what was chosen, so the transcript reads as a history rather than a field of stale buttons.

**G · Refine chips** — the eight adjustments, attached under a result set, re-ranking without re-interviewing. A blocked refine ("I cannot go further that way") is its own state with the remaining options still offered.

**H · Recommendation card** — the centrepiece. Variety name, style dot + word, tasting note in serif, "why it matches" in the user's own words in a tinted callout, axis readings (asked axes as 3-step meters, unasked as a compact line), typical-region pills, example producers *or* the honest empty line, and a provenance footer carrying `row_id` · `dataset_version` · `review_status`, with thumbs up/down.

**I · Trust surfaces** — dataset badge (`45 rows · seed-0.1 · unreviewed`) with a popover explaining where the data comes from and what has not been reviewed; a stale-version notice when `dataset_version_stale`; a "how this works" panel; a per-turn details disclosure (intent, latency, cache hit, cost) kept discreet.

**J · Taste panel** — the three asked slots filling as the interview proceeds, each marked by how it was learned: **asked** (you chose it), **inferred** (read from what you typed), **refined** (adjusted after results). The unasked four appear once a refine touches them. This exists because `taste_profile.confidence` carries `provenance` and showing it is the cheapest honesty in the product — it also lets the user catch a wrong inference immediately.

**K · States** — skeletons not spinners; abstention (FR-13) styled as an answer rather than an error; out-of-scope replies rendered plainly; `error` SSE frame as an inline notice that keeps whatever already streamed; the full error-code map in §6.6.

**L · A11y** — landmarks, `aria-live="polite"` on the streaming region with a politeness budget so a long stream does not machine-gun a screen reader, focus returned on every overlay close, visible focus rings, AA contrast verified in the styleguide.

---

## 5. Routes

The diagram's four, plus a styleguide.

| Route | Screen |
|---|---|
| `/` | Redirect → most recent conversation, else a new one |
| `/age` | Age gate. Every other route redirects here until the cookie is set |
| `/c/:conversationId` | The conversation |
| `/dev/styleguide` | Every token, component and state on one page. Dev-only, stripped from a production build |
| `*` | 404 |

---

## 6. The Backend Facts That Shape This UI

The nuanced part. Eight things about the API that a conventional chat client gets wrong, each with the UI consequence. They come from reading `api/v1/`, `services/runner.py` and the backend README's "Notes for the frontend".

### 6.1 The stream is per-conversation and long-lived, not per-turn

`POST /conversations/{cid}/messages` returns `{turn_id, user_message_id, seq}` and **no content**. Content arrives on a `GET /conversations/{cid}/stream` that was already open. So `EventSource` is opened when the conversation mounts and lives for as long as it is on screen — not opened per send. A client built the usual way (POST, read the response body) would render nothing at all.

### 6.2 Resume is exact, and `anchor_seq` is the detail that matters

Every frame carries `id: {seq}`. Reconnect with `?after={lastSeq}` and the server replays committed parts. But a `token` frame also carries `anchor_seq` — the seq of the **first** token of the current text run — and the rule is: if the drop happened mid-run, reconnect with `?after={anchor_seq - 1}` so the whole run replays as one text frame. Reconnecting with the last token's seq instead resumes into half a sentence that can never be completed. The reducer therefore tracks two cursors: `lastSeq` for frames and `anchorSeq` for the run in progress.

### 6.3 `done` with `status: "idle"` is what stops the spinner

Open the stream on a finished conversation and the server replays the transcript, then sends a `done` frame with `status: "idle"` and **no `id:`** (so it must not move the resume cursor). Without handling it, a client renders the transcript and then waits on a spinner forever — the backend's comment says so explicitly. Equally, that frame only arrives when something *was* replayed: a brand-new conversation gets no idle frame, so "no idle frame yet" cannot mean "still loading".

### 6.4 Sending is idempotent, and one turn at a time

Every send needs an `Idempotency-Key` header or it is rejected with `400 idempotency_key_required`. One uuid per send, **reused on retry** — a retry with a fresh key would start a second turn, and a retry with the same key and different content gets `409 idempotency_key_reused`. A second concurrent send gets `409 turn_in_flight`. So: the key is minted when the user hits send and held with the pending turn; the composer switches to **Stop** (`POST /turns/{turn_id}/cancel`) while a turn runs rather than queueing; a double-click cannot pay twice.

### 6.5 Six frame kinds, and the order is meaningful

`token` · `card` · `chips` · `citation` · `usage` · `done`, plus `error`. A turn arrives as: prose tokens, then cards one at a time, then a citation frame, then the chips. The reducer appends to the current text run until a non-token frame closes it, which means **cards appear after their lead-in sentence has finished streaming** — the layout must absorb that without the composer jumping. A `usage` frame always arrives, even on failure, and `done` always closes.

### 6.6 Errors are `problem+json` with a stable `code`, and each gets its own state

NFR-7: no stack trace reaches a user. Every failure has a designed destination.

| Code / status | UI |
|---|---|
| `age_not_confirmed` 403 | Redirect to `/age`, return to the conversation after |
| `conversation_not_found` 404 | "This conversation is gone" with a new-chat action; drop it from the sidebar cache |
| `turn_in_flight` 409 | Should be unreachable — the composer is already disabled. If it happens, surface it and offer Stop |
| `idempotency_key_required` / `_reused` 400/409 | A client bug. Toast with the `request_id`, and recover by minting a fresh key for a genuinely new send |
| `dataset_unavailable` 503 | Full-screen "recommendations unavailable", poll `/readyz`, recover automatically. The one failure where the product cannot answer at all |
| `engine_unavailable` 503 | Only reachable if someone sets `engine=orchestrated`. "That engine is not installed in this build" |
| `validation_error` 422 | Inline on the composer |
| 429 | "Too many turns in a minute" with a countdown; the limit is 30/min |
| `internal_error` 500 | Inline notice carrying the `request_id`, nothing more |
| `error` SSE frame | Inline in the thread under whatever already streamed. Never discards partial content |

### 6.7 Three card states that are data, not bugs

`example_producers: []` is the honest state (FR-11) and gets a sentence — *"No producers listed: names are verified in review or removed."* — not a hidden section and not a skeleton. `review_status: "unreviewed"` is true of all 45 rows today and gets an amber badge plus one line of explanation in the dataset popover. And a per-axis `confidence` below `confidence_threshold` (0.75) means the server already sent a hedged `label` — *"likely sweet"*, not *"sweet"* — so the client renders `label` verbatim and marks it as hedged; it never recomputes the hedge, and never upgrades the wording.

### 6.8 Sidebar search is titles only

`?q=` is a title substring filter; message bodies need an FTS5 table that does not exist. So the no-results copy says so — *"No conversation titles match. Search does not cover message text yet."* — rather than implying the archive was searched.

---

## 7. Mock API Contract

MSW handlers implement exactly the backend's surface, at the same paths, with the same status codes and the same `problem+json` shape.

```
POST   /api/v1/age-gate                         204, sets the cookie
GET    /api/v1/healthz · /readyz                liveness · dataset-loaded readiness

POST   /api/v1/conversations                    201 ConversationSummary
GET    /api/v1/conversations?cursor=&limit=&archived=&q=   200 ConversationPage
GET    /api/v1/conversations/{cid}              200 ConversationDetail (transcript + taste_profile)
PATCH  /api/v1/conversations/{cid}              200 rename · archive
DELETE /api/v1/conversations/{cid}              204 soft delete

POST   /api/v1/conversations/{cid}/messages     202 {turn_id, user_message_id, seq}
GET    /api/v1/conversations/{cid}/stream?after= SSE: token·card·chips·citation·usage·done|error
POST   /api/v1/turns/{turn_id}/cancel           204

POST   /api/v1/messages/{mid}/feedback          204  {row_id, vote}
GET    /api/v1/meta/taste-axes                  200 the whole vocabulary
GET    /api/v1/meta/dataset-version             200 version · row_count · review_status_counts
GET    /api/v1/meta/usage                       200 session spend
```

**Streaming.** The stream handler returns a real `ReadableStream` of `text/event-stream`, framed exactly as `turns.py` frames it (`id:` / `event:` / `data:`), word-by-word at 12ms with every fourth token pausing double — the backend's own uneven cadence, which exists precisely so a frontend cursor and stop button are tested against something that behaves like a stream. It honours `?after=`, emits the `idle` `done` frame on catch-up, and `/dev/styleguide` exposes a **drop the stream** button so resume is a thing I can test on demand rather than hope about.

**The mock engine is a port, not a script.** `mocks/engine/` holds a TS port of the real serving path: keyword intent router → interview slot filling → style hard filter → weighted distance over the seven axes → sweetness tolerance gate → variety diversification → 3–5 rows → templated copy. Roughly 150 lines against the real 45 rows, mirroring `turns/deterministic.py`, `taste/ranking.py` and `taste/copy.py` closely enough that refine chips genuinely re-rank and "a dessert wine, not sweet at all" genuinely reaches the FR-13 abstention instead of a canned message.

**This is the one place wine words may live in the repo's frontend**, because this directory stands in for the server, not for the client. `mocks/engine/axes.ts` mirrors `taste/axes.py`, and `GET /meta/taste-axes` serves from it — so components still get their vocabulary over the wire, and deleting `src/mocks/` entirely must leave the app working against FastAPI.

**Fixtures.** `wines.seed.json` copied verbatim (45 rows, 5 styles, producers empty, all unreviewed) plus six seeded conversations covering: a completed red interview with results; a refine chain where the user went "bolder" then "smoother"; a dessert conversation that abstains; an out-of-scope price question; a free-text opener that filled two slots at once so the taste panel shows **inferred**; and an empty new conversation. One conversation is pinned to `dataset_version: "seed-0.0"` so `dataset_version_stale` renders somewhere.

**Switching to the real backend.** `VITE_USE_MOCKS=false` stops the worker; Vite proxies `/api` → `http://127.0.0.1:8000`; `fetch` already sends `credentials: "include"` and `EventSource` is already constructed `{ withCredentials: true }`, because the real cookies are httpOnly and the mocks are built to need the same thing.

---

## 8. Folder Skeleton

```
frontend/
├── index.html · package.json · tsconfig.json · vite.config.ts
├── .env.development            VITE_USE_MOCKS=true
├── public/mockServiceWorker.js
└── src/
    ├── main.tsx · App.tsx
    ├── app/            router.tsx · providers.tsx · layouts/AppShell.tsx
    ├── components/
    │   ├── ui/             Button IconButton Textarea Dialog DropdownMenu Tooltip
    │   │                   Popover Badge Pill Skeleton Toast Separator ScrollArea
    │   ├── shell/          Sidebar SidebarToggle TopBar Wordmark OfflineBanner
    │   │                   ReadinessGate ErrorBoundary
    │   ├── agegate/        AgeGateScreen ResponsibilityNote
    │   ├── conversations/  ConversationList ConversationGroup ConversationItem
    │   │                   NewChatButton ConversationSearch RenameDialog
    │   │                   DeleteDialog ArchiveToggle
    │   ├── thread/         Thread MessageList UserTurn AssistantTurn TextRun
    │   │                   StreamingCursor ScrollToBottom ThreadEmptyState
    │   │                   TurnDetails StreamErrorNotice
    │   ├── composer/       Composer SendButton StopButton CharCounter DisabledReason
    │   ├── chips/          ChipRow InterviewChips RefineChips ChipRecord BlockedRefineNotice
    │   ├── cards/          RecommendationCard CardHeader StyleDot TastingNote
    │   │                   WhyItMatches AxisMeter AxisReadings RegionPills
    │   │                   ProducerList EmptyProducerNote ProvenanceFooter
    │   │                   FeedbackButtons CardSkeleton
    │   ├── trust/          DatasetBadge DatasetPopover StaleVersionNotice
    │   │                   HowThisWorksPanel UsageSummary DegradedNotice
    │   ├── taste/          TastePanel SlotRow ProvenanceTag ProfileProgress
    │   └── states/         AbstentionNotice OutOfScopeNotice NotFound RateLimited
    │                       DatasetUnavailable
    ├── hooks/     useConversationStream useSendTurn useAutoScroll useTasteAxes
    │              useDatasetVersion useKeyboardShortcuts useMediaQuery useAgeGate
    ├── lib/       api.ts sse.ts reducer.ts cn.ts format.ts constants.ts problem.ts
    ├── mocks/     browser.ts handlers/ engine/ fixtures/ stream.ts
    ├── stores/    useUIStore.ts useComposerStore.ts
    ├── styles/    globals.css theme.css
    └── types/     api.ts domain.ts sse.ts
```

---

## 9. Build Phases

Each phase ends somewhere demo-able. Nothing is marked done until its states are built, not just its happy path.

### Phase 0 — Scaffold
- [x] Vite + React 19 + TS strict in `frontend/`, `@/` alias, ESLint + Prettier
- [x] Tailwind v4 via `@tailwindcss/vite`; dev proxy `/api` → `127.0.0.1:8000`
- [x] MSW installed, worker written to `public/`, started behind `VITE_USE_MOCKS`
- [x] `types/api.ts` typed by hand against `schemas.py` in snake_case, `types/sse.ts` against the six frames

### Phase 1 — Design system
- [x] `theme.css` with every §3.1 token under `@theme`; `globals.css` resets and sets the canvas
- [x] `ui/` primitives on Radix, each with hover / focus-visible / active / disabled
- [x] `/dev/styleguide`: tokens, type scale, every primitive, every state, both chip kinds, a card in all three provenance states, and the stream-drop button
- [x] Contrast audit of every pairing in the styleguide; fix before moving on

### Phase 2 — Mock API and transport
- [x] `wines.seed.json` copied in; a probe asserts 45 rows, every style present, producers empty, all unreviewed — so a fixture edit that invents data fails loudly
- [x] `mocks/engine/` ported: intent router, interview, ranking, tolerance gate, diversify, copy templates
- [x] All fourteen handlers, with the real status codes and `problem+json` bodies
- [x] `stream.ts`: SSE framing, 12ms uneven cadence, `?after=` replay, `anchor_seq`, the `idle` `done`, forced-drop hook
- [x] `lib/sse.ts` + `lib/reducer.ts`: frames → turn state, seq-deduped, two cursors
- [x] Vitest on the reducer (out-of-order frames, duplicate seq, mid-run resume, idle) and the ranker (abstention case, diversification)

### Phase 3 — Shell, age gate, readiness
- [x] Router with the five routes; `/age` guard on every other route; return-to-intended-route after confirming
- [x] Age gate screen: explicit 21+, responsible-consumption line, no imagery, keyboard-complete
- [x] `ReadinessGate` on `/readyz`; `DatasetUnavailable` with automatic recovery
- [x] AppShell: sidebar + top bar + thread slot + taste panel slot; collapse persisted; error boundary; offline banner; toast host

### Phase 4 — Conversations
- [x] List grouped Today / Last 7 days / Older, newest first, active highlighted
- [x] New chat → `POST /conversations` → navigate to `/c/{id}`
- [x] Search with the titles-only empty copy; archived toggle
- [x] Inline rename, archive, delete with confirm — *refetch-based, not optimistic; see §12.1*
- [x] Cursor-paged infinite scroll at 20; skeleton rows on first load

### Phase 5 — Thread and streaming ← *the core*
- [x] `GET /conversations/{cid}` renders a full transcript from message parts, in seq order
- [x] One `EventSource` per mounted conversation, `withCredentials`, reconnect with backoff
- [x] Optimistic user turn on send, reconciled against `user_message_id`
- [x] Idempotency key minted per send and held for retry; `409 turn_in_flight` unreachable from the UI
- [x] Streaming text run with cursor; Stop wired to cancel; cancelled turns keep their partial text and say they were stopped
- [x] Autoscroll only while pinned to the bottom; scroll-to-bottom button otherwise; no layout shift when a card lands
- [x] `aria-live` region with a politeness budget
- [x] Resume verified with the forced-drop button, mid-run and between runs

### Phase 6 — Chips and composer
- [x] Interview chips from the `chips` frame; selecting one sends `selected_chip_id` and shows it chosen
- [x] Older chip rows become `ChipRecord` — the choice, legible, not clickable
- [x] Refine chips under a result set, from the frame, labels never hardcoded
- [x] "Cannot go further that way" keeps the remaining options live — *shares the abstention frame; see §12.2*
- [x] Composer: auto-grow, Enter/Shift+Enter, 2000 cap with counter from 1800, send/stop, every disabled reason in words

### Phase 7 — Recommendation cards
- [x] Load the `dataviz` skill before writing `AxisMeter`, then build the 3-step meter so it reads as a position on a scale rather than a score out of three
- [x] Card: variety, style dot + word, serif tasting note, why-it-matches callout, asked-axis meters, unasked axes as a compact line, region pills
- [x] `EmptyProducerNote` with the FR-11 sentence; hedged labels rendered verbatim with a dotted underline and a tooltip explaining the hedge
- [x] `ProvenanceFooter`: `row_id` · `dataset_version` · `review_status` badge
- [x] Thumbs up/down → `POST /messages/{mid}/feedback` with `row_id`, optimistic, idempotent on re-vote
- [x] Cards stagger in as they arrive; `CardSkeleton` is shaped blocks only, never sample text

### Phase 8 — Trust surfaces and the honest states
- [x] `DatasetBadge` + popover: row count, version, review counts, where the data comes from, what is not reviewed
- [x] `StaleVersionNotice` on `dataset_version_stale`
- [x] `TastePanel`: the slots, their provenance tags, progress through the interview, and the unasked axes once refine touches them
- [x] `TurnDetails` disclosure per turn: intent, latency, cache hit, cost — discreet, collapsed by default
- [x] `DegradedNotice` when `usage.degraded`; `UsageSummary` in the panel footer
- [x] `AbstentionNotice` (FR-13) styled as an answer, with refine chips attached; `OutOfScopeNotice` rendered plainly
- [x] `HowThisWorksPanel`: three questions, where the data comes from, what the product will not do

### Phase 9 — Polish
- [x] Keyboard pass: shortcuts (`⌘K` new chat, `/` composer, `Esc` stop, `⌘/` list), one focus treatment everywhere, overlays on Radix so focus is trapped and returned
- [ ] Screen-reader pass on a full interview → results → refine run — **needs a browser**
- [ ] Responsive pass at 1440 / 1280 / 1024 / 768 / 390 — **built, not eyeballed; needs a browser**
- [x] `prefers-reduced-motion` honoured including the cursor — *in CSS; not eyeballed*
- [x] Grep for raw hex outside `theme.css`, and for any §3.6 prohibition in a string literal
- [x] Bundle under 250KB gzipped — **165 KB**. Lighthouse itself **needs a browser**

---

## 10. Definition of Done

Every box below is checked against something that was actually run, not against intent.


- [x] `npm install && npm run dev` from a clean checkout gives a working app with no backend running
- [x] A stranger can confirm age, type an opener, answer the chips, get 3–5 cards, hit **bolder**, and see the set change — all against mocks, and all covered by `src/app/App.test.tsx`
- [x] `"a dessert wine, not sweet at all"` reaches the FR-13 abstention, not five sweet wines
- [x] Killing the stream mid-sentence and reconnecting replays the run intact, exactly once
- [x] No component contains a wine word, a raw hex value, or a §3.6 prohibition
- [x] Every row in §6.6 has a screen I can point at
- [x] `VITE_USE_MOCKS=false` against the real backend changes nothing the user can see — **verified; see §14**
- [x] `npm run typecheck` and `npm run test` clean; no `any` in `src/`

---

## 11. Decisions Taken

These were the open questions; the approval took the first option in each, and that is what is built.

1. **Taste panel** is a right rail, open by default ≥1280px, and a top-bar toggle otherwise. It shows each slot and whether it was **asked**, **inferred** or **refined**.
2. **Turn details** are user-facing but collapsed — intent, confidence, latency, cache hit and cost per turn, behind one quiet disclosure. `VITE_SHOW_DIAGNOSTICS=false` removes them and the session spend panel entirely.
3. **Only the latest chip row is live**, and it is docked above the composer rather than left in the transcript. Older rows render as a record of what was offered and what was taken.
4. **`snake_case` on the wire.** `WA_WIRE_CASE` never has to change (answers backend §15 Q1).
5. **`/dev/styleguide` is dev-only** and is dead code in a production build — the mock engine and the dataset it renders cards from never reach the bundle (verified by grepping `dist/`).
6. **Archived conversations** are a toggle in the sidebar footer.
7. **The first-run screen shows three starter phrases** in plain words, because free text is a first-class input (diagram §3/D5) and hiding it to push people towards chips would be coy.

---

## 12. What Is Not Done

Four things, stated rather than left to be discovered.

1. **Sidebar rename, archive and delete refetch rather than updating optimistically.** They are correct and they surface failure with the `request_id`; they are simply not instant. §9 Phase 4 claimed optimistic — this is the one place the build is less than the plan.
2. **A blocked refine shares the abstention's frame.** "I cannot go further that way" and "nothing matches that" are structurally identical on the wire — refine chips, no cards — and the client will not guess between them by reading the text, because sniffing for a phrase would put wine vocabulary back in the client and would break the moment lane 3 rewords the copy. The shared header is worded to be true of both.
3. **Per-turn diagnostics exist only for a turn this client watched run.** The transcript carries no usage, so a reloaded conversation shows none. Exposing it would need `transaction_log` on the conversation detail — a backend change, not a frontend one.
4. **Nothing has been looked at in a real browser.** The app itself is verified end to end headlessly — against the mocks and against the real backend — and every custom Tailwind utility is confirmed present in the built CSS. But the responsive pass at each width, a screen-reader run and Lighthouse all need someone in front of a screen. Treat Phase 9's last three boxes as written-but-unverified, and expect to find spacing to nudge.

---

## 13. One Bug Found In The Backend

`turns/deterministic.py::_lead_in` composes `f"Here are {count} grape varieties worth looking for{tail}"` where `tail` is `f" for {copytext._join(bits)}"`, which renders as:

> Here are 5 grape varieties worth looking **for for** not sweet at all and rich and bold.

The frontend's mock reproduces it exactly, because the mock is a port and silently correcting it there would hide the bug until the real backend was wired up. It is one word in one f-string.

---

## 14. Verified Against The Real Backend

The whole point of mocking at the network boundary is that the swap is a flag rather
than a rewrite. That is only worth anything if someone checks, so: the backend was run
on `127.0.0.1:8001` (`__main__` hardcodes 8000 and 8000 was taken) and the frontend was
pointed at it two different ways.

**1. The wire contract, field by field.** Every interface in `types/api.ts` and
`types/sse.ts` was checked against what the real server actually emits — around fifty
assertions, all passing:

- every key of `ConversationSummary`, `ConversationDetail`, `Message`, `MessagePart`,
  `Card`, `AxisReading`, `TasteProfile`, `SendMessageResponse`, `TasteAxesResponse`,
  `AxisSpec`, `AxisLevel`, `RefineChipSpec`, `DatasetVersionResponse` and
  `UsageResponse` arrives with that name, in `snake_case`
- all seven frames arrive (`token`, `card`, `chips`, `citation`, `usage`, `done`,
  and `error` on failure), ids increase strictly, and **every live token carries
  `anchor_seq`** with one anchor per run
- reopening at `after=0` replays, a text run comes back as **one** `token` frame with
  no `anchor_seq`, and the stream ends with `done` carrying `status: "idle"` and
  **no `id:`** — exactly what the reducer is built for
- **the user's own text replays as a `token` frame too**, which is the direct evidence
  for §6.1's high-water-mark rule: resume at 0 and the user's words would be rendered
  in the assistant's voice
- a repeated `Idempotency-Key` returns the **same** `turn_id` and starts nothing
- `example_producers` is `[]` and `review_status` is `unreviewed` on every card
- a vote on a row the message never cited is a `409 row_not_cited`; a send with no
  idempotency key is a `400`; an unknown conversation is a `404` — each with the
  `code` and `request_id` the UI switches on
- no user-facing label in `/meta/taste-axes` contains the word "dry"
- the profile filled from one free-text sentence, with `provenance: "inferred"` on
  each slot — which is what the taste panel's tags are reading

**2. The app itself.** `src/app/App.real.test.tsx` runs the app tests against that
server instead of the mocks, through the same components, reducer and EventSource —
**five tests, all passing, in about two seconds**
(`WA_REAL_BACKEND=1 npx vitest run src/app/App.real.test.tsx`). Verified there:

- the age gate against the real httpOnly signed cookie, then the real dataset badge
- a typed opener → three slots inferred → **3–5 streamed cards** with real row ids,
  real `not yet reviewed` badges and the FR-11 producer sentence
- a refine chip re-ranking the set without re-interviewing (FR-8)
- **the stream severed mid-answer, resuming with the lead-in intact exactly once** —
  not doubled, not truncated
- FR-13: a dessert wine that is not sweet returns no cards, says the combination is
  not covered, and keeps the adjustments live — with the taste panel reading
  **"2 of 2 answered"**, because FR-4 skips dessert's third question

Two things surfaced only here, both worth knowing:

- **The real age cookie is long-lived**, so a second visit in the same session
  legitimately skips the gate. The suite now passes through the gate whichever way it
  goes, which is what a returning visitor actually does.
- **A proxy that cannot cancel upstream is a trap.** The first version of the harness
  never released the real server's SSE connections, node's per-origin pool filled with
  abandoned streams, and a later request simply queued until the test timed out — a
  "slow test" that was really a leak. Propagating `cancel()` to the upstream reader
  took the suite from one flaky failure to five passes in two seconds. Worth
  remembering if the real client is ever put behind a proxy of its own.
