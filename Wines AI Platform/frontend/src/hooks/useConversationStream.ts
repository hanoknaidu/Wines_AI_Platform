import { useQueryClient } from "@tanstack/react-query";
import { useCallback, useEffect, useMemo, useReducer, useRef, useState } from "react";
import { qk } from "@/lib/queryKeys";
import { initialLive, liveReducer, resumeAfter, sortedBlocks } from "@/lib/reducer";
import { ConversationStream } from "@/lib/sse";

/** Owns the one long-lived EventSource for a mounted conversation.
 *
 * Opened when the conversation mounts and kept open across turns, because
 * `POST .../messages` returns only `{turn_id}` and the content arrives here.
 *
 * It is opened only once the transcript has loaded, at that transcript's high-water
 * mark. Opening at 0 would make the server replay every committed part — including the
 * USER's text parts, which come back as `token` frames carrying no role at all and
 * would be rendered in the assistant's voice. The same reasoning gives us the FLOOR:
 * after a send we know the user part's seq exactly, and the resume cursor must never
 * drop below it.
 */
export function useConversationStream(cid: string | null, startAfter: number | null) {
  const [live, dispatch] = useReducer(liveReducer, initialLive(0));
  const [dropAttempt, setDropAttempt] = useState(0);
  const client = useQueryClient();

  const stateRef = useRef(live);
  stateRef.current = live;

  const floorRef = useRef(0);
  const streamRef = useRef<ConversationStream | null>(null);
  const enabled = cid !== null && startAfter !== null;

  useEffect(() => {
    if (startAfter !== null) floorRef.current = Math.max(floorRef.current, startAfter);
  }, [startAfter]);

  useEffect(() => {
    if (!enabled || cid === null) return;
    floorRef.current = Math.max(floorRef.current, startAfter ?? 0);
    const after = floorRef.current;
    dispatch({ type: "reset", after });

    const stream = new ConversationStream(cid, {
      onFrame: (frame) => dispatch({ type: "frame", frame }),
      onReconnect: () => {
        // Computed BEFORE the discard, from the state the drop happened in.
        const next = Math.max(resumeAfter(stateRef.current), floorRef.current);
        dispatch({ type: "prepare-resume" });
        return next;
      },
      onOpen: () => setDropAttempt(0),
      onDrop: (attempt) => setDropAttempt(attempt),
    });

    streamRef.current = stream;
    stream.open(after);
    return () => {
      stream.close();
      streamRef.current = null;
    };
    // Deliberately not depending on startAfter: a transcript refetch after a turn must
    // not tear down and reopen the stream.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [cid, enabled]);

  // When a turn closes, the transcript becomes authoritative: it carries the message
  // ids feedback needs, and its parts replace the live blocks seq for seq.
  const settledRef = useRef<string | null>(null);
  useEffect(() => {
    if (!cid || !live.caughtUp || live.phase === "idle" || live.turnId === null) return;
    const key = `${live.turnId}:${live.phase}`;
    if (settledRef.current === key) return;
    settledRef.current = key;
    void client.invalidateQueries({ queryKey: qk.conversation(cid) });
    void client.invalidateQueries({ queryKey: ["conversations"] });
    void client.invalidateQueries({ queryKey: qk.usage });
  }, [cid, client, live.caughtUp, live.phase, live.turnId]);

  const blocks = useMemo(() => sortedBlocks(live), [live]);

  /** Called with the send response, so the floor and the turn id are exact. */
  const noteSend = useCallback((turnId: string, userSeq: number) => {
    floorRef.current = Math.max(floorRef.current, userSeq + 1);
    dispatch({ type: "turn-started", turnId });
  }, []);

  const drop = useCallback(() => streamRef.current?.drop(), []);

  return {
    blocks,
    phase: live.phase,
    turnId: live.turnId,
    usage: live.usage,
    isStreaming: live.phase === "streaming",
    reconnecting: dropAttempt > 0,
    noteSend,
    drop,
  };
}
