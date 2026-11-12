import { describe, expect, it } from "vitest";
import { initialLive, liveReducer, resumeAfter, sortedBlocks, type LiveState } from "./reducer";
import type { Frame } from "@/types/sse";

const token = (id: number, text: string, anchor: number): Frame => ({
  name: "token",
  id,
  data: { turn_id: "t_1", text, anchor_seq: anchor },
});

function feed(state: LiveState, ...frames: Frame[]): LiveState {
  return frames.reduce((acc, frame) => liveReducer(acc, { type: "frame", frame }), state);
}

describe("live reducer", () => {
  it("accumulates a text run into ONE block keyed by its anchor", () => {
    const state = feed(
      initialLive(0),
      token(4, "Here ", 4),
      token(5, "are ", 4),
      token(6, "3.", 4),
    );
    const blocks = sortedBlocks(state);
    expect(blocks).toHaveLength(1);
    expect(blocks[0]).toMatchObject({ kind: "text", seq: 4, text: "Here are 3." });
    expect(state.lastSeq).toBe(6);
    expect(state.runAnchor).toBe(4);
  });

  it("drops a frame it has already applied, so reconnecting is safe at any moment", () => {
    let state = feed(initialLive(0), token(4, "Here ", 4), token(5, "are ", 4));
    state = feed(state, token(4, "Here ", 4), token(5, "are ", 4));
    expect(sortedBlocks(state)[0]).toMatchObject({ text: "Here are " });
  });

  it("resumes mid-run at anchor - 1 and discards what it holds from the anchor on", () => {
    let state = feed(initialLive(0), token(7, "half a ", 7), token(8, "senten", 7));
    expect(resumeAfter(state)).toBe(6);

    state = liveReducer(state, { type: "prepare-resume" });
    // Everything from the anchor is gone, so the coalesced replay is not mistaken for
    // a duplicate — which is what would otherwise leave truncated text on screen.
    expect(sortedBlocks(state)).toHaveLength(0);
    expect(state.appliedUpTo).toBe(6);

    state = feed(state, {
      name: "token",
      id: 7,
      data: { text: "half a sentence, now whole." },
    });
    expect(sortedBlocks(state)[0]).toMatchObject({
      seq: 7,
      text: "half a sentence, now whole.",
    });
  });

  it("resumes at lastSeq when no run is in progress", () => {
    const state = feed(initialLive(0), token(3, "done.", 3), {
      name: "citation",
      id: 4,
      data: { row_ids: ["w-0001"], dataset_version: "seed-0.1" },
    });
    expect(state.runAnchor).toBeNull();
    expect(resumeAfter(state)).toBe(4);
  });

  it("closes the current run on any non-token frame", () => {
    const state = feed(
      initialLive(0),
      token(2, "Lead in. ", 2),
      {
        name: "card",
        id: 3,
        data: {
          row_id: "w-0003",
          variety: "Pinot Noir",
          style: "red",
          axes: {},
          description: "",
          why_it_matches: "",
          typical_regions: [],
          example_producers: [],
          review_status: "unreviewed",
          dataset_version: "seed-0.1",
        },
      },
      token(4, "After the card.", 4),
    );
    const blocks = sortedBlocks(state);
    expect(blocks.map((b) => b.kind)).toEqual(["text", "card", "text"]);
  });

  it("treats the idle done as caught-up without moving the resume cursor", () => {
    let state = feed(initialLive(0), token(9, "replayed.", 9));
    state = liveReducer(state, {
      type: "frame",
      // No id, deliberately: an informational frame must not move Last-Event-ID.
      frame: { name: "done", id: null, data: { turn_id: null, status: "idle", replay: true } },
    });
    expect(state.caughtUp).toBe(true);
    expect(state.phase).toBe("idle");
    expect(state.lastSeq).toBe(9);
  });

  it("keeps partial text when a turn ends in an error", () => {
    let state = feed(initialLive(0), token(2, "I was saying ", 2));
    state = feed(state, {
      name: "error",
      id: 3,
      data: { code: "engine_error", title: "Failed", detail: "Try again." },
    });
    expect(sortedBlocks(state).map((b) => b.kind)).toEqual(["text", "error"]);
    expect(state.phase).toBe("error");
  });

  it("records a cancelled turn as cancelled, not as a failure", () => {
    const state = feed(initialLive(0), token(2, "stopped mid", 2), {
      name: "done",
      id: 3,
      data: { turn_id: "t_1", status: "cancelled", row_ids: [] },
    });
    expect(state.phase).toBe("cancelled");
    expect(state.caughtUp).toBe(true);
  });
  // --- the late turn-started race ---------------------------------------
  //
  // Against mocks every frame lands in one tick AFTER the send resolves, so this
  // ordering never occurred. Against a real server a fast interview turn finishes
  // before the POST's own response is unwrapped, and the order inverts.

  const doneFrame = (id: number | null, status: "ok" | "idle", turn: string | null): Frame => ({
    name: "done",
    id,
    data: { turn_id: turn, status },
  });

  it("does not re-arm a turn whose terminal done it has already applied", () => {
    // Exactly what one 984-byte chunk from a real interview turn delivers.
    let state = feed(
      initialLive(0),
      doneFrame(null, "idle", null),
      token(4, "Here ", 4),
      token(5, "are 3.", 4),
      { name: "chips", id: 6, data: { kind: "interview", options: [], turn_id: "t_1" } },
      { name: "usage", id: 7, data: { turn_id: "t_1" } } as Frame,
      doneFrame(8, "ok", "t_1"),
    );
    expect(state.phase).toBe("done");
    expect(state.turnId).toBe("t_1");

    // The send's HTTP response is only now unwrapped.
    state = liveReducer(state, { type: "turn-started", turnId: "t_1" });

    // Before the fix this flipped to "streaming" with no frame left to end it, which
    // disabled the composer and the chip dock for good.
    expect(state.phase).toBe("done");
    expect(state.caughtUp).toBe(true);
  });

  it("still arms a genuinely new turn when the previous one has finished", () => {
    let state = feed(initialLive(0), token(4, "first turn", 4), doneFrame(5, "ok", "t_1"));
    expect(state.phase).toBe("done");

    state = liveReducer(state, { type: "turn-started", turnId: "t_2" });
    expect(state.phase).toBe("streaming");
    expect(state.turnId).toBe("t_2");
    expect(state.caughtUp).toBe(false);
  });

  it("arms a turn that has not streamed yet, which is the common ordering", () => {
    const state = liveReducer(initialLive(0), { type: "turn-started", turnId: "t_1" });
    expect(state.phase).toBe("streaming");
  });
});
