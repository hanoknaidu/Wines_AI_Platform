# Wines AI — Collected Ideas

> **Status:** Pre-architecture brain dump. This document exists to collect thinking so the **BRD** (functional + non-functional specs) can be written from something solid. It is deliberately light on technical nuance — embedding model, extraction topology, store selection and ranking function are *consciously deferred* to the technical architecture step.
>
> **Last updated:** 2026-10-01

---

## 1. The Pitch

**Wines AI is a taste-first wine recommender. You answer three or four plain-language questions about what you like to drink, and it names grape varieties and producers that match — drawn from a corpus of 130,000 expert tasting notes, never invented.**

### The problem

Buying wine is a decision gated by vocabulary you don't have:

- **The label answers the wrong question.** It tells you grape, region, vintage and producer. It does not tell you whether *you* will like it.
- **Scores measure the wrong thing.** "92 points" is quality against a critic's standard. It says nothing about fit to your palate. A 92-point bone-dry Chablis is a bad recommendation for someone who wants something sweet.
- **The one thing a shopper knows is the one thing nothing accepts as input.** People arrive knowing "I like smooth reds, nothing too sour." Every wine site asks them to filter by varietal and region — the exact facts they don't have.
- **Expertise is unevenly available.** A good shop assistant solves this in thirty seconds. Most purchases don't happen in front of one.

### Why an AI tool helps here

The core job is **translation**. There exist 130,000 professionally written tasting notes describing wines in a vocabulary that is precise to sommeliers and opaque to everyone else — *brambly*, *racy*, *unctuous*, *malolactic*. On the other side is consumer taste language — *smooth*, *not too sour*, *sweet but not syrupy*.

Mapping between those two vocabularies is a language problem over an existing corpus. That is squarely what language models are good at, and it is not something a filter dropdown can do.

### Why the usual AI tool doesn't

A general chatbot fails at this for one specific reason: **it will confidently invent a bottle.** Ask it for a sweet red from a named producer and it will return something plausible — a winery that doesn't make that wine, a bottling that never existed, a flavour profile assembled from statistical association.

The user then goes to a shop, the wine isn't there, and the product has spent its only chance at trust. Wine advice is a trust product; the first wrong recommendation ends the relationship.

So the differentiating constraint for Wines AI is not "answer well." It's **every recommendation is a row in the dataset, not a generation.** The model's job is matching and explaining. It is never the source of the wine.

This is the direct analogue of Legal Lens's no-invented-citations constraint, and it drives the architecture the same way.

---

## 2. Who It's For

| | Persona | What they want |
|---|---|---|
| **Primary** | Non-expert drinker | Knows what they like in plain words, doesn't know what to buy. Wants a short list of grapes and producers they can actually find. |
| **Secondary** | Confident-but-curious drinker | Has a usual bottle and wants to branch out — *"I always buy Malbec, what else would I like?"* Needs adjacency, not education. |
| **Explicitly not** | Sommeliers and trade | They don't need taste translation; they need inventory and vintage data, which this isn't. |
| **Explicitly not** | Anyone looking for a quality rating | This recommends on **fit**, not on how good a critic thought the wine was. See §8.6. |

**Phase 1 is a single user with no login.** One person, one session, no account. Multi-user and remembered palates come later (see §5).

---

## 3. The Product

Three pieces: **Interview → Recommend → Refine**. Everything else is plumbing.

### 3.1 The Taste Interview

**What the user does:** Picks from presented options. Not free text — buttons.

This was the original design instinct and it is the right one. Options beat a text box here for three reasons: the user doesn't know the vocabulary to type, picked options are unambiguous to the backend, and a fixed input space means the system can never be asked something it has no data for.

**The constraint that matters: at most four questions.** Every additional question loses users. So the interview must be *adaptive* — ask the question that discriminates most, given what's already known.

**Proposed shape:**

1. **Style** — red / white / rosé / sparkling / dessert. Asked first because it gates which of the remaining axes even apply (tannin is meaningless for a white).
2. **Sweetness** — the original axis, and the one users most want to express.
3. **and 4.** — two more, *chosen by branch*: for reds, body and tannin; for whites, acidity and oak.

