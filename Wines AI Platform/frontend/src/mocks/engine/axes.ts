/** Port of `taste/axes.py`. The seven axes, their levels and the consumer labels.
 *
 * This directory stands in for the SERVER, not for the client — which is why the only
 * wine vocabulary in the repo's frontend lives here, and why it is served over
 * GET /meta/taste-axes rather than imported by a component. Deleting src/mocks/
 * entirely must leave the app working against FastAPI.
 *
 * Two product rules are enforced by this table rather than left to prose: the word
 * "dry" never appears in a user-facing label, and every question is phrased as a
 * physical sensation rather than a wine term. A test asserts the first.
 */

export const STYLES = ["red", "white", "rose", "sparkling", "dessert"] as const;

export const STYLE_LABELS: Record<string, string> = {
  red: "Red",
  white: "White",
  rose: "Rosé",
  sparkling: "Sparkling",
  dessert: "Something sweet for dessert",
};

export interface Level {
  value: string;
  label: string;
  hedged_label: string;
}

export interface Axis {
  id: string;
  asked: boolean;
  levels: Level[];
  question_order: number | null;
  prompt: string | null;
  applies_to: readonly string[];
  weight: number;
}

const level = (value: string, label: string, hedged_label: string): Level => ({
  value,
  label,
  hedged_label,
});

/** Ordering within `levels` is meaningful: it is the scale refine deltas move along. */
export const AXES: Axis[] = [
  {
    id: "style",
    asked: true,
    question_order: 1,
    prompt: "What are you in the mood for?",
    applies_to: STYLES,
    weight: 0, // a hard filter, never a distance term
    levels: STYLES.map((s) => level(s, STYLE_LABELS[s], STYLE_LABELS[s])),
  },
  {
    id: "sweetness",
    asked: true,
    question_order: 2,
    prompt: "How sweet?",
    applies_to: STYLES,
    // Heaviest weight: a sweetness mismatch is the one error a novice notices instantly.
    weight: 3,
    levels: [
      level("dry", "Not sweet at all", "probably not sweet"),
      level("off_dry", "Just a hint of sweetness", "maybe a hint of sweetness"),
      level("sweet", "Properly sweet", "likely sweet"),
    ],
  },
  {
    id: "body",
    asked: true,
    question_order: 3,
    prompt: "How heavy should it feel?",
    applies_to: ["red"],
    weight: 1.5,
    levels: [
      level("light", "Light and easy", "probably light"),
      level("medium", "In the middle", "probably medium-bodied"),
      level("full", "Rich and bold", "likely full-bodied"),
    ],
  },
  {
    id: "oak",
    asked: true,
    question_order: 3,
    prompt: "Crisp or rounded?",
    applies_to: ["white", "rose", "sparkling"],
    weight: 1.5,
    levels: [
      level("none", "Clean and crisp", "probably crisp"),
      level("subtle", "In the middle", "lightly rounded"),
      level("pronounced", "Rounded and buttery", "likely buttery"),
    ],
  },
  {
    id: "tannin",
    asked: false,
    question_order: null,
    prompt: null,
    applies_to: ["red"],
    weight: 1,
    levels: [
      level("smooth", "smooth", "probably smooth"),
      level("moderate", "some grip", "some grip"),
      level("grippy", "firm and grippy", "likely grippy"),
    ],
  },
  {
    id: "acidity",
    asked: false,
    question_order: null,
    prompt: null,
    applies_to: STYLES,
    weight: 1,
    levels: [
      level("soft", "soft", "probably soft"),
      level("fresh", "fresh", "fresh"),
      level("racy", "zippy and sharp", "likely sharp"),
    ],
  },
  {
    id: "fruit_savoury",
    asked: false,
    question_order: null,
    prompt: null,
    applies_to: STYLES,
    weight: 1,
    levels: [
      level("fruit_forward", "fruity", "probably fruity"),
      level("balanced", "balanced", "balanced"),
      level("earthy", "earthy and savoury", "likely earthy"),
    ],
  },
];

export const AXES_BY_ID: Record<string, Axis> = Object.fromEntries(
  AXES.map((axis) => [axis.id, axis]),
);

export const SCORED_AXES = AXES.filter((axis) => axis.weight > 0);

export interface RefineChipSpec {
  id: string;
  label: string;
  axis: string;
  delta: number;
}

export const REFINE_CHIPS: RefineChipSpec[] = [
  { id: "less_sweet", label: "less sweet", axis: "sweetness", delta: -1 },
  { id: "sweeter", label: "sweeter", axis: "sweetness", delta: 1 },
  { id: "lighter", label: "lighter", axis: "body", delta: -1 },
  { id: "bolder", label: "bolder", axis: "body", delta: 1 },
  { id: "smoother", label: "smoother", axis: "tannin", delta: -1 },
  { id: "less_oaky", label: "less oaky", axis: "oak", delta: -1 },
  { id: "more_fruit", label: "more fruit", axis: "fruit_savoury", delta: -1 },
  { id: "more_earthy", label: "more earthy", axis: "fruit_savoury", delta: 1 },
];

export const REFINE_BY_ID: Record<string, RefineChipSpec> = Object.fromEntries(
  REFINE_CHIPS.map((chip) => [chip.id, chip]),
);

export const CONFIDENCE_THRESHOLD = 0.75;

export function levelIndex(axisId: string, value: string | null | undefined): number | null {
  const axis = AXES_BY_ID[axisId];
  if (!axis || value == null) return null;
  const idx = axis.levels.findIndex((l) => l.value === value);
  return idx === -1 ? null : idx;
}

export function levelAt(axisId: string, index: number): string | null {
  const axis = AXES_BY_ID[axisId];
  if (!axis) return null;
  const clamped = Math.max(0, Math.min(axis.levels.length - 1, index));
  return axis.levels[clamped].value;
}

/** "likely dry" is not "dry". The hedge is decided here, server-side, and the client
 *  renders whatever `label` it is handed. */
export function labelFor(axisId: string, value: string, confidence: number): string {
  const axis = AXES_BY_ID[axisId];
  if (!axis) return value;
  const found = axis.levels.find((l) => l.value === value);
  if (!found) return value;
  return confidence >= CONFIDENCE_THRESHOLD ? found.label : found.hedged_label;
}

export function askedAxesForStyle(style: string | null | undefined): Axis[] {
  return AXES.filter((axis) => {
    if (!axis.asked) return false;
    if (style != null && !axis.applies_to.includes(style)) return false;
    return true;
  }).sort((a, b) => (a.question_order ?? 99) - (b.question_order ?? 99));
}

export function styleOptions() {
  return STYLES.map((s) => ({ id: `style:${s}`, label: STYLE_LABELS[s], value: s }));
}
