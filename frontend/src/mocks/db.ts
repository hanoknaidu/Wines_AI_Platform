/** The mock's store. Stands in for SQLite + the repository layer.
 *
 * Persisted to localStorage so a page reload keeps the sidebar, the way the real
 * SQLite-backed backend would. The schema version is checked on boot and anything
 * stale is reseeded rather than migrated — this is a fixture, not a database.
 */

import type { Card, Chips, PartKind, Role, TasteProfile, Vote } from "@/types/api";
import { DATASET_VERSION } from "./engine";

const STORAGE_KEY = "wa.mock.v3";

export interface ConvRow {
  id: string;
  title: string;
  created_at: string;
  updated_at: string;
  archived_at: string | null;
  deleted_at: string | null;
  dataset_version: string;
}

export interface MsgRow {
  id: string;
  conversation_id: string;
  role: Role;
  seq: number;
  turn_id: string | null;
  created_at: string;
}

export interface PartRow {
  id: string;
  message_id: string;
  conversation_id: string;
  kind: PartKind;
  seq: number;
  text: string | null;
  card_json: Card | null;
  chips_json: Chips | null;
  citation_json: { row_ids: string[]; dataset_version: string } | null;
  row_id: string | null;
}

export interface ProfileRow {
  conversation_id: string;
  style: string | null;
  sweetness: string | null;
  body: string | null;
  oak: string | null;
  tannin: string | null;
  acidity: string | null;
  fruit_savoury: string | null;
  confidence_json: Record<string, { confidence?: number; provenance?: string }>;
}

export interface TurnLogRow {
  conversation_id: string;
  turn_id: string;
  intent: string;
  intent_confidence: number;
  model: string;
  engine: string;
  tokens_in: number;
  tokens_out: number;
  cost_usd: number;
  latency_ms: number;
  status: string;
  cache_hit: boolean;
}

export interface FeedbackRow {
  message_id: string;
  row_id: string;
  vote: Vote;
}

interface DbShape {
  version: string;
  age_confirmed: boolean;
  ready: boolean;
  conversations: ConvRow[];
  messages: MsgRow[];
  parts: PartRow[];
  profiles: ProfileRow[];
  turns: TurnLogRow[];
  feedback: FeedbackRow[];
  seq: Record<string, number>;
  idempotency: Record<string, { request_hash: string; response: unknown }>;
}

const PROFILE_AXES = [
  "style",
  "sweetness",
  "body",
  "oak",
  "tannin",
  "acidity",
  "fruit_savoury",
] as const;

function empty(): DbShape {
  return {
    version: STORAGE_KEY,
    age_confirmed: false,
    ready: true,
    conversations: [],
    messages: [],
    parts: [],
    profiles: [],
    turns: [],
    feedback: [],
    seq: {},
    idempotency: {},
  };
}

export const db: DbShape = empty();

let counter = 0;
export function newRowId(prefix: string): string {
  counter += 1;
  return `${prefix}_${Date.now().toString(36)}${counter.toString(36).padStart(3, "0")}`;
}

/* --- persistence -------------------------------------------------------- */

let saveTimer: number | null = null;

export function save(): void {
  if (typeof localStorage === "undefined") return;
  if (saveTimer !== null) window.clearTimeout(saveTimer);
  saveTimer = window.setTimeout(() => {
    try {
      localStorage.setItem(STORAGE_KEY, JSON.stringify(db));
    } catch {
      // A full or blocked store is not a reason to break the demo.
    }
  }, 120);
}

export function restore(): boolean {
  if (typeof localStorage === "undefined") return false;
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (!raw) return false;
    const parsed = JSON.parse(raw) as DbShape;
    if (parsed.version !== STORAGE_KEY) return false;
    Object.assign(db, parsed);
    return true;
  } catch {
    return false;
  }
}

export function reset(): void {
  Object.assign(db, empty());
  if (typeof localStorage !== "undefined") localStorage.removeItem(STORAGE_KEY);
}

/* --- seq: the one allocator, per conversation --------------------------- */

export function nextSeq(cid: string): number {
  const next = (db.seq[cid] ?? 0) + 1;
  db.seq[cid] = next;
  return next;
}

