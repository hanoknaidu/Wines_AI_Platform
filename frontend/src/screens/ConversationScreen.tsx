import { useEffect, useMemo, useRef, useState } from "react";
import { useLocation, useNavigate, useParams } from "react-router-dom";
import { ChipDock } from "@/components/chips/ChipDock";
import { Composer, type ComposerHandle } from "@/components/composer/Composer";
import { CardSkeleton } from "@/components/cards/CardSkeleton";
import { NotFound } from "@/components/states/NotFound";
import { Thread } from "@/components/thread/Thread";
import { StaleVersionNotice } from "@/components/trust/StaleVersionNotice";
import { SkeletonText } from "@/components/ui/Skeleton";
import { useToasts } from "@/components/ui/Toast";
import { useConversation } from "@/hooks/useConversations";
import { useConversationStream } from "@/hooks/useConversationStream";
import { useKeyboardShortcuts } from "@/hooks/useKeyboardShortcuts";
import { useSendTurn } from "@/hooks/useSendTurn";
import { cancelTurn, newId } from "@/lib/api";
import { ApiProblem, isProblem } from "@/lib/problem";
import { buildThread, lastChipsSeq, transcriptHighWater, type PendingTurn } from "@/lib/thread";
import { useComposerStore } from "@/stores/useComposerStore";
import type { Chips, ChipOption } from "@/types/api";

export function ConversationScreen() {
  const { cid = "" } = useParams();
  const navigate = useNavigate();
  const location = useLocation();
  const push = useToasts((state) => state.push);
  const composerRef = useRef<ComposerHandle | null>(null);

  const { data: detail, isLoading, error } = useConversation(cid);
  const highWater = detail ? transcriptHighWater(detail) : null;
  const stream = useConversationStream(detail ? cid : null, highWater);
  const send = useSendTurn();

  const [pending, setPending] = useState<PendingTurn | null>(null);
  const [chosenChipId, setChosenChipId] = useState<string | null>(null);
  const idempotencyKey = useRef<string | null>(null);

  const draft = useComposerStore((state) => state.drafts[cid] ?? "");
  const setDraft = useComposerStore((state) => state.setDraft);
  const clearDraft = useComposerStore((state) => state.clearDraft);

  const turns = useMemo(
    () => buildThread(detail, stream.blocks, stream.turnId, pending),
    [detail, stream.blocks, stream.turnId, pending],
  );

  const liveChips = useMemo<{ seq: number; chips: Chips } | null>(() => {
    const seq = lastChipsSeq(turns);
    if (seq === null) return null;
    for (const turn of turns) {
      for (const block of turn.blocks) {
        if (block.kind === "chips" && block.seq === seq) return { seq, chips: block.chips };
      }
    }
    return null;
  }, [turns]);

  /** The optimistic bubble is dropped the moment the transcript carries the real part
   *  at the seq the send response named — so it is replaced, never duplicated, and
   *  never disappears for a frame in between. */
  useEffect(() => {
    if (!pending || pending.seq === null || !detail) return;
    const seq = pending.seq + 1;
    const landed = detail.messages.some((message) =>
      message.parts.some((part) => part.seq === seq),
    );
    if (landed) setPending(null);
  }, [detail, pending]);

  const submit = (content: string, chipId?: string | null) => {
    const text = content.trim();
    if (!text || stream.isStreaming) return;

    // Minted once per send and held, so a retry of THIS send reuses it. A fresh key on
    // retry would start a second turn and pay for it twice.
    idempotencyKey.current = newId();
    setPending({ content: text, seq: null });
    setChosenChipId(chipId ?? null);
    clearDraft(cid);

    send.mutate(
      { cid, content: text, chipId: chipId ?? null, idempotencyKey: idempotencyKey.current },
      {
        onSuccess: (response) => {
          stream.noteSend(response.turn_id, response.seq);
          setPending({ content: text, seq: response.seq });
        },
        onError: (failure) => {
          setPending(null);
          if (isProblem(failure, "age_not_confirmed")) {
            navigate("/age", { state: { from: `/c/${cid}` } });
            return;
          }
          const problem = failure instanceof ApiProblem ? failure : null;
          push({
            tone: "danger",
            title: problem?.title ?? "That message did not send",
            detail:
              problem?.code === "rate_limited" && problem.retryAfter
                ? `${problem.detail} (about ${problem.retryAfter}s)`
                : (problem?.detail ?? "The server could not be reached."),
            requestId: problem?.requestId,
          });
          // Nothing was sent, so the text goes back where the user left it.
          setDraft(cid, text);
        },
      },
    );
  };

  const stop = () => {
    if (stream.turnId && stream.isStreaming) void cancelTurn(stream.turnId).catch(() => {});
  };

  useKeyboardShortcuts({
    onStop: stop,
    onFocusComposer: () => composerRef.current?.focus(),
  });

  // A conversation opened from the new-conversation screen arrives with its first
  // message in tow, so the user does not have to type it twice.
  const firstSent = useRef(false);
  const firstMessage = (location.state as { firstMessage?: string } | null)?.firstMessage;
  useEffect(() => {
    if (!firstMessage || firstSent.current || !detail) return;
    firstSent.current = true;
    navigate(`/c/${cid}`, { replace: true, state: null });
    submit(firstMessage);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [firstMessage, detail]);

  if (isProblem(error, "conversation_not_found")) {
    return (
      <NotFound
        title="This conversation is gone"
        detail="It was deleted, or it belonged to a different browser session."
      />
    );
  }

  if (isLoading || !detail) {
    return (
      <div className="mx-auto max-w-measure space-y-6 px-4 py-6">
        <SkeletonText lines={2} />
        <CardSkeleton />
      </div>
    );
  }

  const onChipSelect = (option: ChipOption) => submit(option.label, option.id);

  return (
    <div className="flex h-full min-h-0 flex-col">
      {detail.dataset_version_stale ? (
        <div className="mx-auto w-full max-w-measure px-4 pt-4">
          <StaleVersionNotice
            pinned={detail.dataset_version}
            served={detail.served_dataset_version}
          />
        </div>
      ) : null}

      <Thread
        turns={turns}
        streaming={stream.isStreaming}
        cancelled={stream.phase === "cancelled"}
        reconnecting={stream.reconnecting}
        usage={stream.usage}
        turnId={stream.turnId}
        liveChipsSeq={liveChips?.seq ?? null}
        chosenChipId={chosenChipId}
        pendingSeq={pending?.seq ?? null}
      />

      <div className="shrink-0 border-t border-line bg-canvas">
        {liveChips ? (
          <div className="mx-auto max-w-measure px-4 pt-3">
            <ChipDock
              chips={liveChips.chips}
              onSelect={onChipSelect}
              disabled={stream.isStreaming || send.isPending}
              pendingId={send.isPending ? chosenChipId : null}
            />
          </div>
        ) : null}

        <Composer
          ref={composerRef}
          value={draft}
          onChange={(value) => setDraft(cid, value)}
          onSend={() => submit(draft)}
          onStop={stop}
          streaming={stream.isStreaming}
          disabledReason={
            detail.archived
              ? "This conversation is archived — sending will unarchive it."
              : null
          }
        />
      </div>
    </div>
  );
}
