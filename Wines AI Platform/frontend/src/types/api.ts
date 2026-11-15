/** The wire contract, typed by hand against backend `schemas.py`.
 *
 * snake_case, deliberately: the architecture diagram writes turn_id / row_id /
 * dataset_version, the backend's `wire_case` defaults to `snake`, and this file is the
 * reason that setting never has to change (backend §15 Q1). Nothing in the client
 * renames a field on the way in — a mapper layer would be one more place for the two
 * sides to disagree.
 */

export type Vote = "up" | "down";
export type Role = "user" | "assistant";
export type PartKind = "text" | "card" | "chips" | "citation" | "error";
export type Intent = "interview" | "recommend" | "refine" | "out_of_scope";
export type TurnStatus = "ok" | "cancelled" | "error";

/** One taste axis as served. `label` is ALREADY hedged where confidence is low — the
 *  client renders it verbatim and never recomputes the hedge. */
export interface AxisReading {
  value: string;
  confidence: number;
  label: string;
}

export interface Card {
  row_id: string;
  variety: string;
  style: string;
  axes: Record<string, AxisReading>;
  description: string;
  why_it_matches: string;
  typical_regions: string[];
  /** Empty is the honest state (FR-11), not missing data. */
  example_producers: string[];
  review_status: string;
  dataset_version: string;
}

export interface ChipOption {
  id: string;
  label: string;
  value?: string | null;
}

export interface Chips {
  kind: "interview" | "refine";
  axis?: string | null;
  prompt?: string | null;
  options: ChipOption[];
}

export interface MessagePart {
  id: string;
  kind: PartKind;
  seq: number;
  text?: string | null;
  card?: Card | null;
  chips?: Chips | null;
  citation?: { row_ids: string[]; dataset_version: string } | null;
  row_id?: string | null;
}

export interface Message {
  id: string;
  role: Role;
  seq: number;
  turn_id?: string | null;
  created_at: string;
  parts: MessagePart[];
}

export interface TasteProfile {
  style?: string | null;
  sweetness?: string | null;
  body?: string | null;
  oak?: string | null;
  tannin?: string | null;
  acidity?: string | null;
  fruit_savoury?: string | null;
  /** axis -> { confidence, provenance: "asked" | "inferred" | "refined" } */
  confidence: Record<string, { confidence?: number; provenance?: string }>;
}

export interface ConversationSummary {
  id: string;
  title: string;
  created_at: string;
  updated_at: string;
  archived: boolean;
  dataset_version: string;
}

export interface ConversationPage {
  items: ConversationSummary[];
  next_cursor: string | null;
}

export interface ConversationDetail extends ConversationSummary {
  /** Reported rather than silently re-served under a different artifact. */
  dataset_version_stale: boolean;
  served_dataset_version: string;
  taste_profile: TasteProfile;
  messages: Message[];
}

export interface SendMessageResponse {
  turn_id: string;
  user_message_id: string;
  seq: number;
}

export interface AxisLevel {
  value: string;
  label: string;
  hedged_label: string;
}

export interface AxisSpec {
  id: string;
  asked: boolean;
  question_order: number | null;
  prompt: string | null;
  applies_to: string[];
  levels: AxisLevel[];
}

export interface RefineChipSpec {
  id: string;
  label: string;
  axis: string;
  delta: number;
}

/** The single source of truth for vocabulary. No wine word is hardcoded in a
 *  component; every label, level, hedge and chip comes from here. */
export interface TasteAxesResponse {
  axes: AxisSpec[];
  refine_chips: RefineChipSpec[];
  confidence_threshold: number;
  styles: ChipOption[];
}

export interface DatasetVersionResponse {
  dataset_version: string;
  row_count: number;
  review_status_counts: Record<string, number>;
  built_at: string | null;
  checksum: string;
}

export interface UsageResponse {
  turns: number;
  tokens_in: number;
  tokens_out: number;
  cost_usd: number;
  engine: string;
  cache_hits: number;
  ceiling_per_session_usd: number;
  degraded: boolean;
}

export interface ReadyResponse {
  status: "ready" | "not_ready";
  db: string;
  dataset_version?: string | null;
  row_count: number;
  indexes: Record<string, number>;
  engine: string;
  /** What the serving path actually is. Empty for the deterministic engine; for the
   *  orchestrated engine it carries the model provider (`offline` or `anthropic`),
   *  the four model ids, and the retrieval indexes that were loaded. Readiness has to
   *  answer "ready to serve what". */
  serving: Record<string, unknown>;
}

/** RFC 9457 problem+json. Every failure carries a stable `code` and a `request_id`,
 *  and never a stack trace (NFR-7). */
export interface ProblemBody {
  type: string;
  title: string;
  status: number;
  detail: string;
  code: string;
  request_id?: string | null;
}
