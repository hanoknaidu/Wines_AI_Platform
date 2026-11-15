/** Merge the committed transcript with the live stream into one ordered thread.
 *
 * Both sources speak the same seq space, so the merge is a map keyed by seq: the
 * transcript wins wherever they overlap, because its parts carry the message id that
 * feedback needs. There is no flicker when a streamed turn is replaced by its
 * persisted form, and no risk of rendering a block twice.
 */

import type { Block } from "./reducer";
import type { ConversationDetail, MessagePart, Role } from "@/types/api";

export interface Turn {
  key: string;
  role: Role;
  /** Null while a turn is still only on the stream. Feedback needs it, so thumbs stay
   *  disabled until the transcript refetch lands — a window of a few milliseconds. */
  messageId: string | null;
  turnId: string | null;
  blocks: Block[];
}

export interface PendingTurn {
  content: string;
  /** The send response's `seq`. The user text part is always seq + 1, because the
   *  message and its part are allocated back to back and only one turn can be in
   *  flight per conversation. Knowing it exactly is what lets the optimistic bubble
   *  be replaced rather than duplicated. */
  seq: number | null;
}

interface Item {
  role: Role;
  block: Block;
  messageId: string | null;
  turnId: string | null;
}

export function partToBlock(part: MessagePart): Block | null {
  switch (part.kind) {
    case "text":
      return { kind: "text", seq: part.seq, text: part.text ?? "" };
    case "card":
      return part.card ? { kind: "card", seq: part.seq, card: part.card } : null;
    case "chips":
      return part.chips ? { kind: "chips", seq: part.seq, chips: part.chips } : null;
    case "citation":
      return part.citation
        ? {
            kind: "citation",
            seq: part.seq,
            rowIds: part.citation.row_ids,
            datasetVersion: part.citation.dataset_version,
          }
        : null;
    case "error":
      return {
        kind: "error",
        seq: part.seq,
        code: null,
        title: null,
        detail: part.text ?? "",
      };
    default:
      return null;
  }
}

/** The high-water mark the stream should be opened at. Opening at 0 instead would make
 *  the server replay the whole transcript — including the USER's text parts, which
 *  arrive as `token` frames carrying no role and would be rendered in the assistant's
 *  voice. */
export function transcriptHighWater(detail: ConversationDetail | undefined): number {
  if (!detail) return 0;
  let max = 0;
  for (const message of detail.messages) {
    max = Math.max(max, message.seq);
    for (const part of message.parts) max = Math.max(max, part.seq);
  }
  return max;
}

export function buildThread(
  detail: ConversationDetail | undefined,
  liveBlocks: Block[],
  liveTurnId: string | null,
  pending: PendingTurn | null,
): Turn[] {
  const items = new Map<number, Item>();

  for (const block of liveBlocks) {
    items.set(block.seq, {
      role: "assistant",
      block,
      messageId: null,
      turnId: liveTurnId,
    });
  }

  if (detail) {
    for (const message of detail.messages) {
      for (const part of message.parts) {
        const block = partToBlock(part);
        if (!block) continue;
        items.set(part.seq, {
          role: message.role,
          block,
          messageId: message.id,
          turnId: message.turn_id ?? null,
        });
      }
    }
  }

  if (pending) {
    const key = pending.seq !== null ? pending.seq + 1 : Number.MAX_SAFE_INTEGER;
    if (!items.has(key)) {
      items.set(key, {
        role: "user",
        block: { kind: "text", seq: key, text: pending.content },
        messageId: null,
        turnId: null,
      });
    }
  }

  const turns: Turn[] = [];
  for (const seq of [...items.keys()].sort((a, b) => a - b)) {
    const item = items.get(seq) as Item;
    const last = turns[turns.length - 1];
    if (last && last.role === item.role) {
      last.blocks.push(item.block);
      last.messageId = last.messageId ?? item.messageId;
      last.turnId = last.turnId ?? item.turnId;
      continue;
    }
    turns.push({
      key: `${item.role}-${seq}`,
      role: item.role,
      messageId: item.messageId,
      turnId: item.turnId,
      blocks: [item.block],
    });
  }
  return turns;
}

/** Only the newest chip row is live. Clicking a chip three turns up would refine the
 *  CURRENT profile while pointing at an old result set, which is ambiguous — so older
 *  rows render as a record of what was chosen (plan §11 Q3). */
export function lastChipsSeq(turns: Turn[]): number | null {
  let seq: number | null = null;
  for (const turn of turns) {
    for (const block of turn.blocks) {
      if (block.kind === "chips") seq = block.seq;
    }
  }
  return seq;
}
