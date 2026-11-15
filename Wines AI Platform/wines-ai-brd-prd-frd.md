# Wines AI — Product & Functional Specification

> **Hybrid BRD / PRD / FRD.** Why this exists, what it does, how it behaves, and how it's built.
> **Intended reader:** anyone seeing the demo. Assumes interest, not expertise.
> **Scope:** the demo build — production standards, running locally.
> **Version 1.1 — 2026-10-01.** Supersedes `ideas.md` where they differ; amendments in §9.

---

## 1. What This Is, and Why

**Wines AI asks three questions about what you like to drink, then names grape varieties and producers that match — served from a curated wine dataset that is reviewed and frozen before anyone uses it.**

Buying wine is gated by vocabulary you don't have. The label gives you grape, region and vintage — none of which answer whether *you* will like it, and a 92-point score measures quality against a critic's standard, not fit to your palate. Meanwhile the one thing a shopper does know, *"I like smooth reds, nothing too sour,"* is the one input no wine site accepts; they all ask you to filter by varietal, the fact you're missing.

The gap is **translation**. Wine is described in language precise to sommeliers and opaque to everyone else — *brambly*, *racy*, *unctuous* — while people actually say *smooth*, *not too sour*, *sweet but not syrupy*. Wines AI holds both vocabularies and maps between them, which is what a filter dropdown cannot do.

**Why not just ask a chatbot.** Because a chatbot answers from scratch every time, and sooner or later it invents a bottle — a winery that doesn't make that wine, a bottling that never existed. The user goes to a shop, the wine isn't there, and the product has spent its only chance at trust. Wines AI separates the two jobs: the wine knowledge is written down, checked by a person and **frozen** ahead of time; the running app only ever retrieves from it. **Nothing is generated while you wait**, so what the app can say is fixed, finite, and was reviewed before you arrived.

---

## 2. Who It's For, and What Success Means

| | Who | What they need |
|---|---|---|
| **Primary** | Non-expert drinker | Knows what they like in plain words, not what to buy |
| **Secondary** | Curious regular | Has a usual bottle, wants to branch out |
| **Not for** | Trade and sommeliers | They need inventory and vintage data, which this isn't |
| **Not for** | Anyone wanting a quality score | This recommends **fit**, not critic approval |

Success is what a demo can show: a stranger completes the flow unaided and finds the result plausible; nothing outside the reviewed dataset is ever named; recommendations feel instant; someone who knows wine can't trivially break the sweetness matching; and it runs from a clean checkout in one command.

---

## 3. The Experience

Three taps to a recommendation. Options, not a text box — the user doesn't know the vocabulary to type, and a fixed input space means the system can never be asked something it has no data for.

**Age confirmation** comes first. Wine is a regulated product; a demo that ignores that is making a statement it doesn't mean to.

**Q1 — "What are you in the mood for?"** · Red · White · Rosé · Sparkling · Something sweet for dessert

Asked first because it decides which remaining axes apply at all. Tannin is meaningless for a white.

**Q2 — "How sweet?"** · Not sweet at all · Just a hint of sweetness · Properly sweet

**Q3 — branches on Q1:**

| If they picked | They're asked | Options |
|---|---|---|
| Red | *"How heavy should it feel?"* | Light and easy · In the middle · Rich and bold |
| White, Rosé, Sparkling | *"Crisp or rounded?"* | Clean and crisp · In the middle · Rounded and buttery |
| Dessert | *nothing* | Style and sweetness are already enough |

Note what these avoid. Tannin, acidity and oak are never named, and *"dry"* never appears — it is the most misused word in consumer wine language, used to mean not-sweet, tannic, harsh, austere, or simply sophisticated. Asking *"dry or sweet?"* collects unreliable answers from exactly the users who most need help, so every question is a physical sensation instead.

**The results.** Three to five recommendations, each carrying the **grape variety** — the primary answer, and the transferable one, since learning you like Grenache beats learning you like one bottle — plus **what it tastes like** in plain language, **why it matches** in the words the user chose, **typical regions** to look in, and **example producers** worth looking for. Producers are illustrative, not a catalogue: see §8.

Results deliberately **span** a little rather than returning five near-identical wines. Three Cabernets, a Malbec and a Syrah teaches the user something and hedges against one wrong inference; five Cabernets does neither.

**Refine.** A row of adjustments after the results — *less sweet · sweeter · lighter · bolder · smoother · less oaky · more fruit · more earthy* — re-ranks without re-interviewing. This is worth more than a fourth question, because self-reported taste is unreliable: people discover what they meant by seeing a wrong answer first.

**Feedback.** A thumbs up or down per result, logged. Nothing consumes it yet; in a group demo it collects the only honest signal about whether matches land.

---

## 4. The Taste Model

