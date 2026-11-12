import { HttpResponse } from "msw";
import * as db from "../db";

/** problem+json, byte-shaped like `errors.py`. Every failure carries a stable code
 *  and a request id, and never a stack trace. */
export function problem(
  status: number,
  code: string,
  title: string,
  detail: string,
  extra: Record<string, string> = {},
): Response {
  return HttpResponse.json(
    {
      type: "about:blank",
      title,
      status,
      detail,
      code,
      request_id: `req_${Math.random().toString(36).slice(2, 10)}`,
    },
    { status, headers: { "Content-Type": "application/problem+json", ...extra } },
  );
}

/** One error the next mutating call will fail with, set from the styleguide so every
 *  row of the error table has a screen that can be reached on demand. */
let forced: string | null = null;

export function setForced(code: string | null): void {
  forced = code;
}

export function takeForced(): Response | null {
  if (!forced) return null;
  const code = forced;
  forced = null;
  switch (code) {
    case "rate_limited":
      return problem(
        429,
        "rate_limited",
        "Too many turns",
        "You are sending turns faster than the limit allows. Wait a moment and try again.",
        { "Retry-After": "12" },
      );
    case "dataset_unavailable":
      return problem(
        503,
        "dataset_unavailable",
        "Recommendations unavailable",
        "The wine dataset is not loaded, so no recommendation can be grounded in it.",
      );
    case "engine_unavailable":
      return problem(
        503,
        "engine_unavailable",
        "Engine unavailable",
        "The 'orchestrated' engine needs the orchestrator extra installed and configured.",
      );
    case "turn_in_flight":
      return problem(
        409,
        "turn_in_flight",
        "A turn is already running",
        "A turn is still in flight for this conversation. Wait for it or cancel it.",
      );
    case "internal_error":
      return problem(
        500,
        "internal_error",
        "Something went wrong",
        "The request could not be completed.",
      );
    default:
      return problem(400, code, "Request failed", "The request could not be completed.");
  }
}

/** FR-1: every chat route is blocked until age is confirmed, and it is re-checked
 *  server-side on each call rather than trusted from the client. */
export function ageGuard(): Response | null {
  if (db.db.age_confirmed) return null;
  return problem(
    403,
    "age_not_confirmed",
    "Age confirmation required",
    "Confirm you are 21 or older before starting a conversation.",
  );
}

export function readyGuard(): Response | null {
  if (db.db.ready) return null;
  return problem(
    503,
    "dataset_unavailable",
    "Recommendations unavailable",
    "The wine dataset is not loaded, so no recommendation can be grounded in it.",
  );
}
