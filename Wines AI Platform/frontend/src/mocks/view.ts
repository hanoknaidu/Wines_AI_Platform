/** Row -> wire shape. Shared by the handlers and by tests that need a real
 *  conversation to render, so a test can never diverge from what the app receives. */

import * as db from "./db";
import { DATASET_VERSION } from "./engine";
import type {
  ConversationDetail,
  ConversationSummary,
  Message,
  MessagePart,
} from "@/types/api";

export function summary(row: db.ConvRow): ConversationSummary {
  return {
    id: row.id,
    title: row.title,
    created_at: row.created_at,
    updated_at: row.updated_at,
    archived: row.archived_at !== null,
    dataset_version: row.dataset_version,
  };
}

export function detail(row: db.ConvRow): ConversationDetail {
  const messages: Message[] = db.transcript(row.id).map((message) => ({
    id: message.id,
    role: message.role,
    seq: message.seq,
    turn_id: message.turn_id,
    created_at: message.created_at,
    parts: message.parts.map((part): MessagePart => ({
      id: part.id,
      kind: part.kind,
      seq: part.seq,
      text: part.text,
      card: part.card_json,
      chips: part.chips_json,
      citation: part.citation_json,
      row_id: part.row_id,
    })),
  }));

  return {
    ...summary(row),
    // Reported rather than silently re-served under a different artifact.
    dataset_version_stale: row.dataset_version !== DATASET_VERSION,
    served_dataset_version: DATASET_VERSION,
    taste_profile: db.tasteProfile(row.id),
    messages,
  };
}