Seven axes describe each wine. Only three are ever asked.

| Axis | Levels | How it's used |
|---|---|---|
| **Style** | red / white / rosé / sparkling / dessert | Asked (Q1) — a hard filter |
| **Sweetness** | dry / off-dry / sweet | Asked (Q2) — heavily weighted |
| **Body** | light / medium / full | Asked (Q3, reds) |
| **Oak** | none / subtle / pronounced | Asked (Q3, whites, rosé, sparkling) |
| **Tannin** | smooth / moderate / grippy | In the dataset; reachable via refine |
| **Acidity** | soft / fresh / racy | In the dataset; reachable via refine |
| **Fruit vs savoury** | fruit-forward / balanced / earthy | In the dataset; reachable via refine |

The four unasked axes aren't wasted: they are the vocabulary of the refine step, they drive result diversity, and they supply the "what it tastes like" copy. That is what makes three questions sufficient — the interview collects what a novice can confidently answer, and refine exposes the rest once there's something concrete to react to.

**Why three sweetness levels, not five.** Two reasons, and they point the same way. Users cannot reliably place themselves on a five-point sweetness scale — the gap between *off-dry* and *medium-sweet* is not a distinction most people can self-report. And a five-level claim in the dataset is a precision that cannot be checked during review, where a three-level one can. Three levels is what both the user and the verification can actually support.

---

## 5. How It Works

Two halves, and what matters is which half the user waits for.

**Authoring — once, offline, before anyone uses the app.**

```
for each grape variety and wine style (~150 rows)
  → generate a structured row with a language model:
      style · the 7 taste axes · plain-language description
      typical regions · example producers
  → review every row and every field by hand
  → correct what's wrong, delete what can't be verified
  → freeze as a versioned file committed to the repo (JSON → SQLite)
```

The dataset is deliberately small. Around 150 varieties and styles covers what a non-expert will plausibly be recommended, and — the real reason — **it is small enough to review completely.** Every row and field checked before anything ships: a stronger guarantee than sampling a large corpus, and one only available at this size.

**Serving — what the user actually waits for.**

```
three answers → target profile → filter by style → weighted distance across axes
              → diversify by grape variety → top 3–5 rows → copy drawn from the row
```

**No model runs in the request path.** All authoring happened offline and the result is a frozen file, so recommendations return in milliseconds, identical answers always produce identical recommendations, and the app needs no network and no credentials at runtime.

**What this removes.** No third-party scrape, no licensing question, no nine-year-old snapshot to apologise for. No extraction pipeline, no embedding model, no vector store. The dataset is a few hundred rows in a file a person can read end to end — which is also why it can be fully reviewed.

**Where the risk moved.** It changed address rather than disappearing. Previously the risk was misreading a real expert's tasting note; now it is asserting something untrue with **no external source to check against.** Full human review is the only thing standing behind that — which is precisely why the dataset is sized to make full review possible.

**Stack.** Python and FastAPI serving a server-rendered page, with a little vanilla JavaScript for the branching interview. Dependencies with `uv`; SQLite for the dataset, loaded into memory at startup. No machine-learning dependencies at runtime at all. One process, one command.

---

## 6. Functional Requirements

| # | Requirement |
|---|---|
| FR-1 | Confirm legal drinking age before any recommendation is shown. |
| FR-2 | Ask style first, from five fixed options, and apply it as a hard filter. |
| FR-3 | Ask sweetness from three fixed options, phrased as sensation rather than wine terminology. |
| FR-4 | Ask one further question selected by the style answer; skip it entirely for dessert. |
| FR-5 | Return three to five recommendations, each naming a grape variety, its taste profile and typical regions. |
| FR-6 | Explain each match in the same terms the user selected. |
| FR-7 | Ensure the result set spans at least two grape varieties wherever the match set allows. |
| FR-8 | Offer refine adjustments that re-rank the existing results without repeating the interview. |
| FR-9 | Record a thumbs up or down per recommendation against the session. |
| FR-10 | Serve every field from the frozen dataset, identified by row, and never call a model at request time. |
| FR-11 | Name example producers only where verified in review; present them as examples to look for, not as stock. |
| FR-12 | Support many users holding independent sessions at once, with no sign-up, and allow a clean restart. |
| FR-13 | Show an honest empty state when nothing matches, rather than silently relaxing the filters. |

---

## 7. Non-Functional Requirements

