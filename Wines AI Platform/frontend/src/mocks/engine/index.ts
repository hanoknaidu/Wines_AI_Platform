/** Port of `turns/deterministic.py` — the Phase-1 engine, over the real 45 seed rows.
 *
 *   answers -> target profile -> hard filter on style -> weighted distance across axes
 *           -> diversify by grape variety -> top 3-5 rows -> copy drawn from the row
 *
 * This is a port rather than a canned transcript on purpose. A scripted response
 * cannot exercise refine, cannot reach FR-13's abstention, and cannot be wrong in the
 * same places the real engine is wrong — so a UI built against one would be tested
 * against nothing.
 */

import artifact from "../fixtures/wines.seed.json";
import { askedAxesForStyle } from "./axes";
import * as copy from "./copy";
import { classify } from "./intent";
import { isSufficient, nextQuestion, readAny, readChip } from "./interview";
import * as ranking from "./ranking";
import * as refine from "./refine";
import type { DatasetArtifact, EngineEvent, Profile, TurnRequest, WineRow } from "./types";
import type { Intent } from "@/types/api";

const DATASET = artifact as DatasetArtifact;
export const ROWS: WineRow[] = DATASET.rows;
export const DATASET_VERSION = DATASET.dataset_version;
export const BUILT_AT = DATASET.built_at;

/** Mirrors of `config.py`. */
const MAX_INTERVIEW_QUESTIONS = 3;
const RESULTS_MIN = 3;
const RESULTS_MAX = 3;
const SWEETNESS_TOLERANCE_LEVELS = 1;
const MAX_MATCH_DISTANCE = 0.6;

const byRowId = new Map(ROWS.map((row) => [row.row_id, row]));

export function resolveRow(rowId: string): WineRow | null {
  return byRowId.get(rowId) ?? null;
}

export function reviewStatusCounts(): Record<string, number> {
  const counts: Record<string, number> = {};
  for (const row of ROWS) counts[row.review_status] = (counts[row.review_status] ?? 0) + 1;
  return counts;
}

export function runTurn(req: TurnRequest): EngineEvent[] {
  const events: EngineEvent[] = [];
  const profile: Profile = { ...req.profile };
  const { intent, confidence, topic } = classify(req.utterance, profile, {
    selectedChipId: req.selected_chip_id,
    hasResults: req.previous_row_ids.length > 0,
  });

  // The routed intent is not always the EFFECTIVE one: an interview turn that fills
  // the last slot goes on to recommend, and a refine that cannot move an axis falls
  // back. `usage` is emitted at the end carrying what actually happened.
  const ctx: { intent: Intent } = { intent };

  if (intent === "out_of_scope") {
    events.push({ t: "token", text: copy.outOfScope(topic ?? "generic") });
  } else if (intent === "refine") {
    runRefine(events, req, profile, ctx);
  } else {
    // Both 'interview' and 'recommend' go through the interview path: it harvests
    // whatever axes the utterance states and only then decides whether it has enough.
    // Dispatching 'recommend' straight to recommend would hand it the STORED profile
    // and lose the slots the router just read out of the utterance.
    runInterview(events, req, profile, ctx);
  }

  events.push({
    t: "usage",
    intent: ctx.intent,
    intent_confidence: confidence,
    model: "deterministic",
  });
  return events;
}

function runInterview(
  events: EngineEvent[],
  req: TurnRequest,
  profile: Profile,
  ctx: { intent: Intent },
): void {
  const patch: Record<string, string> = {};
  const confidence: Record<string, { confidence: number; provenance: string }> = {};

  const read = req.selected_chip_id ? readChip(req.selected_chip_id) : null;
  if (read) {
    patch[read[0]] = read[1];
    confidence[read[0]] = { confidence: 1, provenance: "asked" };
  } else {
    // Harvest every axis the utterance states, not only the one just asked.
    for (const [axisId, value] of Object.entries(readAny(req.utterance))) {
      if (profile[axisId] == null) {
        patch[axisId] = value;
        confidence[axisId] = { confidence: 0.8, provenance: "inferred" };
      }
    }
  }

  if (Object.keys(patch).length) {
    Object.assign(profile, patch);
    events.push({ t: "profile", values: patch, confidence });
  }

  const askedCount = ["style", "sweetness", "body", "oak"].filter(
    (axis) => profile[axis] != null,
  ).length;

  if (isSufficient(profile)) {
    runRecommend(events, req, profile, null, ctx);
    return;
  }

  const question = nextQuestion(profile, askedCount, MAX_INTERVIEW_QUESTIONS);
  if (question === null) {
    // Cap reached without enough slots: recommend on what we have rather than asking
    // a fourth question the product promised not to ask.
    runRecommend(events, req, profile, null, ctx);
    return;
  }

  ctx.intent = "interview";
  events.push({ t: "token", text: question.prompt });
  events.push({
    t: "chips",
    chips: {
      kind: "interview",
      axis: question.axis,
      prompt: question.prompt,
      options: question.options,
    },
  });
}

