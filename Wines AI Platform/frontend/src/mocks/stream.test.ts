/** Integration over the real transport: engine -> runner -> SSE frames -> reducer.
 *
 * This is the test that matters most, because every subtlety the client has to handle
 * lives in the seam between those four things: the anchor seq, the coalesced replay,
 * the resume cursor, and the idle `done`. The reducer unit tests use hand-made frames;
 * these use frames the mock actually produced.
 */

import { afterEach, beforeEach, describe, expect, it } from "vitest";
import * as db from "./db";
import { buildStream, cancelTurn, startTurn } from "./stream";
import {
  initialLive,
  liveReducer,
  resumeAfter,
  sortedBlocks,
  type LiveState,
} from "@/lib/reducer";
import type { Frame, FrameName } from "@/types/sse";

interface Parsed {
  id: number | null;
  name: FrameName;
  data: Record<string, unknown>;
}

/** Read an SSE body the way EventSource would, stopping at a predicate. */
async function read(
  stream: ReadableStream<Uint8Array>,
  until: (frames: Parsed[]) => boolean,
  limit = 400,
): Promise<Parsed[]> {
  const reader = stream.getReader();
  const decoder = new TextDecoder();
  const frames: Parsed[] = [];
  let buffer = "";

  while (frames.length < limit) {
    const { value, done } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    const chunks = buffer.split("\n\n");
    buffer = chunks.pop() ?? "";
    for (const chunk of chunks) {
      if (!chunk.trim() || chunk.startsWith(":")) continue;
      const id = /^id: (\d+)$/m.exec(chunk);
      const name = /^event: (\w+)$/m.exec(chunk);
      const data = /^data: (.*)$/m.exec(chunk);
      if (!name || !data) continue;
      frames.push({
        id: id ? Number(id[1]) : null,
        name: name[1] as FrameName,
        data: JSON.parse(data[1]) as Record<string, unknown>,
      });
    }
    if (until(frames)) break;
  }
  void reader.cancel();
  return frames;
}

const apply = (state: LiveState, frames: Parsed[]): LiveState =>
  frames.reduce(
    (acc, frame) => liveReducer(acc, { type: "frame", frame: frame as unknown as Frame }),
    state,
  );

const hasDone = (frames: Parsed[]) => frames.some((f) => f.name === "done");

function conversation(): string {
  const row = db.createConversation("New conversation");
  return row.id;
}

/** What `api/v1/turns.py:send` does before the runner starts, condensed. */
function send(cid: string, content: string, chipId?: string | null): string {
  const turnId = db.newRowId("t");
  const seq = db.nextSeq(cid);
  const message = db.addMessage({ cid, role: "user", seq, turn_id: turnId });
  db.addPart({
    message_id: message.id,
    cid,
    kind: "text",
    seq: db.nextSeq(cid),
    text: content,
  });
  startTurn({ cid, turnId, utterance: content, chipId: chipId ?? null });
  return turnId;
}

beforeEach(() => db.reset());
afterEach(() => db.reset());

