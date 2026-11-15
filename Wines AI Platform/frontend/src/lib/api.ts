/** The only module that talks to the network.
 *
 * Two things here are load-bearing and easy to get wrong:
 *
 * 1. `credentials: "include"` on every call. The session and age-gate cookies are
 *    httpOnly and signed, so without it every request arrives anonymous and the
 *    age gate never passes (backend §14.2).
 * 2. `Idempotency-Key` on send, minted once per send and REUSED on retry. A fresh key
 *    on retry starts a second turn; the same key with different content is a 409.
 */

import { API_BASE } from "./constants";
import { NetworkProblem, problemFrom } from "./problem";
import type {
  ConversationDetail,
  ConversationPage,
  ConversationSummary,
  DatasetVersionResponse,
  ReadyResponse,
  SendMessageResponse,
  TasteAxesResponse,
  UsageResponse,
  Vote,
} from "@/types/api";

export function newId(): string {
  if (typeof crypto !== "undefined" && "randomUUID" in crypto) return crypto.randomUUID();
  return `${Date.now()}-${Math.random().toString(16).slice(2)}`;
}

interface RequestOptions {
  method?: string;
  body?: unknown;
  headers?: Record<string, string>;
  signal?: AbortSignal;
}

async function request<T>(path: string, options: RequestOptions = {}): Promise<T> {
  const { method = "GET", body, headers = {}, signal } = options;
  let response: Response;
  try {
    response = await fetch(`${API_BASE}${path}`, {
      method,
      credentials: "include",
      signal: signal ?? null,
      headers: {
        Accept: "application/json",
        // The backend mints its own if absent; sending one means a client-side
        // failure and a server log line share an id.
        "X-Request-Id": newId(),
        ...(body !== undefined ? { "Content-Type": "application/json" } : {}),
        ...headers,
      },
      ...(body !== undefined ? { body: JSON.stringify(body) } : {}),
    });
  } catch (cause) {
    if (cause instanceof DOMException && cause.name === "AbortError") throw cause;
    throw new NetworkProblem(cause);
  }

  if (!response.ok) throw await problemFrom(response);
  if (response.status === 204) return undefined as T;
  return (await response.json()) as T;
}

/* --- platform ---------------------------------------------------------- */

export const getReady = () => request<ReadyResponse>("/readyz");

/* --- age gate (FR-1) --------------------------------------------------- */

export const confirmAge = () =>
  request<void>("/age-gate", { method: "POST", body: { confirmed: true } });

/* --- conversations ----------------------------------------------------- */

export interface ListParams {
  cursor?: string | null;
  limit?: number;
  archived?: boolean;
  q?: string;
}

export function listConversations(params: ListParams = {}) {
  const search = new URLSearchParams();
  if (params.cursor) search.set("cursor", params.cursor);
  search.set("limit", String(params.limit ?? 20));
  if (params.archived) search.set("archived", "true");
  // Title substring only: message bodies need an FTS5 table that does not exist.
  if (params.q?.trim()) search.set("q", params.q.trim());
  return request<ConversationPage>(`/conversations?${search.toString()}`);
}

export const createConversation = (title?: string) =>
  request<ConversationSummary>("/conversations", {
    method: "POST",
    body: title ? { title } : {},
  });

export const getConversation = (cid: string) =>
  request<ConversationDetail>(`/conversations/${cid}`);

export const patchConversation = (cid: string, patch: { title?: string; archived?: boolean }) =>
  request<ConversationSummary>(`/conversations/${cid}`, { method: "PATCH", body: patch });

export const deleteConversation = (cid: string) =>
  request<void>(`/conversations/${cid}`, { method: "DELETE" });

/* --- turns ------------------------------------------------------------- */

export const sendMessage = (
  cid: string,
  body: { content: string; selected_chip_id?: string | null },
  idempotencyKey: string,
) =>
  request<SendMessageResponse>(`/conversations/${cid}/messages`, {
    method: "POST",
    body,
    headers: { "Idempotency-Key": idempotencyKey },
  });

export const cancelTurn = (turnId: string) =>
  request<void>(`/turns/${turnId}/cancel`, { method: "POST" });

/* --- feedback (FR-9) --------------------------------------------------- */

export const sendFeedback = (messageId: string, rowId: string, vote: Vote) =>
  request<void>(`/messages/${messageId}/feedback`, {
    method: "POST",
    body: { row_id: rowId, vote },
  });

/* --- meta -------------------------------------------------------------- */

export const getTasteAxes = () => request<TasteAxesResponse>("/meta/taste-axes");
export const getDatasetVersion = () => request<DatasetVersionResponse>("/meta/dataset-version");
export const getUsage = () => request<UsageResponse>("/meta/usage");