/* --- conversations ------------------------------------------------------ */

export function createConversation(title: string, at?: Date, datasetVersion?: string): ConvRow {
  const now = (at ?? new Date()).toISOString();
  const row: ConvRow = {
    id: newRowId("c"),
    title,
    created_at: now,
    updated_at: now,
    archived_at: null,
    deleted_at: null,
    // Pinned at creation so a transcript records which artifact it was served from.
    dataset_version: datasetVersion ?? DATASET_VERSION,
  };
  db.conversations.push(row);
  db.profiles.push({
    conversation_id: row.id,
    style: null,
    sweetness: null,
    body: null,
    oak: null,
    tannin: null,
    acidity: null,
    fruit_savoury: null,
    confidence_json: {},
  });
  save();
  return row;
}

export function getConversation(cid: string): ConvRow | null {
  return db.conversations.find((c) => c.id === cid && c.deleted_at === null) ?? null;
}

function sortKey(row: ConvRow): string {
  return `${row.updated_at}|${row.id}`;
}

export function listPage(options: {
  limit: number;
  cursor?: string | null;
  archived?: boolean;
  q?: string | null;
}): { items: ConvRow[]; next_cursor: string | null } {
  const { limit, cursor, archived = false, q } = options;
  let rows = db.conversations.filter(
    (c) => c.deleted_at === null && (c.archived_at !== null) === archived,
  );
  if (q?.trim()) {
    // Title substring only. Message bodies need an FTS5 table that does not exist.
    const needle = q.trim().toLowerCase();
    rows = rows.filter((c) => c.title.toLowerCase().includes(needle));
  }
  rows.sort((a, b) => sortKey(b).localeCompare(sortKey(a)));
  if (cursor) rows = rows.filter((c) => sortKey(c).localeCompare(cursor) < 0);
  const page = rows.slice(0, limit);
  const next = rows.length > limit && page.length ? sortKey(page[page.length - 1]) : null;
  return { items: page, next_cursor: next };
}

export function touchConversation(cid: string): void {
  const row = getConversation(cid);
  if (row) {
    row.updated_at = new Date().toISOString();
    save();
  }
}

export function patchConversation(
  cid: string,
  patch: { title?: string | null; archived?: boolean | null },
): ConvRow | null {
  const row = getConversation(cid);
  if (!row) return null;
  if (patch.title != null) row.title = patch.title;
  if (patch.archived != null) {
    row.archived_at = patch.archived ? new Date().toISOString() : null;
  }
  row.updated_at = new Date().toISOString();
  save();
  return row;
}

export function softDelete(cid: string): boolean {
  const row = getConversation(cid);
  if (!row) return false;
  row.deleted_at = new Date().toISOString();
  save();
  return true;
}

/* --- messages and parts ------------------------------------------------- */

export function addMessage(args: {
  cid: string;
  role: Role;
  seq: number;
  turn_id: string | null;
  created_at?: string;
}): MsgRow {
  const row: MsgRow = {
    id: newRowId("m"),
    conversation_id: args.cid,
    role: args.role,
    seq: args.seq,
    turn_id: args.turn_id,
    created_at: args.created_at ?? new Date().toISOString(),
  };
  db.messages.push(row);
  save();
  return row;
}

export function addPart(args: {
  message_id: string;
  cid: string;
  kind: PartKind;
  seq: number;
  text?: string | null;
  card_json?: Card | null;
  chips_json?: Chips | null;
  citation_json?: { row_ids: string[]; dataset_version: string } | null;
  row_id?: string | null;
}): PartRow {
  const row: PartRow = {
    id: newRowId("p"),
    message_id: args.message_id,
    conversation_id: args.cid,
    kind: args.kind,
    seq: args.seq,
    text: args.text ?? null,
    card_json: args.card_json ?? null,
    chips_json: args.chips_json ?? null,
    citation_json: args.citation_json ?? null,
    row_id: args.row_id ?? null,
  };
  db.parts.push(row);
  save();
  return row;
}

