/** The mock's turn runner and SSE transport. Mirrors `services/runner.py` and
 *  `api/v1/turns.py:stream` closely, because the subtleties this client has to handle
 *  are all in here:
 *
 *   - one seq allocator per conversation, shared by messages, parts and frames
 *   - a text run coalesced into ONE persisted part under its anchor seq, while the
 *     live stream emits one frame per word
 *   - `?after=` replay, then the in-flight turn's live buffer, then the tail — so
 *     there is never a hole between the last committed part and the live edge
 *   - the idle `done`, with no `id:`, only when something was actually replayed
 *   - one in-flight turn per conversation, and cancellation that stops mid-run
 *
 * A mock that skipped any of these would let the client's resume logic ship untested.
 */

import * as db from "./db";
import { DATASET_VERSION, runTurn as runEngine } from "./engine";
import type { EngineEvent } from "./engine/types";
import type { FrameName } from "@/types/sse";

const STREAM_TOKEN_DELAY_MS = 12;
const KEEPALIVE_MS = 15_000;

export interface Published {
  seq: number;
  name: FrameName;
  data: Record<string, unknown>;
}

interface InFlight {
  turnId: string;
  cid: string;
  buffer: Published[];
  cancelled: boolean;
}

const byConversation = new Map<string, InFlight>();
const byTurn = new Map<string, InFlight>();
const subscribers = new Map<string, Set<(event: Published) => void>>();
const openStreams = new Set<{ cid: string; close: () => void }>();

const sleep = (ms: number) => new Promise<void>((resolve) => window.setTimeout(resolve, ms));

export const activeForConversation = (cid: string) => byConversation.get(cid) ?? null;
export const activeTurn = (turnId: string) => byTurn.get(turnId) ?? null;

function publish(cid: string, event: Published): void {
  const set = subscribers.get(cid);
  if (!set) return;
  for (const handler of set) handler(event);
}

function subscribe(cid: string, handler: (event: Published) => void): () => void {
  let set = subscribers.get(cid);
  if (!set) {
    set = new Set();
    subscribers.set(cid, set);
  }
  set.add(handler);
  return () => {
    set?.delete(handler);
    if (set && set.size === 0) subscribers.delete(cid);
  };
}

/* --- running a turn ------------------------------------------------------ */

export function startTurn(args: {
  cid: string;
  turnId: string;
  utterance: string;
  chipId?: string | null;
}): InFlight {
  const entry: InFlight = { turnId: args.turnId, cid: args.cid, buffer: [], cancelled: false };
  byConversation.set(args.cid, entry);
  byTurn.set(args.turnId, entry);
  void drive(entry, args.utterance, args.chipId ?? null);
  return entry;
}

export function cancelTurn(turnId: string): boolean {
  const entry = byTurn.get(turnId);
  if (!entry) return false;
  entry.cancelled = true;
  return true;
}

