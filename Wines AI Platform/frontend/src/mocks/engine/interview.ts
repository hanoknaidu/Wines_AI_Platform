/** Port of `taste/interview.py`. Which question to ask next, and how to read an answer.
 *
 * Slots unfilled -> ask, never guess. Style is asked first because it gates which of
 * the remaining axes even apply. Hard cap: 3 questions.
 */

import { AXES_BY_ID, askedAxesForStyle, type Axis } from "./axes";
import type { Profile } from "./types";

export interface Question {
  axis: string;
  prompt: string;
  options: { id: string; label: string; value: string }[];
}

function optionsFor(axis: Axis) {
  return axis.levels.map((l) => ({
    id: `${axis.id}:${l.value}`,
    label: l.label,
    value: l.value,
  }));
}

export function nextQuestion(
  profile: Profile,
  askedCount: number,
  maxQuestions: number,
): Question | null {
  if (askedCount >= maxQuestions) return null;
  const style = profile.style ?? null;
  for (const axis of askedAxesForStyle(style)) {
    if (profile[axis.id] == null) {
      return { axis: axis.id, prompt: axis.prompt ?? "", options: optionsFor(axis) };
    }
  }
  return null;
}

/** Enough to recommend: a style, a sweetness, and the style's third axis if it has
 *  one. Dessert is sufficient on two slots — FR-4 skips its third question entirely. */
export function isSufficient(profile: Profile): boolean {
  if (!profile.style || !profile.sweetness) return false;
  return askedAxesForStyle(profile.style).every((axis) => profile[axis.id] != null);
}

/* --- reading a free-text answer ---------------------------------------- *
 * The chip path is exact (the id names the axis and the level). This is the fallback
 * for people who type, which the architecture makes a first-class input.
 */

const STYLE_WORDS: Record<string, string[]> = {
  red: ["red", "reds"],
  white: ["white", "whites"],
  rose: ["rose", "rosé", "pink", "blush"],
  sparkling: ["sparkling", "bubbles", "bubbly", "fizz", "champagne", "prosecco"],
  dessert: ["dessert", "pudding", "after dinner", "with pudding"],
};

const SWEET_WORDS: Record<string, string[]> = {
  dry: ["not sweet", "no sweetness", "nothing sweet", "unsweet", "bone dry", "dry"],
  off_dry: [
    "hint of sweet",
    "a bit sweet",
    "slightly sweet",
    "touch of sweet",
    "off dry",
    "little sweet",
    "lightly sweet",
    "semi sweet",
  ],
  sweet: ["properly sweet", "very sweet", "really sweet", "sweet", "sugary", "dessert sweet"],
};

const BODY_WORDS: Record<string, string[]> = {
  light: ["light", "easy", "delicate", "easy drinking", "not heavy"],
  medium: ["medium", "middle", "in between", "moderate"],
  full: ["full", "bold", "rich", "heavy", "big", "powerful", "robust"],
};

const OAK_WORDS: Record<string, string[]> = {
  none: ["crisp", "clean", "sharp", "fresh", "no oak", "unoaked", "mineral"],
  subtle: ["middle", "in between", "balanced", "a little oak"],
  pronounced: ["buttery", "rounded", "oaky", "creamy", "toasty", "vanilla"],
};

const AXIS_WORDS: Record<string, Record<string, string[]>> = {
  style: STYLE_WORDS,
  sweetness: SWEET_WORDS,
  body: BODY_WORDS,
  oak: OAK_WORDS,
};

// Negation cues. Longest-match alone is not enough: "nothing too sweet" contains
// "sweet" but not the phrase "nothing sweet", so a pure phrase table reads it as
// SWEET — and gets it wrong in the worst possible direction, serving a dessert wine
// to someone who just said they do not want one.
const NEGATIONS = [
  "not ",
  "nothing ",
  "no ",
  "without ",
  "avoid ",
  "isn't ",
  "dont ",
  "don't ",
];
const NEGATION_WINDOW = 28;

const EXPLICIT_OFF_DRY = [
  "hint of sweet",
  "touch of sweet",
  "slightly sweet",
  "a bit sweet",
  "little sweet",
  "lightly sweet",
  "semi sweet",
  "off dry",
];

function negated(lowered: string, needle: string): boolean {
  let start = 0;
  for (;;) {
    const idx = lowered.indexOf(needle, start);
    if (idx === -1) return false;
    const window = lowered.slice(Math.max(0, idx - NEGATION_WINDOW), idx);
    if (NEGATIONS.some((cue) => window.includes(cue))) return true;
    start = idx + needle.length;
  }
}

export function readAnswer(axisId: string, text: string): string | null {
  const table = AXIS_WORDS[axisId];
  if (!table) return null;
  const lowered = text.toLowerCase();

  if (axisId === "sweetness") {
    if (EXPLICIT_OFF_DRY.some((phrase) => lowered.includes(phrase))) return "off_dry";
    if (negated(lowered, "sweet")) return "dry";
  }

  let best: { length: number; value: string } | null = null;
  for (const [value, phrases] of Object.entries(table)) {
    for (const phrase of phrases) {
      if (lowered.includes(phrase) && (best === null || phrase.length > best.length)) {
        best = { length: phrase.length, value };
      }
    }
  }
  return best?.value ?? null;
}

export function readChip(chipId: string): [string, string] | null {
  if (!chipId.includes(":")) return null;
  const [axisId, value] = chipId.split(":", 2);
  const axis = AXES_BY_ID[axisId];
  if (!axis) return null;
  if (!axis.levels.some((l) => l.value === value)) return null;
  return [axisId, value];
}

/** Harvest every axis an utterance happens to state, not just the asked one. Someone
 *  who opens with "a smooth dry red" has answered two questions and implied a third;
 *  re-asking what they already said is the fastest way to look stupid. */
export function readAny(text: string): Record<string, string> {
  const found: Record<string, string> = {};
  for (const axisId of ["style", "sweetness", "body", "oak"]) {
    const value = readAnswer(axisId, text);
    if (value !== null) found[axisId] = value;
  }
  return found;
}