| # | Requirement | Target |
|---|---|---|
| NFR-1 | Recommendation latency | Under 100 ms at p95; no model inference in the request path |
| NFR-2 | Concurrency | At least 20 simultaneous anonymous sessions on a single laptop |
| NFR-3 | Reproducibility | Clean checkout to running app in one command; pinned dependencies; the dataset is a committed artifact, not a build step |
| NFR-4 | External dependencies | None at runtime — no API keys or secrets to provision, no outbound network calls, functions fully offline |
| NFR-5 | Dataset verification | 100% of rows and fields human-reviewed before release; review status recorded per row |
| NFR-6 | Code quality | Typed module boundaries; unit tests covering the ranking function and the dataset schema validator |
| NFR-7 | Error handling | No stack trace reaches a user; every failure path has a defined user-facing state |
| NFR-8 | Observability | Structured logs of session, answers, results served, feedback received |
| NFR-9 | Data integrity | Every served field originates in the frozen dataset — never from a model at request time |
| NFR-10 | Startup | The app loads the dataset and starts in seconds |

NFR-4 and NFR-5 carry this design. Because the dataset is authored once and committed, the running app has **no credentials at all** — nothing to leak or rotate, no per-request cost, no third party in the data path. And because it is small, verification is a complete pass rather than a sample. Authoring is the only place a model is involved, and its output is treated as a draft for review, not as data.

---

## 8. Trust, Limits, and What's Deliberately Absent

The section that decides whether any of this is believable.

**Honest about where the data comes from.** This is the most important limitation in the document. The dataset is not sourced from published reviews or a commercial database — it is **generated by a language model and then reviewed line by line by a person.** For grape varieties that is solid ground: that Cabernet Sauvignon is dry, full-bodied and tannic is stable, documented knowledge, not a judgement call, and it is easy to check. **Named producers are the weakest point in the system,** because which wines a specific winery actually makes is exactly what a language model will confabulate. Hence FR-11: producer names are verified in review or removed, and shown as examples to look for rather than a catalogue. There is no external ground truth behind any of it, and this document does not pretend otherwise.

**Nothing is generated at request time.** Whatever the dataset's limits, they are fixed and inspectable before a user arrives (FR-10, NFR-9). A wrong row is a bug someone can find and fix, not a fresh invention on every visit.

**Honest about coverage.** Around 150 varieties and styles is enough for a non-expert and nowhere near complete. Obscure grapes, regional specialities and most of the world's actual bottles are absent. The system will sometimes have no good answer, and FR-13 requires it to say so rather than stretch.

**No availability or price.** Nothing here is checked against what a shop stocks, and price is out of scope entirely — a number we cannot verify is worse than no number. Recommendations name a **producer and a grape**, never a vintage, so they stay useful without claiming to be current.

**Regulated-product posture.** Age confirmation before use. No health claims in either direction — not that wine is good for you, not a lecture about drinking — and a responsible-consumption note. No purchase path or buy links: direct-to-consumer alcohol shipping is regulated jurisdiction by jurisdiction and is a compliance project, not a feature.

**Taste is subjective, and the product says so.** No scores, no "best," no ranking that reads as a verdict. The output is a starting point for your own exploration — getting this tone wrong would turn the tool into the thing it was built to replace.

---

## 9. Decisions, Amendments, and What's Next

Five decisions changed from `ideas.md` as this document was written:

| Was | Now | Why |
|---|---|---|
| A 130,000-row third-party review corpus | ~150 rows authored by a language model, fully human-reviewed, frozen | No third-party scrape or licensing question, no nine-year-old data, and small enough to verify completely rather than sample. Accepted cost: no external ground truth — see §8. |
| Taste axes extracted from tasting-note prose | Taste axes authored directly as structured fields | With the dataset written rather than scraped, there is no prose to extract from. Removes the embedding pipeline, the false-friend lexicon and the vector store entirely. |
| Single user, no auth | Many concurrent anonymous sessions, still no accounts | A group demo means several people using it at once from their own devices. |
| React + TypeScript + Vite front end | Server-rendered FastAPI with a little vanilla JS | One process, no build step. The UI is a wizard and a list. |
| Five sweetness levels, four questions | Three sweetness levels, three questions | Users can't reliably self-report five levels, and five can't be verified in review (§4). |

Unchanged: price stays out of scope, nothing is generated at request time, and producer-and-grape stays the unit of recommendation.

**Open items**, carried forward rather than quietly resolved:

- **Ranking ties.** With price gone, nothing obvious separates equally good matches. Critic points would smuggle quality back into a fit recommendation, against §8. Intent is deliberate variety diversity — it needs deciding, not defaulting.
- **How producers get verified**, and by what standard. This is the weakest link in the system (§8) and the verification method is not yet defined.
- **Dataset coverage**: which 150 varieties and styles, and what the minimum bar is for including one.
- **Which model authors the dataset.** At this size the cost is negligible either way, so this is a quality decision rather than a budget one — and the runtime stays credential-free regardless (NFR-4).

**Next, in order:** draft the dataset schema, author the ~150 rows, review every one and record what the review changed, then build the interview. The dataset is the risk; the interface is not.
