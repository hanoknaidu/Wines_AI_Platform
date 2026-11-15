import { Loader2 } from "lucide-react";
import { useAutoScroll } from "@/hooks/useAutoScroll";
import type { Turn } from "@/lib/thread";
import type { UsageFrame } from "@/types/sse";
import { AssistantTurn } from "./AssistantTurn";
import { ScrollToBottom } from "./ScrollToBottom";
import { UserTurn } from "./UserTurn";

export function Thread({
  turns,
  streaming,
  cancelled,
  reconnecting,
  usage,
  turnId,
  liveChipsSeq,
  chosenChipId,
  pendingSeq,
}: {
  turns: Turn[];
  streaming: boolean;
  cancelled: boolean;
  reconnecting: boolean;
  usage: UsageFrame | null;
  turnId: string | null;
  liveChipsSeq: number | null;
  chosenChipId: string | null;
  pendingSeq: number | null;
}) {
  const fingerprint = turns.map((turn) => `${turn.key}:${turn.blocks.length}`).join("|");
  const lastBlockText = turns.at(-1)?.blocks.at(-1);
  const { ref, pinned, onScroll, scrollToBottom } = useAutoScroll(
    `${fingerprint}:${lastBlockText?.kind === "text" ? lastBlockText.text.length : 0}`,
  );

  const lastTurnKey = turns.at(-1)?.key;

  return (
    <div className="relative flex h-full min-h-0 flex-col">
      <div
        ref={ref}
        onScroll={onScroll}
        className="min-h-0 flex-1 overflow-y-auto overscroll-contain"
      >
        <div className="mx-auto max-w-measure space-y-6 px-4 py-6">
          {turns.map((turn) => {
            const isLast = turn.key === lastTurnKey;
            return (
              <div key={turn.key}>
                {turn.role === "user" ? (
                  <UserTurn
                    blocks={turn.blocks}
                    pending={pendingSeq !== null && turn.messageId === null}
                  />
                ) : (
                  <AssistantTurn
                    blocks={turn.blocks}
                    messageId={turn.messageId}
                    settled={!(streaming && isLast)}
                    streaming={streaming && isLast}
                    usage={turn.turnId === turnId || turn.messageId === null ? usage : null}
                    liveChipsSeq={liveChipsSeq}
                    chosenChipId={chosenChipId}
                  />
                )}
              </div>
            );
          })}

          {cancelled && !streaming ? (
            /* Partial text stays on screen — the user watched it arrive, and
               removing it would look like the app had rewritten history. But it has
               to be labelled, or a half-finished answer reads as the whole answer. */
            <p className="text-micro text-subtle">You stopped this answer.</p>
          ) : null}

          {reconnecting ? (
            <p className="flex items-center gap-2 text-micro text-subtle">
              <Loader2 size={12} className="animate-spin" />
              Reconnecting — the answer will pick up exactly where it stopped.
            </p>
          ) : null}
        </div>
      </div>

      {!pinned ? <ScrollToBottom onClick={scrollToBottom} /> : null}

      {/* A politeness budget: the whole run is announced once it settles, rather than
          once per token. Announcing each token turns a screen reader into a machine gun. */}
      <div aria-live="polite" aria-atomic="true" className="sr-only">
        {streaming
          ? "Writing an answer."
          : cancelled
            ? "You stopped the answer."
            : liveAnnouncement(turns)}
      </div>
    </div>
  );
}

/** Terse on purpose. The answer itself is in the document, so repeating its prose in
 *  a live region makes a screen reader read the whole thing twice — once as an
 *  announcement and again when the user reaches it. This says that something arrived
 *  and what shape it is; the content stays where content belongs. */
function liveAnnouncement(turns: Turn[]): string {
  const last = turns.at(-1);
  if (!last || last.role !== "assistant") return "";

  const cards = last.blocks.filter((block) => block.kind === "card").length;
  if (cards) return `Answer ready, with ${cards} recommendations.`;

  const chips = last.blocks.find(
    (block): block is Extract<typeof block, { kind: "chips" }> => block.kind === "chips",
  );
  if (chips?.chips.kind === "refine") {
    return "No match for that. Adjustments are available below the answer.";
  }
  if (chips) return `A question, with ${chips.chips.options.length} options.`;
  if (last.blocks.some((block) => block.kind === "error")) return "That answer failed.";
  return "Answer ready.";
}
