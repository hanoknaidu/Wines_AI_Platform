import { RecommendationCard } from "@/components/cards/RecommendationCard";
import { ChipRecord } from "@/components/chips/ChipRecord";
import { AbstentionNotice } from "@/components/states/AbstentionNotice";
import { OutOfScopeNotice } from "@/components/states/OutOfScopeNotice";
import { SHOW_DIAGNOSTICS } from "@/lib/constants";
import type { Block } from "@/lib/reducer";
import type { UsageFrame } from "@/types/sse";
import { StreamErrorNotice } from "./StreamErrorNotice";
import { TextRun } from "./TextRun";
import { TurnDetails } from "./TurnDetails";

/** One assistant turn: prose, then cards, then the citation, then the chips.
 *
 * How the turn is framed is decided STRUCTURALLY, never by reading the text. Sniffing
 * for a phrase would put wine vocabulary in the client and would break the moment the
 * copy was reworded — and lane 3's generator will reword all of it.
 *
 *   refine chips + no cards -> "I could not match that; adjust something" (FR-13's
 *                              abstention, and a refine that cannot move an axis)
 *   text alone, settled     -> out of scope: price, stock, vintage, buying, health
 *   anything else           -> an ordinary answer
 */
export function AssistantTurn({
  blocks,
  messageId,
  settled,
  streaming,
  usage,
  liveChipsSeq,
  chosenChipId,
}: {
  blocks: Block[];
  messageId: string | null;
  settled: boolean;
  streaming: boolean;
  usage: UsageFrame | null;
  liveChipsSeq: number | null;
  chosenChipId: string | null;
}) {
  const hasCards = blocks.some((block) => block.kind === "card");
  const refineChips = blocks.some(
    (block) => block.kind === "chips" && block.chips.kind === "refine",
  );
  const hasChips = blocks.some((block) => block.kind === "chips");
  const lastTextSeq = blocks.filter((b) => b.kind === "text").at(-1)?.seq ?? null;

  const noMatch = settled && refineChips && !hasCards;
  const outOfScope = settled && !hasChips && !hasCards;

  const rendered: React.ReactNode[] = [];
  let cardRun: Block[] = [];

  const flushCards = () => {
    if (!cardRun.length) return;
    const run = cardRun;
    cardRun = [];
    rendered.push(
      <div key={`cards-${run[0].seq}`} className="space-y-3">
        {run.map((block) =>
          block.kind === "card" ? (
            <RecommendationCard
              key={block.seq}
              card={block.card}
              messageId={messageId}
              animate={!settled}
            />
          ) : null,
        )}
      </div>,
    );
  };

  for (const block of blocks) {
    if (block.kind === "card") {
      cardRun.push(block);
      continue;
    }
    flushCards();

    if (block.kind === "text") {
      const body = (
        <TextRun text={block.text} streaming={streaming && block.seq === lastTextSeq} />
      );
      rendered.push(
        <div key={block.seq}>
          {noMatch ? (
            <AbstentionNotice>{body}</AbstentionNotice>
          ) : outOfScope ? (
            <OutOfScopeNotice>{body}</OutOfScopeNotice>
          ) : (
            body
          )}
        </div>,
      );
      continue;
    }

    if (block.kind === "chips") {
      // The newest row is live in the dock above the composer; this is the record.
      if (block.seq === liveChipsSeq) continue;
      rendered.push(<ChipRecord key={block.seq} chips={block.chips} chosen={chosenChipId} />);
      continue;
    }

    if (block.kind === "citation") {
      rendered.push(
        <p key={block.seq} className="text-micro text-subtle">
          Served from {block.rowIds.length} dataset {block.rowIds.length === 1 ? "row" : "rows"}{" "}
          · <span className="tabular">{block.datasetVersion}</span>
        </p>,
      );
      continue;
    }

    if (block.kind === "error") {
      rendered.push(
        <StreamErrorNotice key={block.seq} title={block.title} detail={block.detail} />,
      );
    }
  }
  flushCards();

  return (
    <div className="space-y-3.5">
      {rendered}
      {SHOW_DIAGNOSTICS && usage && settled ? <TurnDetails usage={usage} /> : null}
    </div>
  );
}