async function drive(entry: InFlight, utterance: string, chipId: string | null): Promise<void> {
  const { cid, turnId } = entry;
  const started = performance.now();
  const events = runEngine({
    utterance,
    selected_chip_id: chipId,
    profile: db.profileValues(cid),
    previous_row_ids: db.lastCitedRowIds(cid),
  });

  let status = "ok";
  let assistantId: string | null = null;
  let runAnchor: number | null = null;
  let chunks: string[] = [];
  const cited: string[] = [];
  let usage = { intent: "unknown", intent_confidence: 0, model: "deterministic" };

  const emit = (name: FrameName, data: Record<string, unknown>): number => {
    const seq = db.nextSeq(cid);
    const event: Published = { seq, name, data };
    entry.buffer.push(event);
    publish(cid, event);
    return seq;
  };

  const ensureAssistant = (): string => {
    if (assistantId === null) {
      assistantId = db.addMessage({
        cid,
        role: "assistant",
        seq: db.nextSeq(cid),
        turn_id: turnId,
      }).id;
    }
    return assistantId;
  };

  // Persisting one row per token would turn a 300-word answer into 400 writes for no
  // readable benefit, so a run is coalesced into a single part under its anchor seq.
  const closeRun = (): void => {
    if (chunks.length && runAnchor !== null && assistantId !== null) {
      db.addPart({
        message_id: assistantId,
        cid,
        kind: "text",
        seq: runAnchor,
        text: chunks.join(""),
      });
    }
    chunks = [];
    runAnchor = null;
  };

  try {
    for (const event of events as EngineEvent[]) {
      if (entry.cancelled) {
        status = "cancelled";
        break;
      }

      if (event.t === "profile") {
        db.mergeProfile(cid, event.values, event.confidence);
        continue;
      }
      if (event.t === "usage") {
        usage = {
          intent: event.intent,
          intent_confidence: event.intent_confidence,
          model: event.model,
        };
        continue;
      }

      const messageId = ensureAssistant();

      if (event.t === "token") {
        // Word by word on an uneven cadence: the client's cursor, its stop button and
        // its no-layout-shift guarantees have to be tested against something that
        // behaves like a stream, and `?after=` cannot be tested at all against an
        // instant response.
        const words = event.text.split(" ");
        for (let i = 0; i < words.length; i += 1) {
          if (entry.cancelled) {
            status = "cancelled";
            break;
          }
          const text = i === words.length - 1 ? words[i] : `${words[i]} `;
          const seq = db.nextSeq(cid);
          if (runAnchor === null) runAnchor = seq;
          chunks.push(text);
          const frame: Published = {
            seq,
            name: "token",
            // anchor_seq lets a client that drops mid-run reconnect at anchor - 1 and
            // get the whole run back, rather than resuming into half a sentence.
            data: { turn_id: turnId, text, anchor_seq: runAnchor },
          };
          entry.buffer.push(frame);
          publish(cid, frame);
          await sleep(STREAM_TOKEN_DELAY_MS * (i % 4 === 3 ? 2 : 1));
        }
        if (status === "cancelled") break;
        continue;
      }

      // Any non-token event closes the current text run.
      closeRun();

      if (event.t === "card") {
        const seq = db.nextSeq(cid);
        db.addPart({
          message_id: messageId,
          cid,
          kind: "card",
          seq,
          card_json: event.card,
          row_id: event.row_id,
        });
        cited.push(event.row_id);
        const frame: Published = {
          seq,
          name: "card",
          data: { turn_id: turnId, ...event.card },
        };
        entry.buffer.push(frame);
        publish(cid, frame);
        continue;
      }

      if (event.t === "chips") {
        const seq = db.nextSeq(cid);
        db.addPart({
          message_id: messageId,
          cid,
          kind: "chips",
          seq,
          chips_json: event.chips,
        });
        const frame: Published = {
          seq,
          name: "chips",
          data: { turn_id: turnId, ...event.chips },
        };
        entry.buffer.push(frame);
        publish(cid, frame);
        continue;
      }

      if (event.t === "citation") {
        const citation = { row_ids: event.row_ids, dataset_version: DATASET_VERSION };
        const seq = db.nextSeq(cid);
        db.addPart({
          message_id: messageId,
          cid,
          kind: "citation",
          seq,
          citation_json: citation,
        });
        const frame: Published = {
          seq,
          name: "citation",
          data: { turn_id: turnId, ...citation },
        };
        entry.buffer.push(frame);
        publish(cid, frame);
      }
    }
    closeRun();
  } catch {
    status = "error";
    emit("error", {
      turn_id: turnId,
      code: "engine_error",
      title: "The recommendation could not be completed",
      detail: "Something went wrong while answering. Try again.",
    });
  } finally {
    const latency = Math.round(performance.now() - started);

    // One transaction_log row per turn, without exception. A cost of $0.00 is still a
    // row — the accounting path has to be exercised before real models make it
    // expensive to discover it was wrong.
    db.writeTurn({
      conversation_id: cid,
      turn_id: turnId,
      intent: usage.intent,
      intent_confidence: usage.intent_confidence,
      model: usage.model,
      engine: "deterministic",
      tokens_in: 0,
      tokens_out: 0,
      cost_usd: 0,
      latency_ms: latency,
      status,
      cache_hit: false,
    });

    emit("usage", {
      turn_id: turnId,
      intent: usage.intent,
      intent_confidence: usage.intent_confidence,
      model: usage.model,
      engine: "deterministic",
      tokens_in: 0,
      tokens_out: 0,
      cost_usd: 0,
      cache_hit: false,
      degraded: false,
      degraded_reason: null,
      latency_ms: latency,
    });

    const doneSeq = db.nextSeq(cid);
    const done: Published = {
      seq: doneSeq,
      name: "done",
      data: { turn_id: turnId, status, row_ids: cited, seq: doneSeq },
    };
    entry.buffer.push(done);
    publish(cid, done);

    byConversation.delete(cid);
    byTurn.delete(turnId);
  }
}

