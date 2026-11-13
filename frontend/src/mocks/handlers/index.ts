/** MSW handlers: the backend's surface, at the same paths, with the same status codes.
 *  Swapping to the real FastAPI is VITE_USE_MOCKS=false — not a refactor. */

import { HttpResponse, http, delay } from "msw";
import { API_BASE } from "@/lib/constants";
import * as db from "../db";
import { BUILT_AT, DATASET_VERSION, ROWS, reviewStatusCounts } from "../engine";
import { CONFIDENCE_THRESHOLD, AXES, REFINE_CHIPS, styleOptions } from "../engine/axes";
import * as stream from "../stream";
import { detail, summary } from "../view";
import { ageGuard, problem, readyGuard, takeForced } from "./shared";
import type { SendMessageResponse } from "@/types/api";

const url = (path: string) => `${API_BASE}${path}`;

export const handlers = [
  /* --- platform ---------------------------------------------------------- */

  http.get(url("/healthz"), () => HttpResponse.json({ status: "ok" })),

  http.get(url("/readyz"), async () => {
    await delay(60);
    if (!db.db.ready) {
      return HttpResponse.json(
        {
          status: "not_ready",
          db: "ok",
          row_count: 0,
          indexes: {},
          engine: "deterministic",
          serving: {},
        },
        { status: 503 },
      );
    }
    return HttpResponse.json({
      status: "ready",
      db: "ok",
      dataset_version: DATASET_VERSION,
      row_count: ROWS.length,
      indexes: { by_style: 5, by_row_id: ROWS.length },
      engine: "deterministic",
      serving: {},
    });
  }),

  /* --- age gate (FR-1) --------------------------------------------------- */

  http.post(url("/age-gate"), async ({ request }) => {
    const body = (await request.json()) as { confirmed?: boolean };
    if (!body?.confirmed) {
      return problem(
        400,
        "age_not_confirmed",
        "Age confirmation required",
        "Confirmation must be explicit.",
      );
    }
    await delay(140);
    db.db.age_confirmed = true;
    db.save();
    return new HttpResponse(null, { status: 204 });
  }),

  /* --- conversations ----------------------------------------------------- */

  http.get(url("/conversations"), async ({ request }) => {
    const blocked = ageGuard() ?? readyGuard();
    if (blocked) return blocked;
    await delay(130);
    const params = new URL(request.url).searchParams;
    const page = db.listPage({
      limit: Math.min(Number(params.get("limit") ?? 20), 100),
      cursor: params.get("cursor"),
      archived: params.get("archived") === "true",
      q: params.get("q"),
    });
    return HttpResponse.json({
      items: page.items.map(summary),
      next_cursor: page.next_cursor,
    });
  }),

  http.post(url("/conversations"), async ({ request }) => {
    const blocked = ageGuard() ?? readyGuard() ?? takeForced();
    if (blocked) return blocked;
    const body = (await request.json().catch(() => ({}))) as { title?: string };
    await delay(90);
    const row = db.createConversation(body?.title || stream.NEW_TITLE);
    return HttpResponse.json(summary(row), { status: 201 });
  }),

  http.get(url("/conversations/:cid"), async ({ params }) => {
    const blocked = ageGuard() ?? readyGuard();
    if (blocked) return blocked;
    await delay(110);
    const row = db.getConversation(params.cid as string);
    if (!row) {
      return problem(
        404,
        "conversation_not_found",
        "Conversation not found",
        `No conversation ${params.cid}.`,
      );
    }
    return HttpResponse.json(detail(row));
  }),

  http.patch(url("/conversations/:cid"), async ({ params, request }) => {
    const blocked = ageGuard() ?? takeForced();
    if (blocked) return blocked;
    const body = (await request.json()) as { title?: string; archived?: boolean };
    await delay(80);
    const row = db.patchConversation(params.cid as string, body);
    if (!row) {
      return problem(
        404,
        "conversation_not_found",
        "Conversation not found",
        `No conversation ${params.cid}.`,
      );
    }
    return HttpResponse.json(summary(row));
  }),

  http.delete(url("/conversations/:cid"), async ({ params }) => {
    const blocked = ageGuard() ?? takeForced();
    if (blocked) return blocked;
    await delay(80);
    const ok = db.softDelete(params.cid as string);
    if (!ok) {
      return problem(
        404,
        "conversation_not_found",
        "Conversation not found",
        `No conversation ${params.cid}.`,
      );
    }
    return new HttpResponse(null, { status: 204 });
  }),

  /* --- turns ------------------------------------------------------------- */

  http.post(url("/conversations/:cid/messages"), async ({ params, request }) => {
    const blocked = ageGuard() ?? readyGuard() ?? takeForced();
    if (blocked) return blocked;

    const cid = params.cid as string;
    const key = request.headers.get("Idempotency-Key");
    const body = (await request.json()) as {
      content: string;
      selected_chip_id?: string | null;
    };

    if (!key) {
      return problem(
        400,
        "idempotency_key_required",
        "Idempotency-Key required",
        "Send an Idempotency-Key header so a retried send cannot start a second turn.",
      );
    }

    const hash = db.hashRequest({
      cid,
      content: body.content,
      chip: body.selected_chip_id ?? null,
    });
    const existing = db.idempotencyGet(key);
    if (existing) {
      if (existing.request_hash !== hash) {
        return problem(
          409,
          "idempotency_key_reused",
          "Idempotency-Key reused",
          "That Idempotency-Key was used for a different request body.",
        );
      }
      // Replay: return the original body and start nothing. The cheapest cost control
      // in the system — a retried send never pays twice.
      return HttpResponse.json(existing.response as SendMessageResponse, { status: 202 });
    }

    const conversation = db.getConversation(cid);
    if (!conversation) {
      return problem(
        404,
        "conversation_not_found",
        "Conversation not found",
        `No conversation ${cid}.`,
      );
    }

    // One in-flight turn per conversation: two concurrent turns drawing on the same
    // seq sequence would interleave their SSE ids and break resume.
    const active = stream.activeForConversation(cid);
    if (active) {
      return problem(
        409,
        "turn_in_flight",
        "A turn is already running",
        `Turn ${active.turnId} is still in flight for this conversation. Wait for it or cancel it.`,
      );
    }

    if (!body.content?.trim() || body.content.length > 2000) {
      return problem(
        422,
        "validation_error",
        "Invalid request",
        "The request body failed validation.",
      );
    }

    const turnId = db.newRowId("t");
    const userSeq = db.nextSeq(cid);
    const message = db.addMessage({ cid, role: "user", seq: userSeq, turn_id: turnId });
    db.addPart({
      message_id: message.id,
      cid,
      kind: "text",
      seq: db.nextSeq(cid),
      text: body.content,
    });

    // Auto-named from turn 1, mirroring the sidebar's behaviour.
    if (conversation.title === stream.NEW_TITLE) {
      conversation.title = stream.titleFrom(body.content);
    }
    conversation.updated_at = new Date().toISOString();
    db.save();

    stream.startTurn({ cid, turnId, utterance: body.content, chipId: body.selected_chip_id });

    const response = { turn_id: turnId, user_message_id: message.id, seq: userSeq };
    db.idempotencyPut(key, hash, response);
    return HttpResponse.json(response, { status: 202 });
  }),

  http.get(url("/conversations/:cid/stream"), ({ params, request }) => {
    const blocked = ageGuard();
    if (blocked) return blocked;
    const cid = params.cid as string;
    if (!db.getConversation(cid)) {
      return problem(
        404,
        "conversation_not_found",
        "Conversation not found",
        `No conversation ${cid}.`,
      );
    }
    const after = Number(new URL(request.url).searchParams.get("after") ?? 0);
    return new HttpResponse(stream.buildStream(cid, Number.isFinite(after) ? after : 0), {
      headers: {
        "Content-Type": "text/event-stream",
        "Cache-Control": "no-cache",
        Connection: "keep-alive",
        "X-Accel-Buffering": "no",
      },
    });
  }),

  http.post(url("/turns/:turnId/cancel"), async ({ params }) => {
    const blocked = ageGuard();
    if (blocked) return blocked;
    const ok = stream.cancelTurn(params.turnId as string);
    if (!ok) {
      return problem(
        404,
        "turn_not_found",
        "Turn not found",
        `Turn ${params.turnId} is unknown or has expired.`,
      );
    }
    return new HttpResponse(null, { status: 204 });
  }),

  /* --- feedback (FR-9) --------------------------------------------------- */

  http.post(url("/messages/:mid/feedback"), async ({ params, request }) => {
    const blocked = ageGuard();
    if (blocked) return blocked;
    const mid = params.mid as string;
    const body = (await request.json()) as { row_id: string; vote: "up" | "down" };
    const message = db.getMessage(mid);
    if (!message) {
      return problem(404, "message_not_found", "Message not found", `No message ${mid}.`);
    }
    // A vote against a row the message never cited is either a client bug or a forged
    // request, and silently accepting it poisons the only honest signal collected here.
    if (!db.messageRowIds(mid).includes(body.row_id)) {
      return problem(
        409,
        "row_not_cited",
        "Row not cited by that message",
        `Message ${mid} did not cite row ${body.row_id}.`,
      );
    }
    await delay(70);
    db.upsertFeedback({ message_id: mid, row_id: body.row_id, vote: body.vote });
    return new HttpResponse(null, { status: 204 });
  }),

  /* --- meta -------------------------------------------------------------- */

  http.get(url("/meta/taste-axes"), async () => {
    await delay(60);
    return HttpResponse.json({
      axes: AXES.map((axis) => ({
        id: axis.id,
        asked: axis.asked,
        question_order: axis.question_order,
        prompt: axis.prompt,
        applies_to: [...axis.applies_to],
        levels: axis.levels,
      })),
      refine_chips: REFINE_CHIPS,
      confidence_threshold: CONFIDENCE_THRESHOLD,
      styles: styleOptions(),
    });
  }),

  http.get(url("/meta/dataset-version"), async () => {
    await delay(60);
    if (!db.db.ready) {
      return problem(
        503,
        "dataset_unavailable",
        "Recommendations unavailable",
        "The wine dataset is not loaded, so no recommendation can be grounded in it.",
      );
    }
    return HttpResponse.json({
      dataset_version: DATASET_VERSION,
      row_count: ROWS.length,
      review_status_counts: reviewStatusCounts(),
      built_at: BUILT_AT,
      checksum: "mock-sha256-not-a-real-digest",
    });
  }),

  http.get(url("/meta/usage"), async () => {
    const usage = db.sessionUsage();
    return HttpResponse.json({
      ...usage,
      cost_usd: Number(usage.cost_usd.toFixed(6)),
      engine: "deterministic",
      ceiling_per_session_usd: 0.5,
      degraded: false,
    });
  }),
];