Four taps, and the two branch questions are always the ones that matter for that style.

### 3.2 The Taste Model

Since price is out of scope (D1), taste now carries the entire recommendation. One sweetness axis is not enough to distinguish 130,000 wines, so the model needs real dimensions:

| Axis | Values | Asked as | Applies to |
|---|---|---|---|
| **Style** | red / white / rosé / sparkling / dessert | directly | all |
| **Sweetness** | bone dry → dry → off-dry → medium-sweet → sweet | *"no sweetness at all"* → *"properly sweet, like dessert"* | all |
| **Body** | light / medium / full | *"light like water or rich like cream?"* | all |
| **Tannin** | smooth / moderate / grippy | *"that mouth-drying grip of over-steeped tea — yes or no?"* | reds |
| **Acidity** | soft / fresh / racy | *"do you like a sharp, lemony edge?"* | whites, sparkling |
| **Fruit vs savoury** | fruit-forward / balanced / earthy | *"jammy fruit, or earthy and savoury?"* | all |
| **Oak** | none / subtle / pronounced | *"buttery and vanilla, or clean and crisp?"* | whites (esp. Chardonnay), some reds |

Seven axes, **never seven questions.** Four are asked; the rest are inferred from style and left open as "no preference," which widens the match rather than constraining it.

The phrasing column is the actual product work. See Suggestion 3 — asking these in jargon collects noise.

### 3.3 The Recommendation

**What they get back:** three to five results, each carrying:

- **The grape variety** — the transferable knowledge. Learning you like Grenache is worth more than learning you like one bottle.
- **Named producers** — straight from the dataset's `winery` column. This satisfies the "suggest brands" requirement **from data**, not from model memory.
- **Why it matches**, in the user's own terms — *"dry, soft tannins, dark fruit, no oak — that's what you asked for."*
- **What it tastes like**, translated out of the tasting note.
- **Honest confidence** where a taste axis was inferred weakly (§8.4).

**One deliberate design call:** the results should *span* a little rather than return five near-identical wines. A list of five Cabernets is a worse answer than three Cabernets, a Malbec and a Syrah — it teaches the user something and it hedges against one wrong inference.

**Phase 1 non-goals:** no price, no availability, no purchase path, no food pairing, no remembered preferences.

### 3.4 Refine

One round of correction — *"too sweet," "lighter," "less oaky"* — re-ranks without re-interviewing.

This is small to build and worth more than a fifth interview question, because **self-reported taste is unreliable** (§9.6). People discover what they meant by seeing a wrong answer. Phase 1 stretch; Phase 2 at the latest.

---

## 4. Decisions Already Made

Recorded so the BRD doesn't relitigate them.

| # | Decision | Choice | Rationale |
|---|---|---|---|
| D1 | **Price** | **Out of scope.** Taste only. | Decided 2026-10-01, replacing an earlier taste-plus-price design. Three things support it: the dataset's prices come from a **June 2017** scrape and would be confidently wrong today; price filtering is what every wine site already does, so it isn't where this product differentiates; and dropping it forces the taste model to be genuinely good (§3.2) rather than leaning on a crude second axis. See Suggestion 7 for keeping the door open cheaply. |
| D2 | **Dataset** | `winemag-data-130k-v2` — Wine Enthusiast reviews, scraped week of 15 June 2017 | 129,971 rows. Carries `variety` (the grape), `winery` (the brand), `description` (the expert tasting note), `points`, `price`, `title`, `designation` and region fields. Public, well-understood, and it already contains both halves the product needs: the brand to recommend and the prose to derive taste from. |
| D3 | **Recommendations are retrieved, never generated** | Every result is a dataset row, identified by `winery` + `variety` + `title` | The invented-bottle failure mode (§1) is fatal to a trust product. The model matches and explains; it is never the source. |
| D4 | **Taste axes are derived offline, once** | A batch extraction pass over all 130k rows, not a per-request model call | This is where the "use open-source models to extract from the files" idea lands. Running it offline means: no model in the request path, sub-100ms recommendations, identical answers for identical inputs, a cost that is paid once (§7.3), and an auditable intermediate table a human can inspect and correct. |
| D5 | **Guided options, not free text** | Buttons for Phase 1 | The original design instinct. Also closes the ambiguous-input and prompt-injection surfaces at the front door rather than defending against them later. Free text becomes an *additional* path in Phase 2, never the only one. |
| D6 | **Phase 1 users** | Single user, no auth | Removes login, sessions and persistence from the MVP. Same reasoning as Legal Lens D3, and the same mitigation: the schema carries a user identifier from day one even though it's always the same value. |
| D7 | **End goal** | Production-intent, built in phases | So the BRD covers the full functional *and* non-functional picture, with Phase 1 scoped as the MVP slice of it. |
| D8 | **Frontend** | React + TypeScript + Vite | No preference expressed. Matching Legal Lens D5 — same stack, same tooling, one set of conventions across both projects. The UI here is simpler (an option wizard and a result list, no PDF overlay), so this is a low-risk default rather than a considered bet. |