/** The same path with no streaming and no delay, for seeding fixtures. Fixtures are
 *  therefore GENERATED by the engine rather than written by hand — they cannot drift
 *  from what the live engine produces. */
export function seedTurn(args: {
  cid: string;
  utterance: string;
  chipId?: string | null;
  at: Date;
}): void {
  const { cid, at } = args;
  const turnId = db.newRowId("t");
  const iso = at.toISOString();

  const userMessage = db.addMessage({
    cid,
    role: "user",
    seq: db.nextSeq(cid),
    turn_id: turnId,
    created_at: iso,
  });
  db.addPart({
    message_id: userMessage.id,
    cid,
    kind: "text",
    seq: db.nextSeq(cid),
    text: args.utterance,
  });

  const events = runEngine({
    utterance: args.utterance,
    selected_chip_id: args.chipId ?? null,
    profile: db.profileValues(cid),
    previous_row_ids: db.lastCitedRowIds(cid),
  });

  let assistantId: string | null = null;
  const ensureAssistant = (): string => {
    if (assistantId === null) {
      assistantId = db.addMessage({
        cid,
        role: "assistant",
        seq: db.nextSeq(cid),
        turn_id: turnId,
        created_at: iso,
      }).id;
    }
    return assistantId;
  };

  let chunks: string[] = [];
  let anchor: number | null = null;
  const closeRun = () => {
    if (chunks.length && anchor !== null && assistantId !== null) {
      db.addPart({
        message_id: assistantId,
        cid,
        kind: "text",
        seq: anchor,
        text: chunks.join(""),
      });
    }
    chunks = [];
    anchor = null;
  };

  let intent = "unknown";
  let intentConfidence = 0;

  for (const event of events) {
    if (event.t === "profile") {
      db.mergeProfile(cid, event.values, event.confidence);
      continue;
    }
    if (event.t === "usage") {
      intent = event.intent;
      intentConfidence = event.intent_confidence;
      continue;
    }
    const messageId = ensureAssistant();
    if (event.t === "token") {
      if (anchor === null) anchor = db.nextSeq(cid);
      chunks.push(event.text);
      continue;
    }
    closeRun();
    const seq = db.nextSeq(cid);
    if (event.t === "card") {
      db.addPart({
        message_id: messageId,
        cid,
        kind: "card",
        seq,
        card_json: event.card,
        row_id: event.row_id,
      });
    } else if (event.t === "chips") {
      db.addPart({
        message_id: messageId,
        cid,
        kind: "chips",
        seq,
        chips_json: event.chips,
      });
    } else if (event.t === "citation") {
      db.addPart({
        message_id: messageId,
        cid,
        kind: "citation",
        seq,
        citation_json: { row_ids: event.row_ids, dataset_version: DATASET_VERSION },
      });
    }
  }
  closeRun();

  db.writeTurn({
    conversation_id: cid,
    turn_id: turnId,
    intent,
    intent_confidence: intentConfidence,
    model: "deterministic",
    engine: "deterministic",
    tokens_in: 0,
    tokens_out: 0,
    cost_usd: 0,
    latency_ms: 7,
    status: "ok",
    cache_hit: false,
  });

  const conversation = db.getConversation(cid);
  if (conversation) {
    if (conversation.title === NEW_TITLE) {
      conversation.title = titleFrom(args.utterance);
    }
    conversation.updated_at = iso;
  }
  db.save();
}

export const NEW_TITLE = "New conversation";

