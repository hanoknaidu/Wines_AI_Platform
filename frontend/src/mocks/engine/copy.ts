/** Port of `taste/copy.py`. User-facing copy, composed from the row and the user's own
 *  selections. Every string is templated from dataset fields — nothing is generated,
 *  so nothing can be invented. */

import { AXES_BY_ID, labelFor, levelIndex } from "./axes";
import type { Profile, WineRow } from "./types";
import type { AxisReading } from "@/types/api";

/** "Why it matches" is phrased in the words the user chose (FR-6), so the explanation
 *  uses the asked level's consumer label and never the wine term. */
const MATCH_PHRASES: Record<string, string> = {
  "sweetness:dry": "you asked for nothing sweet, and this is not sweet",
  "sweetness:off_dry": "you asked for just a hint of sweetness, and this has one",
  "sweetness:sweet": "you asked for properly sweet, and this is",
  "body:light": "you wanted light and easy, and this is a light-bodied wine",
  "body:medium": "you wanted something in the middle, and this sits there",
  "body:full": "you wanted rich and bold, and this is full-bodied",
  "oak:none": "you wanted clean and crisp, and this sees no oak",
  "oak:subtle": "you wanted something in the middle, and the oak here is light",
  "oak:pronounced": "you wanted rounded and buttery, and this is oak-aged",
};

const NEAR_MISS: Record<string, string> = {
  sweetness: "it is a touch {direction} than you asked for",
  body: "it is a little {direction} than you asked for",
  oak: "the oak is a little {direction} than you asked for",
};

const DIRECTION: Record<string, string> = {
  "sweetness:-1": "drier",
  "sweetness:1": "sweeter",
  "body:-1": "lighter",
  "body:1": "fuller",
  "oak:-1": "crisper",
  "oak:1": "more oaky",
};

const READING_AXES = ["sweetness", "body", "oak", "tannin", "acidity", "fruit_savoury"];
const ASKED_AXES = ["sweetness", "body", "oak"];

export function join(items: string[]): string {
  if (items.length === 0) return "";
  if (items.length === 1) return items[0];
  return `${items.slice(0, -1).join(", ")} and ${items[items.length - 1]}`;
}

function confidenceFor(row: WineRow, axisId: string): number {
  const value = row.confidence[axisId];
  return typeof value === "number" ? value : 0.5;
}

function capitalise(text: string): string {
  return text.charAt(0).toUpperCase() + text.slice(1);
}

/** The per-axis block on a card, with the hedge already applied. */
export function axisReadings(row: WineRow): Record<string, AxisReading> {
  const out: Record<string, AxisReading> = {};
  for (const axisId of READING_AXES) {
    const axis = AXES_BY_ID[axisId];
    if (!axis.applies_to.includes(row.style)) continue;
    const value = row[axisId as keyof WineRow] as string | null;
    if (value == null) continue;
    const confidence = confidenceFor(row, axisId);
    out[axisId] = {
      value,
      confidence: Number(confidence.toFixed(3)),
      label: labelFor(axisId, value, confidence),
    };
  }
  return out;
}

/** Explain the match in the user's terms, and name the gap where there is one. */
export function whyItMatches(row: WineRow, profile: Profile): string {
  const hits: string[] = [];
  const misses: string[] = [];

  for (const axisId of ASKED_AXES) {
    const target = profile[axisId];
    if (target == null) continue;
    const actual = row[axisId as keyof WineRow] as string | null;
    if (actual == null) continue;
    if (actual === target) {
      const phrase = MATCH_PHRASES[`${axisId}:${target}`];
      if (phrase) hits.push(phrase);
    } else {
      const t = levelIndex(axisId, target);
      const a = levelIndex(axisId, actual);
      if (t === null || a === null) continue;
      const direction = DIRECTION[`${axisId}:${a > t ? 1 : -1}`];
      const template = NEAR_MISS[axisId];
      if (direction && template) misses.push(template.replace("{direction}", direction));
    }
  }

  const parts: string[] = [];
  if (hits.length) parts.push(`${capitalise(join(hits))}.`);
  if (misses.length) parts.push(`${capitalise(join(misses))}.`);
  if (!parts.length) {
    parts.push("This is the closest match in the dataset to what you described.");
  }

  // An honest hedge where an axis the user asked about is low-confidence.
  const low = ASKED_AXES.filter(
    (axisId) =>
      profile[axisId] != null &&
      (row[axisId as keyof WineRow] as string | null) != null &&
      confidenceFor(row, axisId) < 0.75,
  );
  if (low.length) {
    parts.push(
      `Worth knowing: the ${join(low.map((a) => a.replace(/_/g, " ")))} reading on this row is less certain.`,
    );
  }
  return parts.join(" ");
}

/** Straight from the row's description field. Never rewritten. */
export function tastesLike(row: WineRow): string {
  return row.description;
}

/** FR-13: say so honestly rather than silently relaxing the filters. */
export function emptyState(profile: Profile): string {
  const styleName =
    AXES_BY_ID.style.levels.find((l) => l.value === profile.style)?.label.toLowerCase() ??
    String(profile.style);
  const sweetName =
    AXES_BY_ID.sweetness.levels
      .find((l) => l.value === profile.sweetness)
      ?.label.toLowerCase() ?? String(profile.sweetness);
  return (
    `Nothing in the dataset matches ${styleName} that is ${sweetName}. ` +
    "Rather than widen the search and hand you something you did not ask for, " +
    "here is the honest answer: that combination is not covered. " +
    "Adjust one of the choices below and I will look again."
  );
}

/** Templated, no retrieval. BRD §8's posture, in one place. */
export function outOfScope(topic: string): string {
  const responses: Record<string, string> = {
    price:
      "Price is out of scope here. Nothing in this dataset is checked against what a shop charges, and a number I cannot verify is worse than no number.",
    availability:
      "I cannot tell you what is in stock. Nothing here is checked against a shop's inventory, so the producers are examples to look for, not a catalogue.",
    health:
      "I am not the right source on wine and health, in either direction. Ask someone qualified.",
    purchase:
      "There is no purchase path here. Shipping alcohol is regulated jurisdiction by jurisdiction, so buying is deliberately not part of this.",
    vintage:
      "I do not hold vintage data. Recommendations here name a grape and a producer to look for, which stays useful without claiming to be current.",
    generic:
      "That is outside what this dataset covers. I can suggest grape varieties and styles that match how you like wine to taste - ask me about that.",
  };
  return responses[topic] ?? responses.generic;
}

export function leadIn(count: number, profile: Profile): string {
  const bits: string[] = [];
  for (const axisId of ["sweetness", "body", "oak"]) {
    const value = profile[axisId];
    if (value == null) continue;
    const level = AXES_BY_ID[axisId].levels.find((l) => l.value === value);
    if (level) bits.push(level.label.toLowerCase());
  }
  // Mirrors `deterministic.py::_lead_in` exactly, including why it is not `join`: the
  // sentence already ends in "for", and these labels contain "and" themselves, so
  // `join` would render "rich and bold and rounded and buttery".
  const tail = bits.length ? `: ${bits.join(", ")}` : "";
  return `Here are ${count} grape varieties worth looking for${tail}.`;
}