---

## 5. Phases

| Phase | Scope |
|---|---|
| **1 — MVP** | Offline taste extraction over the 130k corpus. Four-question adaptive interview. Three-to-five recommendations with variety, producers and a plain-language explanation. Single user, no auth, no price. |
| **2 — Refinement & breadth** | The refine loop (§3.4). Free text alongside options. Food pairing. "I like X, what else?" adjacency. |
| **3 — Live commercial data** | A current data source for availability and price. **Price returns here**, properly sourced (D1). Region-aware results — recommending what's actually on shelves near the user. |
| **4 — Personalisation** | Accounts, remembered palate, learning from thumbs up/down across sessions. This is where the logged feedback from Suggestion 9 pays off. |

---

## 6. Tech Stack

| Layer | Choice | Notes |
|---|---|---|
| **Frontend** | React + TypeScript + Vite | See D8 |
| **Backend** | Python + FastAPI | Matching Legal Lens; async matters less here since there's no streaming in the hot path |
| **Packaging / deps** | `uv` | Same as Legal Lens |
| **Offline pipeline** | Python — pandas or polars | Runs once, offline; not a service |
| **Taste extraction** | *Deferred — candidates in §7.2* | The one genuinely open technical question |
| **Store** | *Deferred — but see the note below* | |
| **Metadata DB** | SQLite for Phase 1, Postgres beyond | |

### A note on scale: this is not a big-data problem

Worth stating plainly before anyone reaches for infrastructure. The corpus is ~130k rows and roughly 65 MB of CSV. Add a 384-dimension embedding per wine and that's another ~200 MB. **The entire enriched dataset fits comfortably in the memory of a single modest process.**

So Phase 1 needs no vector database, no search cluster, and no distributed anything. An in-memory table with a brute-force nearest-neighbour scan over 130k rows returns in single-digit milliseconds. A managed vector store is a Phase 3 concern that arrives with live commercial data, if ever.

This mirrors the lesson from Legal Lens's Suggestion 2: check whether the retrieval machinery is solving a problem you actually have.

---

## 7. AI Layer — Sketch Only

### 7.1 Pipeline shape

```
OFFLINE, ONCE:
  winemag CSV → clean / dedupe → per-wine taste extraction from `description`
              → 7-axis taste vector + per-axis confidence
              → cross-check against varietal priors → enriched table

AT REQUEST TIME:
  interview answers → target taste vector
                    → hard filter (style) + nearest-neighbour (remaining axes)
                    → diversify across variety
                    → top 3–5 rows → explanation copy → UI
```

Note what is *not* in the request path: any model call. Extraction is offline (D4); the explanation copy can be templated from the structured axes, with an optional LLM pass if templated copy reads too mechanically.

### 7.2 The one hard technical question: deriving sweetness

**The dataset does not have a sweetness column.** The single most important input to the product is the one field the data lacks. Everything rests on deriving it from the `description` prose plus the `variety`.

Three candidate approaches, to be evaluated rather than chosen on instinct:

**(a) Lexicon + rules.** A hand-built map of sommelier vocabulary to axis values — *bone-dry*, *off-dry*, *lush*, *unctuous*, *racy*, *firm tannins*, *buttery*. Transparent, debuggable, free to run, and likely stronger than it sounds: tasting-note prose is highly formulaic, which is exactly the condition under which lexicons work well. Must handle negation and collocation — see §9.2, which is where naive versions of this die.

**(b) Zero-shot or LLM structured extraction.** One pass per row returning the seven axes with confidences. Better on nuance and on notes that describe sweetness obliquely. Costs money once (§7.3).

**(c) Varietal priors.** Not an approach on its own, but an essential **cross-check** on both of the above. Cabernet Sauvignon is effectively always dry; Moscato and Port are always sweet. A row whose derived sweetness contradicts a strong varietal prior is almost certainly an extraction artifact and should be flagged for review rather than shipped.

**Recommended order:** build (a) first, measure it against a hand-labelled gold set (Suggestion 2), then apply (b) only to the rows and axes where (a) measurably fails. This is cheaper, and it produces a system whose failures are inspectable.

### 7.3 What the extraction pass costs

Recorded because the cost of (b) is the main argument people will raise against it, and the number turns out to settle the argument.

Estimating ~300 input tokens per row (a cached instruction prefix plus a ~60-token tasting note) and ~80 output tokens for the structured axes, across 129,971 rows:

| Model | ID | Input $/1M | Output $/1M | Est. one-time pass | With Batch API (−50%) |
|---|---|---|---|---|---|
| Claude Haiku 4.5 | `claude-haiku-4-5` | $1.00 | $5.00 | ~$90 | **~$45** |
| Claude Sonnet 5.5 | `claude-sonnet-5-5` | $2.00 | $10.00 | ~$180 | ~$90 |
| Claude Opus 5.5 | `claude-opus-5-5` | $4.00 | $20.00 | ~$360 | ~$180 |

*Model reference current as of 2026-09-25. Token counts are estimates — verify with `count_tokens` on a 100-row sample before committing.*

**The whole corpus can be enriched for roughly the price of a dinner.** Three consequences:

- The offline-extraction decision (D4) is not a cost compromise; it's cheaper *and* better.
- This is a **mechanical per-row extraction task**, so the cheap tier is the right tier — a different call from Legal Lens, where reasoning quality justified Opus. Measure Haiku first and only escalate on evidence.
- It's a batch job with no latency requirement, which is exactly what the Batch API's 50% discount is for. Prompt caching on the shared instruction prefix cuts the input side further.

The cost of being wrong is also low: re-running the whole pass after a prompt fix is another $45, not a project.

### 7.4 Platform facts worth recording

- **Batch API** — 50% discount, asynchronous, results keyed by `custom_id` and returned in arbitrary order. Built for exactly this shape of job.
- **Prompt caching** — prefix-based, so the extraction instructions go first and the per-wine note last. Any byte change in the prefix invalidates the cache for every row after it.
- **Structured outputs** — `output_config.format` constrains the response to the seven-axis schema, which removes response-parsing as a failure mode across 130k rows.
- **No model in the request path at all** in Phase 1, if templated explanations read acceptably. Worth testing before assuming an LLM is needed for the copy.

### 7.5 A dead end, recorded so nobody walks into it

The **UCI Wine Quality** dataset (1,599 red and 4,898 white *vinho verde* samples) contains actual measured `residual_sugar` — real sweetness chemistry, the exact ground truth this product wants.

It cannot be used. It has no `variety`, no `winery`, and no tasting note; it's physicochemical measurements of anonymous Portuguese samples. There is no join key to the winemag corpus and no way to recommend from it, since it can't name a wine.

Two public wine datasets, each holding precisely what the other lacks. Worth knowing before someone spends a week trying to bridge them.

---

## 8. Trust & Guardrails

The section a generic BRD would skip. Alcohol is a regulated product and taste advice is a trust product; both constrain the design.

### 8.1 No invented bottles