describe("the mock transport", () => {
  it("streams an interview question word by word, then its chips", async () => {
    const cid = conversation();
    const stream = buildStream(cid, db.db.seq[cid] ?? 0);
    send(cid, "I want a red");

    const frames = await read(stream, hasDone);
    const tokens = frames.filter((f) => f.name === "token");

    expect(tokens.length).toBeGreaterThan(1);
    // Every token of one run carries the same anchor — the key the reducer merges on.
    const anchors = new Set(tokens.map((f) => f.data.anchor_seq));
    expect(anchors.size).toBe(1);
    expect(frames.some((f) => f.name === "chips")).toBe(true);
    expect(frames.at(-1)?.name).toBe("done");
    expect(frames.at(-1)?.data.status).toBe("ok");

    const state = apply(initialLive(0), frames);
    const blocks = sortedBlocks(state);
    // "I want a red" already answered question one, so the next one is sweetness —
    // re-asking what the user just said is the fastest way to look stupid.
    expect(blocks[0]).toMatchObject({ kind: "text", text: "How sweet?" });
    expect(blocks[1].kind).toBe("chips");
  });

  it("coalesces the run into one persisted part, so a replay is one frame", async () => {
    const cid = conversation();
    const stream = buildStream(cid, 0);
    send(cid, "a bold red, nothing too sweet");
    await read(stream, hasDone);

    const textParts = db.db.parts.filter((p) => p.conversation_id === cid && p.kind === "text");
    // The user's message plus one part per assistant text RUN — not one per token.
    expect(textParts.length).toBeLessThan(5);
    expect(db.db.parts.filter((p) => p.kind === "card").length).toBeGreaterThanOrEqual(3);
  });

  it("replays a finished conversation and says it is idle, so no spinner hangs", async () => {
    const cid = conversation();
    const first = buildStream(cid, 0);
    send(cid, "a bold red, nothing too sweet");
    await read(first, hasDone);

    // A fresh reader with after=0, exactly as a client with no transcript would.
    const replay = await read(buildStream(cid, 0), (frames) =>
      frames.some((f) => f.name === "done"),
    );
    const done = replay.find((f) => f.name === "done");
    expect(done?.data.status).toBe("idle");
    expect(done?.id).toBeNull(); // must not move the resume cursor
    expect(replay.filter((f) => f.name === "card").length).toBeGreaterThanOrEqual(3);
  });

  it("resumes mid-run at anchor - 1 and rebuilds the sentence exactly once", async () => {
    const cid = conversation();
    const highWater = db.db.seq[cid] ?? 0;
    const live = buildStream(cid, highWater);
    send(cid, "a crisp white, nothing sweet");

    // Drop after a few tokens, mid-sentence.
    const partial = await read(
      live,
      (frames) => frames.filter((f) => f.name === "token").length >= 4,
    );
    let state = apply(initialLive(highWater), partial);
    expect(state.runAnchor).not.toBeNull();

    const after = resumeAfter(state);
    state = liveReducer(state, { type: "prepare-resume" });
    const resumed = await read(buildStream(cid, after), hasDone);
    state = apply(state, resumed);

    const texts = sortedBlocks(state).filter(
      (block): block is Extract<typeof block, { kind: "text" }> => block.kind === "text",
    );
    // The lead-in survived the drop whole, with nothing doubled.
    const joined = texts.map((t) => t.text).join(" ");
    expect(joined).toContain("Here are");
    expect(joined).not.toMatch(/Here are.*Here are/);
    expect(sortedBlocks(state).filter((b) => b.kind === "card").length).toBeGreaterThanOrEqual(
      3,
    );
  });

  it("stops a turn on cancel and keeps what had already arrived", async () => {
    const cid = conversation();
    const stream = buildStream(cid, db.db.seq[cid] ?? 0);
    const turnId = send(cid, "a bold red, nothing too sweet");

    const frames = await read(stream, (list) => {
      if (list.filter((f) => f.name === "token").length >= 3) cancelTurn(turnId);
      return hasDone(list);
    });

    expect(frames.at(-1)?.data.status).toBe("cancelled");
    const state = apply(initialLive(0), frames);
    expect(state.phase).toBe("cancelled");
    expect(sortedBlocks(state).some((b) => b.kind === "text")).toBe(true);
  });

  it("refuses a second turn while one is in flight", async () => {
    const cid = conversation();
    const stream = buildStream(cid, 0);
    send(cid, "a bold red, nothing too sweet");
    // The handler returns 409 off exactly this check.
    const { activeForConversation } = await import("./stream");
    expect(activeForConversation(cid)).not.toBeNull();
    await read(stream, hasDone);
    expect(activeForConversation(cid)).toBeNull();
  });

  it("writes one transaction row per turn, at zero cost", async () => {
    const cid = conversation();
    const stream = buildStream(cid, 0);
    send(cid, "I want a red");
    await read(stream, hasDone);
    expect(db.db.turns).toHaveLength(1);
    expect(db.db.turns[0]).toMatchObject({ cost_usd: 0, status: "ok", intent: "interview" });
  });
});
