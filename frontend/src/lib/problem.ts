import type { ProblemBody } from "@/types/api";

/** A failure with a stable machine-readable code. Every call site switches on `code`,
 *  never on a message string. */
export class ApiProblem extends Error {
  readonly status: number;
  readonly code: string;
  readonly title: string;
  readonly detail: string;
  readonly requestId: string | null;
  readonly retryAfter: number | null;

  constructor(body: ProblemBody, retryAfter: number | null = null) {
    super(body.detail || body.title);
    this.name = "ApiProblem";
    this.status = body.status;
    this.code = body.code;
    this.title = body.title;
    this.detail = body.detail;
    this.requestId = body.request_id ?? null;
    this.retryAfter = retryAfter;
  }
}

/** The network itself failed. Distinct from a problem+json response: one means "the
 *  server said no", the other means "nothing answered", and they are different screens. */
export class NetworkProblem extends Error {
  readonly code = "network_unreachable";
  constructor(cause?: unknown) {
    super("The server could not be reached.");
    this.name = "NetworkProblem";
    this.cause = cause;
  }
}

export function isProblem(error: unknown, code?: string): error is ApiProblem {
  return error instanceof ApiProblem && (code === undefined || error.code === code);
}

export async function problemFrom(response: Response): Promise<ApiProblem> {
  const retryHeader = response.headers.get("Retry-After");
  const retryAfter = retryHeader ? Number(retryHeader) : null;
  let body: ProblemBody;
  try {
    body = (await response.json()) as ProblemBody;
  } catch {
    body = {
      type: "about:blank",
      title: "Request failed",
      status: response.status,
      detail: "The request could not be completed.",
      code: response.status === 429 ? "rate_limited" : "http_error",
    };
  }
  if (!body.code) body.code = response.status === 429 ? "rate_limited" : "http_error";
  if (!body.status) body.status = response.status;
  return new ApiProblem(body, Number.isFinite(retryAfter) ? retryAfter : null);
}