**Hard requirement.** Every recommendation resolves to a specific dataset row. The response carries the row's identity — `winery`, `variety`, `title` — so any claim is checkable against the source corpus. Nothing reaches the user that didn't come from the data (D3).

### 8.2 Alcohol is regulated

- **Age gate** before any recommendation. 21+ in the US; the threshold varies by jurisdiction, and so do the rules on how alcohol may be marketed at all.
- **No marketing to minors**, which constrains tone and visual design, not just the gate.
- **No health claims in either direction.** Not "good for the heart," not a lecture. The product recommends on taste and says nothing about consumption.
- **A responsible-consumption message** in the footer.

If this ever ships commercially, jurisdiction-specific alcohol advertising rules become a real compliance surface. Worth naming now; out of scope for Phase 1.

### 8.3 Honest about stale data

The corpus is a June 2017 snapshot. A specific vintage bottling from it may simply not exist on a shelf in 2026. Two mitigations:

- **Recommend at producer-plus-variety level, not exact vintage** (Suggestion 6). *"Look for Mollydooker Shiraz"* survives nine years; *"the 2014 Carnival of Love"* may not.
- **Say plainly that availability isn't checked.** One line, not buried.

D1 already removes the worst version of this problem — a nine-year-old price presented as current.

### 8.4 Confidence, not false precision

Where a taste axis was derived with low confidence, the UI says so. *"Likely dry"* and *"dry"* are different claims, and a product that can't tell them apart is lying by omission. The extraction step must emit per-axis confidence (§7.2) for this to be possible at all — which is why it's a requirement on the pipeline, not a UI nicety.

### 8.5 No purchase path in Phase 1

No buy links, no cart, no fulfilment. US direct-to-consumer alcohol shipping is regulated state by state and is a compliance project in its own right, not a feature to bolt on.

### 8.6 Taste is subjective, and the product should say so

This recommends fit, not quality. It should avoid implying objective authority — no scores, no "best," no rankings that look like verdicts. Output is a starting point for the user's own exploration. Getting this tone wrong turns a helpful tool into the thing it was built to replace.

---

## 9. Known Design Problems

Identifiably hard, named before the BRD so they get budgeted for.

1. **The primary input is the missing column.** The product's first substantive question is sweetness, and sweetness is precisely what the dataset doesn't record (§7.2). Every other design problem below is downstream of this one.

2. **Sommelier false friends.** *"Sweet tannins," "sweet oak," "sweet spice"* and *"a dry finish"* on a genuinely sweet wine are all standard tasting-note phrases — and all of them mean something other than what a keyword matcher will conclude. A naive search for "sweet" and "dry" will produce confidently wrong sweetness on a large fraction of rows. Needs negation handling, collocation rules, and the varietal cross-check of §7.2(c).

3. **Riesling.** Varietal priors are strong at the extremes and useless in the middle: Riesling spans bone-dry *trocken* to intensely sweet Trockenbeerenauslese, and so do Chenin Blanc and Sherry. The hard cases are exactly where "I want something sweet" users land, so this isn't a tail problem. The text has to carry it — and the text is often silent on sweetness.

4. **There is no ground truth.** Nothing in the data says *"this wine is off-dry,"* so extraction accuracy cannot be measured without hand-labelling. Not a reason to skip measurement — a reason to build the gold set first (Suggestion 2).

5. **Corpus bias, and the recommendation that's right but unbuyable.** Every wine in the dataset was selected for review by Wine Enthusiast and scored 80–100. That skews toward wines someone thought worth reviewing and under-represents supermarket shelf wine — which is the beginner's actual shopping context. The system can return a taste match that is accurate and impossible to find. The corpus also skews US, French and Italian.

6. **"Dry" is the most misused word in consumer wine language.** People say it to mean *not sweet*, *tannic*, *harsh*, *austere*, or sometimes just *sophisticated*. So the obvious interview question — *"do you want dry or sweet?"* — collects noisy answers from the very users who most need help. This is a direct problem for the original flow design, and the fix is §3.2's phrasing column plus Suggestion 3.