export function transcript(cid: string): (MsgRow & { parts: PartRow[] })[] {
  return db.messages
    .filter((m) => m.conversation_id === cid)
    .sort((a, b) => a.seq - b.seq)
    .map((m) => ({
      ...m,
      parts: db.parts.filter((p) => p.message_id === m.id).sort((a, b) => a.seq - b.seq),
    }));
}

export function partsAfter(cid: string, after: number): PartRow[] {
  return db.parts
    .filter((p) => p.conversation_id === cid && p.seq > after)
    .sort((a, b) => a.seq - b.seq);
}

export function messageRowIds(messageId: string): string[] {
  return db.parts
    .filter((p) => p.message_id === messageId && p.row_id)
    .map((p) => p.row_id as string);
}

export function getMessage(messageId: string): MsgRow | null {
  return db.messages.find((m) => m.id === messageId) ?? null;
}

/** The row ids the most recent assistant message cited — what refine anchors to. */
export function lastCitedRowIds(cid: string): string[] {
  const messages = db.messages
    .filter((m) => m.conversation_id === cid && m.role === "assistant")
    .sort((a, b) => b.seq - a.seq);
  for (const message of messages) {
    const ids = messageRowIds(message.id);
    if (ids.length) return ids;
  }
  return [];
}

/* --- taste profile ------------------------------------------------------ */

export function getProfile(cid: string): ProfileRow {
  let row = db.profiles.find((p) => p.conversation_id === cid);
  if (!row) {
    row = {
      conversation_id: cid,
      style: null,
      sweetness: null,
      body: null,
      oak: null,
      tannin: null,
      acidity: null,
      fruit_savoury: null,
      confidence_json: {},
    };
    db.profiles.push(row);
  }
  return row;
}

export function mergeProfile(
  cid: string,
  values: Record<string, string>,
  confidence: Record<string, { confidence?: number; provenance?: string }>,
): void {
  const row = getProfile(cid);
  for (const [axis, value] of Object.entries(values)) {
    if ((PROFILE_AXES as readonly string[]).includes(axis)) {
      (row as unknown as Record<string, string | null>)[axis] = value;
    }
  }
  row.confidence_json = { ...row.confidence_json, ...confidence };
  save();
}

export function profileValues(cid: string): Record<string, string | null> {
  const row = getProfile(cid);
  return Object.fromEntries(PROFILE_AXES.map((axis) => [axis, row[axis]]));
}

export function tasteProfile(cid: string): TasteProfile {
  const row = getProfile(cid);
  return {
    style: row.style,
    sweetness: row.sweetness,
    body: row.body,
    oak: row.oak,
    tannin: row.tannin,
    acidity: row.acidity,
    fruit_savoury: row.fruit_savoury,
    confidence: row.confidence_json,
  };
}

/* --- logs --------------------------------------------------------------- */

export function writeTurn(row: TurnLogRow): void {
  db.turns.push(row);
  save();
}

export function sessionUsage() {
  const turns = db.turns;
  return {
    turns: turns.length,
    tokens_in: turns.reduce((sum, t) => sum + t.tokens_in, 0),
    tokens_out: turns.reduce((sum, t) => sum + t.tokens_out, 0),
    cost_usd: turns.reduce((sum, t) => sum + t.cost_usd, 0),
    cache_hits: turns.filter((t) => t.cache_hit).length,
  };
}

export function upsertFeedback(row: FeedbackRow): void {
  const existing = db.feedback.find(
    (f) => f.message_id === row.message_id && f.row_id === row.row_id,
  );
  if (existing) existing.vote = row.vote;
  else db.feedback.push(row);
  save();
}

/* --- idempotency -------------------------------------------------------- */

export function idempotencyGet(key: string) {
  return db.idempotency[key] ?? null;
}

export function idempotencyPut(key: string, request_hash: string, response: unknown): void {
  db.idempotency[key] = { request_hash, response };
  save();
}

export function hashRequest(value: unknown): string {
  const text = JSON.stringify(value);
  let hash = 0;
  for (let i = 0; i < text.length; i += 1) {
    hash = (hash << 5) - hash + text.charCodeAt(i);
    hash |= 0;
  }
  return hash.toString(16);
}
