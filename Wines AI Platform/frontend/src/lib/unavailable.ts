import { ApiProblem, NetworkProblem } from "@/lib/problem";

/** Why the app cannot be used right now. These are three different situations and
 *  each needs its own message: telling a rate-limited user that the dataset is missing
 *  sends them, or whoever they report it to, after the wrong problem. */
export type UnavailableReason =
  | { kind: "dataset" }
  | { kind: "rate_limited"; retryAfter: number | null }
  | { kind: "unreachable" };

/** Turn a failed gate check into a reason. Only an actual answer from `/readyz`
 *  saying "not ready" (503) means the dataset is the problem. */
export function unavailableReason(error: unknown): UnavailableReason {
  if (error instanceof ApiProblem) {
    if (error.status === 429 || error.code === "rate_limited") {
      return { kind: "rate_limited", retryAfter: error.retryAfter };
    }
    if (error.status === 503 || error.code === "dataset_unavailable") return { kind: "dataset" };
    return { kind: "unreachable" };
  }
  if (error instanceof NetworkProblem) return { kind: "unreachable" };
  return { kind: "unreachable" };
}
