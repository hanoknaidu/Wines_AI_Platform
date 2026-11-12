/** Port of `turns/intent.py`. Keyword + slot-state router.
 *
 * Returns the same four intents lane 3's Haiku router will return, with the same
 * semantics, so the UI behaves identically after the switch.
 */

import { REFINE_BY_ID } from "./axes";
import { isSufficient, readAny, readChip } from "./interview";
import { detect } from "./refine";
import type { Profile } from "./types";
import type { Intent } from "@/types/api";

const OUT_OF_SCOPE_TOPICS: [string, string[]][] = [
  [
    "price",
    ["how much", "price", "cost", "cheap", "expensive", "budget", "$", "£", "under 20"],
  ],
  ["availability", ["in stock", "available", "stocked", "carry", "find it at", "near me"]],
  [
    "health",
    [
      "healthy",
      "health",
      "calories",
      "hangover",
      "sulphite",
      "sulfite",
      "good for you",
      "bad for you",
      "liver",
      "pregnan",
    ],
  ],
  ["purchase", ["buy", "purchase", "order", "ship", "delivery", "add to cart", "checkout"]],
  ["vintage", ["vintage", "what year", "which year", "2019", "2020", "2021"]],
];

/** Order matters. Safety first, then an explicit chip, then refine-against-results,
 *  then the interview/recommend decision from slot state. */
export function classify(
  utterance: string,
  profile: Profile,
  options: { selectedChipId?: string | null; hasResults?: boolean } = {},
): { intent: Intent; confidence: number; topic: string | null } {
  const lowered = utterance.toLowerCase();

  for (const [topic, needles] of OUT_OF_SCOPE_TOPICS) {
    for (const needle of needles) {
      if (lowered.includes(needle)) {
        return { intent: "out_of_scope", confidence: 0.9, topic };
      }
    }
  }

  const chipId = options.selectedChipId;
  if (chipId) {
    if (REFINE_BY_ID[chipId]) return { intent: "refine", confidence: 1, topic: null };
    if (readChip(chipId)) return { intent: "interview", confidence: 1, topic: null };
  }

  if (options.hasResults && detect(utterance) !== null) {
    return { intent: "refine", confidence: 0.9, topic: null };
  }

  const merged = { ...profile, ...readAny(utterance) };
  if (isSufficient(merged)) return { intent: "recommend", confidence: 0.85, topic: null };

  return { intent: "interview", confidence: 0.8, topic: null };
}
