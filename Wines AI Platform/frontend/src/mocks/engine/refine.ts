/** Port of `taste/refine.py`. Parse a delta and move exactly one axis.
 *
 * Anchored to the previous result set: the correction re-ranks what the user actually
 * saw plus a widened candidate set. It never re-interviews (FR-8).
 */

import { AXES_BY_ID, REFINE_BY_ID, REFINE_CHIPS, levelAt, levelIndex } from "./axes";
import type { RefineChipSpec } from "./axes";
import type { Profile } from "./types";

/** Free-text equivalents of the chips, longest-match first. */
const PHRASES: [string, string][] = [
  ["less sweet", "less_sweet"],
  ["not so sweet", "less_sweet"],
  ["too sweet", "less_sweet"],
  ["drier", "less_sweet"],
  ["sweeter", "sweeter"],
  ["more sweet", "sweeter"],
  ["not sweet enough", "sweeter"],
  ["lighter", "lighter"],
  ["less heavy", "lighter"],
  ["too heavy", "lighter"],
  ["bolder", "bolder"],
  ["richer", "bolder"],
  ["fuller", "bolder"],
  ["heavier", "bolder"],
  ["smoother", "smoother"],
  ["less grippy", "smoother"],
  ["too tannic", "smoother"],
  ["less oaky", "less_oaky"],
  ["less oak", "less_oaky"],
  ["too oaky", "less_oaky"],
  ["more fruit", "more_fruit"],
  ["fruitier", "more_fruit"],
  ["more earthy", "more_earthy"],
  ["earthier", "more_earthy"],
  ["more savoury", "more_earthy"],
  ["more savory", "more_earthy"],
];

export function detect(text: string, chipId?: string | null): RefineChipSpec | null {
  if (chipId && REFINE_BY_ID[chipId]) return REFINE_BY_ID[chipId];
  const lowered = text.toLowerCase();
  let best: { length: number; chip: string } | null = null;
  for (const [phrase, chip] of PHRASES) {
    if (lowered.includes(phrase) && (best === null || phrase.length > best.length)) {
      best = { length: phrase.length, chip };
    }
  }
  return best ? REFINE_BY_ID[best.chip] : null;
}

/** Move one axis one step. Returns the patch and, if it could not move, why. */
export function apply(
  profile: Profile,
  chip: RefineChipSpec,
): { patch: Record<string, string>; blocked: string | null } {
  const axis = AXES_BY_ID[chip.axis];
  if (!axis) return { patch: {}, blocked: `unknown axis ${chip.axis}` };

  const style = profile.style;
  if (style != null && !axis.applies_to.includes(style)) {
    return { patch: {}, blocked: `${chip.axis} does not apply to ${style}` };
  }

  const current = profile[chip.axis];
  // An axis that was never asked (tannin, acidity, fruit/savoury) starts from the
  // middle, so the delta has somewhere to move from.
  let idx =
    current == null ? Math.floor(axis.levels.length / 2) : levelIndex(chip.axis, current);
  if (idx === null) idx = Math.floor(axis.levels.length / 2);

  const targetIdx = idx + chip.delta;
  if (targetIdx < 0 || targetIdx > axis.levels.length - 1) {
    return {
      patch: {},
      blocked: `already at the ${targetIdx < 0 ? "lowest" : "highest"} ${chip.axis}`,
    };
  }

  const value = levelAt(chip.axis, targetIdx);
  return { patch: value ? { [chip.axis]: value } : {}, blocked: null };
}

export function chipsPayload() {
  return REFINE_CHIPS.map((c) => ({ id: c.id, label: c.label }));
}