7. **Dropping price removed the tiebreaker.** A consequence of D1 worth stating honestly: among wines that match the taste profile equally well, nothing remains to rank by except `points` — and ranking by `points` quietly turns a fit recommendation into a critic-quality recommendation, which §8.6 says not to do. The tiebreak needs a deliberate decision (Suggestion 5), not a default.

---

## 10. Open Questions

To resolve before or during the BRD.

**Product scope**
- [ ] Is the output a grape variety, a producer, or a specific bottling? (§8.3 argues for the first two)
- [ ] How many recommendations — and how much should they deliberately differ from each other (§3.3)?
- [ ] Does the refine loop (§3.4) make Phase 1, or wait?
- [ ] Food pairing: real Phase 2 feature, or scope creep? The dataset has nothing to support it directly.
- [ ] Does "I like Malbec, what else?" get its own entry path, or is it just the interview with answers pre-filled?

**Taste model**
- [ ] Which four questions get asked, and in what branch order?
- [ ] Five sweetness levels or three? More granularity is only worth it if extraction can actually distinguish them.
- [ ] How are unasked axes handled — treated as "no preference," or inferred from the asked ones?
- [ ] What's the confidence threshold below which an axis isn't shown at all (§8.4)?

**Data**
- [ ] Deduplication: the corpus has near-duplicate rows for the same wine across vintages. Collapse them, or treat them as distinct?
- [ ] How is the long tail of `variety` handled? (Hundreds of varieties, most with very few rows)
- [ ] Rows with a null `variety` or `description` — drop, or salvage?
- [ ] Is the 2017 corpus acceptable for Phase 1, with §8.3's honesty, or does Phase 1 need a fresher source?
- [ ] **The tiebreak question from §9.7** — what ranks equally-good matches?

**Commercial / operational**
- [ ] Is this a product, a portfolio piece, or a prototype? (Changes how much of §8.2 matters now)
- [ ] Deployment target?
- [ ] Any licensing constraint on the winemag dataset for commercial use — worth checking before it's load-bearing

---

## 11. Suggestions to Consider

Raised for consideration, not decided. Accept, reject, or defer each.

### Suggestion 1 — Build the lexicon baseline before touching a model

A hand-built vocabulary map (§7.2a) is free to run, inspectable, and fixable in minutes. Tasting-note prose is formulaic enough that it will probably get a long way. Build it first, measure it, and spend model budget only on the rows and axes where it demonstrably fails.

The point isn't that the lexicon is better. It's that it gives you a **measured baseline** — without one, there's no way to tell whether the expensive approach is actually earning its cost.

### Suggestion 2 — Hand-label 200 wines before building the extractor

The highest-value half-day in this project. Pick ~200 wines, stratified across style and variety, and hand-label their true sweetness and body. **Deliberately over-sample the hard cases** — Riesling, Chenin Blanc, Moscato, anything from §9.3 — because that's where every approach will differ.

Without this there is no way to answer "is the extraction working," and every later prompt or lexicon change gets evaluated by vibes. Cheap now; effectively impossible to retrofit once you're tuning by feel and can't tell whether yesterday's change helped.

Pair it with negative cases: wines whose notes say *"sweet tannins"* or *"dry finish"* (§9.2), so the false-friend failures show up in the score rather than in production.

### Suggestion 3 — Ask in experiential language, never in jargon

Because of §9.6, the question *"do you prefer dry, medium-dry or sweet?"* returns unreliable data from exactly the users the product exists for.

Concretely:

| Instead of | Ask |
|---|---|
| "Dry, medium-dry, or sweet?" | "How sweet? — *None at all* / *Just a hint* / *Noticeably sweet* / *Dessert-sweet*" |
| "How much tannin?" | "That mouth-drying grip you get from over-steeped tea — *love it* / *fine with it* / *rather not*" |
| "Light, medium or full-bodied?" | "Light and easy like water, or rich and mouth-filling like cream?" |
| "How much oak?" | "Buttery and vanilla, or clean and crisp?" |

Same underlying axes, answerable by someone who has never read a wine list. The axis names stay internal.

### Suggestion 4 — Emit per-axis confidence from day one

