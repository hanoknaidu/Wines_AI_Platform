/** The seven SSE frames, as `services/runner.py` publishes them.
 *
 * Two shapes exist for the same event name, and conflating them is the subtlest bug
 * available in this client:
 *
 *   LIVE      a turn in flight publishes `token` frames carrying turn_id and
 *             anchor_seq, one frame per chunk.
 *   REPLAY    `turns.py:_part_to_event` maps a persisted part back onto its frame, so
 *             a whole coalesced text run replays as ONE `token` frame carrying only
 *             `{text}` — no turn_id, no anchor_seq.
 *
 * Hence every field a replay cannot supply is optional here.
 */

import type { Card, Chips, Intent, TurnStatus } from "./api";

export interface TokenFrame {
  turn_id?: string;
  text: string;
  /** The seq of the FIRST token of the current run. Resume uses anchor_seq - 1 so the
   *  run replays whole, rather than resuming into half a sentence. Absent on replay,
   *  where the frame already IS the whole run. */
  anchor_seq?: number;
}

export type CardFrame = Card & { turn_id?: string };
export type ChipsFrame = Chips & { turn_id?: string };

export interface CitationFrame {
  turn_id?: string;
  row_ids: string[];
  dataset_version: string;
}

export interface UsageFrame {
  turn_id: string;
  intent: Intent | "unknown";
  intent_confidence: number;
  model: string;
  engine: string;
  tokens_in: number;
  tokens_out: number;
  cost_usd: number;
  cache_hit: boolean;
  degraded: boolean;
  /** Why the answer degraded, when it did: a cost ceiling, a provider outage, or a
   *  verifier repair that replaced generated prose with copy drawn from the row.
   *  Null on a normal turn. Present so a turn that silently fell back to templated
   *  copy is visible rather than merely cheaper. */
  degraded_reason: string | null;
  latency_ms: number;
}

export interface DoneFrame {
  turn_id: string | null;
  /** "idle" means: the stream is caught up and nothing is pending. It arrives with no
   *  `id:`, so it must not move the resume cursor. Without handling it, a client
   *  renders a finished transcript and then waits on a spinner forever. */
  status: TurnStatus | "idle";
  row_ids?: string[];
  seq?: number;
  replay?: boolean;
}

export interface ErrorFrame {
  turn_id?: string | null;
  code?: string;
  title?: string;
  detail: string;
}

export type FrameName = "token" | "card" | "chips" | "citation" | "usage" | "done" | "error";

export type Frame =
  | { name: "token"; id: number | null; data: TokenFrame }
  | { name: "card"; id: number | null; data: CardFrame }
  | { name: "chips"; id: number | null; data: ChipsFrame }
  | { name: "citation"; id: number | null; data: CitationFrame }
  | { name: "usage"; id: number | null; data: UsageFrame }
  | { name: "done"; id: number | null; data: DoneFrame }
  | { name: "error"; id: number | null; data: ErrorFrame };
