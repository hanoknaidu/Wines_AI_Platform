/** Frames in, renderable blocks out. The core of this client.
 *
 * Three rules this reducer exists to enforce, each of which is a bug if you get it
 * wrong and each of which comes from reading `services/runner.py`:
 *
 * 1. A text run is keyed by its ANCHOR seq, not by the seq of each token. Live, the
 *    run arrives as many `token` frames all carrying the same `anchor_seq`; persisted,
 *    the same run is ONE text part at exactly that seq. Keying on the anchor means a
 *    replayed transcript and a live stream produce the same block at the same key, so
 *    the two sources merge by seq with no flicker and no duplication.
 *
 * 2. Resume is `anchor_seq - 1` mid-run, `lastSeq` otherwise. And because asking the
 *    server to replay from the anchor means we will receive that run again, we must
 *    first DISCARD what we hold from the anchor onwards — otherwise a run that
 *    completed server-side while we were disconnected replays as one coalesced frame
 *    that we then skip as a duplicate, leaving the truncated text on screen forever.
 *
 * 3. A frame with no `id:` must not move the resume cursor. The idle `done` is sent
 *    exactly that way, deliberately.
 */

import type { Card, Chips } from "@/types/api";
import type { Frame, UsageFrame } from "@/types/sse";

export type Block =
  | { kind: "text"; seq: number; text: string }
  | { kind: "card"; seq: number; card: Card }
  | { kind: "chips"; seq: number; chips: Chips }
  | { kind: "citation"; seq: number; rowIds: string[]; datasetVersion: string }
  | { kind: "error"; seq: number; code: string | null; title: string | null; detail: string };

export type StreamPhase = "connecting" | "idle" | "streaming" | "done" | "cancelled" | "error";

export interface LiveState {
  blocks: Record<number, Block>;
  /** Highest frame seq applied. Duplicates at or below this are dropped. */
  appliedUpTo: number;
  /** Where to resume from when nothing is mid-run. */
  lastSeq: number;
  /** Anchor of the text run in progress, or null between runs. */
  runAnchor: number | null;
  turnId: string | null;
  phase: StreamPhase;
  usage: UsageFrame | null;
  /** True once the server has said there is nothing pending — either an idle `done`
   *  on catch-up or a real `done` closing a turn. Until then a spinner is honest. */
  caughtUp: boolean;
}

export type LiveAction =
  | { type: "frame"; frame: Frame }
  | { type: "turn-started"; turnId: string }
  | { type: "prepare-resume" }
  | { type: "connecting" }
  | { type: "reset"; after?: number };

export function initialLive(after = 0): LiveState {
  return {
    blocks: {},
    appliedUpTo: after,
    lastSeq: after,
    runAnchor: null,
    turnId: null,
    phase: "connecting",
    usage: null,
    caughtUp: false,
  };
}

/** The `?after=` value for the next connection. */
export function resumeAfter(state: LiveState): number {
  return state.runAnchor !== null ? Math.max(0, state.runAnchor - 1) : state.lastSeq;
}

export function liveReducer(state: LiveState, action: LiveAction): LiveState {
  switch (action.type) {
    case "reset":
      return initialLive(action.after ?? 0);

    case "connecting":
      return { ...state, phase: state.phase === "streaming" ? "streaming" : "connecting" };

    case "turn-started": {
      // `noteSend` dispatches this when POST .../messages RESOLVES, which is not
      // necessarily before that turn's frames arrive. A deterministic interview turn is
      // two tokens and a chip row, so the server can finish it - and the stream can
      // deliver `token`, `chips`, `usage` and the terminal `done` in a single chunk -
      // while the client is still unwrapping the POST's own HTTP response.
      //
      // Re-arming to "streaming" there is unrecoverable: the turn is over, every frame
      // it will ever emit has been applied, and nothing remains to move the phase on.
      // The composer and the chip dock are disabled off `isStreaming`, so the UI stays
      // locked with a spinner up and nothing coming. It is intermittent and it is worst
      // on the FASTEST turn, which is why it survived a suite that only ever drove slow
      // ones against instant mocks.
      //
      // `done`/`token` frames carry `turn_id`, so "this exact turn already finished" is
      // answerable rather than guessed at.
      const finished =
        state.turnId === action.turnId &&
        (state.phase === "done" || state.phase === "cancelled" || state.phase === "error");
      if (finished) return state;
      return {
        ...state,
        turnId: action.turnId,
        phase: "streaming",
        caughtUp: false,
        usage: null,
      };
    }

    case "prepare-resume": {
      if (state.runAnchor === null) return state;
      const anchor = state.runAnchor;
      const blocks: Record<number, Block> = {};
      for (const [key, block] of Object.entries(state.blocks)) {
        if (Number(key) < anchor) blocks[Number(key)] = block;
      }
      return {
        ...state,
        blocks,
        runAnchor: null,
        appliedUpTo: anchor - 1,
        lastSeq: anchor - 1,
      };
    }

    case "frame":
      return applyFrame(state, action.frame);
  }
}

