/** Port of `taste/ranking.py` and `taste/diversify.py`.
 *
 * Style hard filter, then weighted L1 distance over the axes the profile actually
 * specifies, then a spread across grape variety. This is BRD v1.1's own serving path.
 */

import { AXES_BY_ID, SCORED_AXES, levelIndex } from "./axes";
import type { Profile, WineRow } from "./types";

export interface Scored {
  row: WineRow;
  distance: number;
  perAxis: Record<string, number>;
  score: number;
}

function axisDistance(axisId: string, target: string, actual: string): number | null {
  const t = levelIndex(axisId, target);
  const a = levelIndex(axisId, actual);
  if (t === null || a === null) return null;
  const span = Math.max(1, AXES_BY_ID[axisId].levels.length - 1);
  return Math.abs(t - a) / span;
}

/** Style is a hard pre-filter (FR-2). Nothing else is. */
export function hardFilter(rows: WineRow[], profile: Profile): WineRow[] {
  const style = profile.style;
  if (style == null) return [...rows];
  return rows.filter((row) => row.style === style);
}

export function rank(rows: WineRow[], profile: Profile): Scored[] {
  const scored: Scored[] = rows.map((row) => {
    let total = 0;
    let weightSum = 0;
    const perAxis: Record<string, number> = {};
    for (const axis of SCORED_AXES) {
      const target = profile[axis.id];
      if (target == null) continue;
      const actual = row[axis.id as keyof WineRow] as string | null;
      if (actual == null) continue;
      const d = axisDistance(axis.id, target, actual);
      if (d === null) continue;
      perAxis[axis.id] = Number(d.toFixed(4));
      total += d * axis.weight;
      weightSum += axis.weight;
    }
    // Unspecified axes are skipped rather than defaulted — a default would invent a
    // preference the user never expressed and then rank on it.
    const distance = weightSum ? total / weightSum : 1;
    return {
      row,
      distance: Number(distance.toFixed(6)),
      perAxis,
      score: Number((1 / (1 + distance)).toFixed(6)),
    };
  });

  // Ties broken by row_id so identical answers always produce identical output.
  scored.sort((a, b) => a.distance - b.distance || a.row.row_id.localeCompare(b.row.row_id));
  return scored;
}

/** Not folded into the distance score on purpose: a weighted average can always be
 *  dragged back under a threshold by other axes agreeing, and no amount of agreement
 *  about body makes a sweet wine an answer to "not sweet at all". */
export function withinSweetnessTolerance(
  scored: Scored[],
  profile: Profile,
  tolerance: number,
): Scored[] {
  const target = profile.sweetness;
  if (target == null) return scored;
  const t = levelIndex("sweetness", target);
  if (t === null) return scored;
  return scored.filter((item) => {
    const a = levelIndex("sweetness", item.row.sweetness);
    return a !== null && Math.abs(a - t) <= tolerance;
  });
}

/** "Chardonnay (oaked)" and "Chardonnay (unoaked)" are one variety for diversity. */
function varietyKey(variety: string): string {
  return variety.split("(")[0].trim().toLowerCase();
}

/** Greedy pass taking the best unseen variety first, then backfilling — relaxing to a
 *  second row of an already-used variety beats returning two results when five good
 *  matches exist. The spread is a preference, not a cap on the result count (FR-7). */
export function diversify(scored: Scored[], want: number, maxPerVariety = 1): Scored[] {
  const chosen: Scored[] = [];
  const counts: Record<string, number> = {};

  for (const candidate of scored) {
    const key = varietyKey(candidate.row.variety);
    if ((counts[key] ?? 0) >= maxPerVariety) continue;
    chosen.push(candidate);
    counts[key] = (counts[key] ?? 0) + 1;
    if (chosen.length >= want) return chosen;
  }

  for (const candidate of scored) {
    if (chosen.includes(candidate)) continue;
    chosen.push(candidate);
    if (chosen.length >= want) break;
  }
  return chosen;
}

export function varietyCount(scored: Scored[]): number {
  return new Set(scored.map((s) => varietyKey(s.row.variety))).size;
}
