/** What a row's `review_status` means, in one place.
 *
 * Three surfaces render this distinction — the card's provenance footer, the producer
 * list and the dataset badge — and the whole point of the field is that they agree.
 * Before this existed each one tested `status === "reviewed"` itself, which made
 * `"fixture"` read as *reviewed* in one place and *unreviewed* in another.
 *
 * The important asymmetry: only `reviewed` and `corrected` mean a person signed the
 * row, and a producer name is a checked fact in exactly those two states. `fixture`
 * carries producer names WITHOUT that signature — they are illustrative, generated
 * rather than verified — so it must never render as reviewed. See backend
 * `dataset/schema.py`, which refuses to let a fixture row carry a `reviewed_by`.
 */

export type ReviewStatus = "reviewed" | "corrected" | "fixture" | "unreviewed";

const KNOWN: ReviewStatus[] = ["reviewed", "corrected", "fixture", "unreviewed"];

/** Anything unrecognised degrades to `unreviewed`: the cautious end, never the
 *  reassuring one. A future status the client has not shipped support for yet must not
 *  arrive looking checked. */
export function reviewStatusOf(raw: string): ReviewStatus {
  return (KNOWN as string[]).includes(raw) ? (raw as ReviewStatus) : "unreviewed";
}

/** A person checked this row. The only condition under which a producer name on the
 *  card is a verified claim. */
export function isSigned(raw: string): boolean {
  const status = reviewStatusOf(raw);
  return status === "reviewed" || status === "corrected";
}

/** The card badge: short label and tone per status. */
export const REVIEW_BADGE: Record<ReviewStatus, { label: string; tone: "ok" | "caution" }> = {
  reviewed: { label: "reviewed", tone: "ok" },
  corrected: { label: "reviewed · corrected", tone: "ok" },
  fixture: { label: "example data", tone: "caution" },
  unreviewed: { label: "not yet reviewed", tone: "caution" },
};

/** The tooltip behind that badge. Each string says what is and is not checked, because
 *  "example data" on its own does not tell anyone whether to trust the names. */
export const REVIEW_TOOLTIP: Record<ReviewStatus, string> = {
  reviewed: "A person has checked every field on this row, including the producer names.",
  corrected:
    "A person checked this row and corrected it. Every field, including the producer names, has been verified.",
  fixture:
    "Demo data. The taste readings are the same ones the reviewed dataset will carry, but the producer names here are illustrative examples that no person has checked yet — treat them as names to look up, not as verified fact.",
  unreviewed:
    "This row has not been through human review yet. The taste readings are a starting point rather than a checked fact.",
};