function applyFrame(state: LiveState, frame: Frame): LiveState {
  const { id, name } = frame;

  // A frame with an id we have already applied is a replay of something we hold.
  // Dropping it by seq is what makes reconnecting safe to do at any moment.
  if (id !== null && id <= state.appliedUpTo && name !== "done") return state;

  const advanced =
    id !== null
      ? { appliedUpTo: Math.max(state.appliedUpTo, id), lastSeq: Math.max(state.lastSeq, id) }
      : {};

  switch (name) {
    case "token": {
      // `anchor_seq` live; the frame's own id on replay, where the frame IS the run.
      const key = frame.data.anchor_seq ?? id;
      if (key === null) return state;
      const existing = state.blocks[key];
      const text = (existing?.kind === "text" ? existing.text : "") + frame.data.text;
      return {
        ...state,
        ...advanced,
        blocks: { ...state.blocks, [key]: { kind: "text", seq: key, text } },
        runAnchor: key,
        turnId: frame.data.turn_id ?? state.turnId,
        phase: "streaming",
      };
    }

    case "card": {
      if (id === null) return state;
      const { turn_id, ...card } = frame.data;
      return {
        ...state,
        ...advanced,
        // Any non-token frame closes the current text run.
        runAnchor: null,
        blocks: { ...state.blocks, [id]: { kind: "card", seq: id, card: card as Card } },
        turnId: turn_id ?? state.turnId,
        phase: "streaming",
      };
    }

    case "chips": {
      if (id === null) return state;
      const { turn_id, ...chips } = frame.data;
      return {
        ...state,
        ...advanced,
        runAnchor: null,
        blocks: { ...state.blocks, [id]: { kind: "chips", seq: id, chips: chips as Chips } },
        turnId: turn_id ?? state.turnId,
        phase: "streaming",
      };
    }

    case "citation": {
      if (id === null) return state;
      return {
        ...state,
        ...advanced,
        runAnchor: null,
        blocks: {
          ...state.blocks,
          [id]: {
            kind: "citation",
            seq: id,
            rowIds: frame.data.row_ids,
            datasetVersion: frame.data.dataset_version,
          },
        },
      };
    }

    case "error": {
      const seq = id ?? state.lastSeq + 1;
      return {
        ...state,
        ...advanced,
        runAnchor: null,
        phase: "error",
        blocks: {
          ...state.blocks,
          [seq]: {
            kind: "error",
            seq,
            code: frame.data.code ?? null,
            title: frame.data.title ?? null,
            detail: frame.data.detail,
          },
        },
      };
    }

    case "usage":
      return { ...state, ...advanced, usage: frame.data };

    case "done": {
      // "idle" means caught up with nothing pending. It carries no id on purpose, so
      // it must not move the cursor — and it only arrives when something was actually
      // replayed, so its absence never means "still loading".
      if (frame.data.status === "idle") {
        return { ...state, caughtUp: true, runAnchor: null, phase: "idle" };
      }
      if (id !== null && id <= state.appliedUpTo && state.caughtUp) return state;
      const phase: StreamPhase =
        frame.data.status === "cancelled"
          ? "cancelled"
          : frame.data.status === "error"
            ? "error"
            : "done";
      return { ...state, ...advanced, runAnchor: null, caughtUp: true, phase };
    }
  }
}

export function sortedBlocks(state: LiveState): Block[] {
  return Object.values(state.blocks).sort((a, b) => a.seq - b.seq);
}