§8.4 needs it, and it's nearly free to add during extraction but expensive to backfill — it would mean re-running the whole pass. It also makes §7.2(c)'s varietal cross-check actionable: low-confidence rows that contradict a strong prior are the review queue.

### Suggestion 5 — Decide the tiebreak now

Per §9.7, D1 left a hole in the ranking. Options worth weighing: random within the matched set (honest, but non-reproducible), deliberate diversity across variety (§3.3 wants this anyway), number of reviews as a rough proxy for findability, or `points` with an explicit acknowledgement that it imports critic bias.

Diversity-plus-findability looks like the right answer, but it should be a recorded decision rather than whatever the sort happens to do.

### Suggestion 6 — Recommend producers and varieties, not vintages

*"Look for Mollydooker Shiraz"* is useful in 2026. *"The 2014 Carnival of Love"* may not exist anywhere the user can reach. Recommending one level up from the exact bottling is both more robust to the stale corpus (§8.3) and more useful — it's a thing the user can actually go and find.

### Suggestion 7 — Keep `price` flowing through the pipeline, unused

D1 takes price out of the *product*. It shouldn't take it out of the *schema*. Carry the column through cleaning and into the enriched table, just never read it.

Then Phase 3 is a flag and a fresh price source, rather than a re-run of the whole pipeline. Same reasoning as Legal Lens's Suggestion 4 on `matter_id`: cheap now, a migration later.

### Suggestion 8 — Log thumbs up/down from day one, even with nothing consuming it

A one-bit signal per recommendation, stored and otherwise ignored. Phase 4's personalisation (§5) needs training data that can only be collected by having shipped. Starting the log on day one means Phase 4 begins with a dataset instead of beginning with a wait.

### Suggestion 9 — Reconsider the folder name

`Wines AI Platform` has two spaces in it. Fine for a docs folder; mild friction later for `uv`, npm scripts, Docker paths and CI. If this becomes the repo root, `wines-ai` would save some quoting. The same point was raised for `Legal Lens` and not acted on — so take it as a consistent preference for spaces, or fix both while they're each one directory.

---

## 12. Proposed BRD Outline

The next deliverable. Suggested structure:

1. **Executive Summary** — what Wines AI is, who it's for, why taste-first
2. **Business Objectives & Success Metrics** — what success looks like, measurably
3. **Scope** — in scope for Phase 1, out of scope (price, availability, purchase), future phases
4. **Stakeholders & Personas**
5. **Functional Requirements**
   - 5.1 Age gate and entry
   - 5.2 The taste interview — questions, branching, adaptive logic
   - 5.3 The taste model — axes, values, representation
   - 5.4 Recommendation and ranking, including the tiebreak (§9.7)
   - 5.5 Explanation and confidence display
   - 5.6 Refinement
6. **Data Requirements**
   - 6.1 Source corpus, provenance, and its known biases (§9.5)
   - 6.2 Cleaning, deduplication, and the long tail of `variety`
   - 6.3 Taste extraction — approach, confidence, and the human review queue
   - 6.4 The enriched schema, including carried-but-unused fields (Suggestion 7)
7. **Non-Functional Requirements**
   - 7.1 Extraction accuracy — *measured against the gold set, per axis*
   - 7.2 Performance and latency
   - 7.3 Reproducibility — identical inputs give identical recommendations (D4)
   - 7.4 One-time and ongoing cost
   - 7.5 Scalability, availability, usability and accessibility
8. **Compliance & Responsible Service** — age verification, alcohol marketing rules, no health claims, no purchase path
9. **Trust Requirements** — no invented bottles, honest confidence, honest staleness
10. **Assumptions & Constraints**
11. **Risks & Mitigations** — derived sweetness being wrong, front and centre
12. **Dependencies** — dataset, extraction model, hosting
13. **Phased Delivery Plan**
14. **Open Questions** — carried forward from §10
15. **Glossary** — wine terms and technical terms, since this document spans both

**Deliberately not in the BRD:** the extraction prompt, the lexicon contents, embedding model selection, the ranking function's weights, store selection. Those belong in the Technical Architecture Document that follows.