function runRefine(
  events: EngineEvent[],
  req: TurnRequest,
  profile: Profile,
  ctx: { intent: Intent },
): void {
  const chip = refine.detect(req.utterance, req.selected_chip_id);
  if (chip === null) {
    runRecommend(events, req, profile, null, ctx);
    return;
  }

  const { patch, blocked } = refine.apply(profile, chip);
  if (blocked) {
    events.push({
      t: "token",
      text: `I cannot go further that way - ${blocked}. Try one of the other adjustments below.`,
    });
    events.push({ t: "chips", chips: { kind: "refine", options: refine.chipsPayload() } });
    return;
  }

  Object.assign(profile, patch);
  events.push({
    t: "profile",
    values: patch,
    confidence: Object.fromEntries(
      Object.keys(patch).map((axis) => [axis, { confidence: 1, provenance: "refined" }]),
    ),
  });

  ctx.intent = "refine";
  // Trailing space: the next text run is concatenated by the client's reducer.
  events.push({ t: "token", text: `Adjusting for ${chip.label}. ` });
  runRecommend(events, req, profile, req.previous_row_ids, ctx);
}

function runRecommend(
  events: EngineEvent[],
  _req: TurnRequest,
  profile: Profile,
  anchor: string[] | null,
  ctx: { intent: Intent },
): void {
  ctx.intent = "recommend";
  let candidates = ranking.hardFilter(ROWS, profile);

  if (anchor?.length) {
    // Widened candidate set that keeps the previously shown rows in play, so the
    // correction is relative to what was on screen rather than a fresh search.
    const seen = new Set(candidates.map((row) => row.row_id));
    const anchored = anchor
      .map(resolveRow)
      .filter((row): row is WineRow => row !== null && !seen.has(row.row_id));
    candidates = [...candidates, ...anchored];
  }

  if (!candidates.length) {
    events.push({ t: "token", text: copy.emptyState(profile) });
    events.push({ t: "chips", chips: { kind: "refine", options: refine.chipsPayload() } });
    return;
  }

  let scored = ranking.rank(candidates, profile);

  // FR-13: an honest empty state, never a silently widened filter. The style filter
  // alone cannot carry this — without the floor, asking for a dessert wine that is
  // "not sweet at all" returns five properly-sweet dessert wines.
  const inRange = ranking
    .withinSweetnessTolerance(scored, profile, SWEETNESS_TOLERANCE_LEVELS)
    .filter((item) => item.distance <= MAX_MATCH_DISTANCE);

  if (!inRange.length) {
    events.push({ t: "token", text: copy.emptyState(profile) });
    events.push({ t: "chips", chips: { kind: "refine", options: refine.chipsPayload() } });
    return;
  }
  scored = inRange;

  let chosen = ranking.diversify(scored, RESULTS_MAX);
  if (chosen.length < RESULTS_MIN) chosen = scored.slice(0, RESULTS_MIN);

  events.push({ t: "token", text: copy.leadIn(chosen.length, profile) });

  for (const item of chosen) {
    const row = item.row;
    events.push({
      t: "card",
      row_id: row.row_id,
      card: {
        row_id: row.row_id,
        variety: row.variety,
        style: row.style,
        axes: copy.axisReadings(row),
        description: copy.tastesLike(row),
        why_it_matches: copy.whyItMatches(row, profile),
        typical_regions: [...row.typical_regions],
        example_producers: [...row.example_producers],
        review_status: row.review_status,
        dataset_version: row.dataset_version,
      },
    });
  }

  events.push({ t: "citation", row_ids: chosen.map((item) => item.row.row_id) });
  events.push({ t: "chips", chips: { kind: "refine", options: refine.chipsPayload() } });
}

/** Which axes this style actually asks about — used by the taste panel. */
export function askedAxisIds(style: string | null | undefined): string[] {
  return askedAxesForStyle(style).map((axis) => axis.id);
}