/** Auto-named from turn 1, mirroring the sidebar's behaviour. */
export function titleFrom(content: string): string {
  const title = content.trim();
  if (title.length <= 52) return title || NEW_TITLE;
  return `${title.slice(0, 52).trimEnd()}...`;
}

/* --- the SSE response ---------------------------------------------------- */

function frame(seq: number, name: string, data: unknown): string {
  return `id: ${seq}\nevent: ${name}\ndata: ${JSON.stringify(data)}\n\n`;
}

/** An informational frame with no `id:`. SSE leaves Last-Event-ID untouched when a
 *  frame omits it, which is exactly right for a frame that reports state rather than
 *  carrying content: it must not move the resume cursor. */
function frameNoId(name: string, data: unknown): string {
  return `event: ${name}\ndata: ${JSON.stringify(data)}\n\n`;
}

function partToFrame(part: db.PartRow): { name: string; data: unknown } | null {
  switch (part.kind) {
    case "text":
      // A coalesced text part replays as a single `token` frame carrying the whole
      // run: the client's reducer appends either way.
      return { name: "token", data: { text: part.text ?? "" } };
    case "card":
      return part.card_json ? { name: "card", data: part.card_json } : null;
    case "chips":
      return part.chips_json ? { name: "chips", data: part.chips_json } : null;
    case "citation":
      return part.citation_json ? { name: "citation", data: part.citation_json } : null;
    case "error":
      return { name: "error", data: { detail: part.text ?? "" } };
    default:
      return null;
  }
}

export function buildStream(cid: string, after: number): ReadableStream<Uint8Array> {
  const encoder = new TextEncoder();
  let unsubscribe: (() => void) | null = null;
  let keepalive: number | null = null;
  let handle: { cid: string; close: () => void } | null = null;

  return new ReadableStream<Uint8Array>({
    start(controller) {
      let closed = false;
      const push = (text: string) => {
        if (closed) return;
        try {
          controller.enqueue(encoder.encode(text));
        } catch {
          closed = true;
        }
      };

      // 1. Replay committed parts with seq > after.
      let replayedUpTo = after;
      let replayed = 0;
      for (const part of db.partsAfter(cid, after)) {
        const mapped = partToFrame(part);
        if (!mapped) continue;
        push(frame(part.seq, mapped.name, mapped.data));
        replayedUpTo = Math.max(replayedUpTo, part.seq);
        replayed += 1;
      }

      // 2. Attach the live buffer of an in-flight turn, so there is no hole between
      //    the last committed part and the live tail.
      const active = byConversation.get(cid);
      if (active) {
        for (const event of [...active.buffer]) {
          if (event.seq > replayedUpTo) {
            push(frame(event.seq, event.name, event.data));
            replayedUpTo = event.seq;
          }
        }
      } else if (replayed) {
        // We replayed history and nothing is running, so no `done` will ever arrive
        // for those turns. Without this a client renders the transcript and then waits
        // on a spinner forever. Only when something was actually replayed: a client
        // that opens the stream and THEN sends its turn has nothing to catch up on.
        push(
          frameNoId("done", { turn_id: null, status: "idle", replay: true, seq: replayedUpTo }),
        );
      }

      // 3. Tail.
      unsubscribe = subscribe(cid, (event) => {
        if (event.seq <= replayedUpTo) return;
        replayedUpTo = event.seq;
        push(frame(event.seq, event.name, event.data));
      });

      keepalive = window.setInterval(() => push(": keep-alive\n\n"), KEEPALIVE_MS);

      handle = {
        cid,
        close: () => {
          closed = true;
          try {
            controller.close();
          } catch {
            /* already closed */
          }
        },
      };
      openStreams.add(handle);
    },

    cancel() {
      unsubscribe?.();
      if (keepalive !== null) window.clearInterval(keepalive);
      if (handle) openStreams.delete(handle);
    },
  });
}

/** Force open streams to end, so the client's resume path can be exercised on
 *  demand from the styleguide instead of hoped about. */
export function dropStreams(cid?: string): number {
  let dropped = 0;
  for (const handle of [...openStreams]) {
    if (cid && handle.cid !== cid) continue;
    handle.close();
    openStreams.delete(handle);
    dropped += 1;
  }
  return dropped;
}
