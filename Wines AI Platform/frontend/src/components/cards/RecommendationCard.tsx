import { useTasteAxes } from "@/hooks/useTasteAxes";
import { cn } from "@/lib/cn";
import type { Card } from "@/types/api";
import { AxisReadings } from "./AxisReadings";
import { FeedbackButtons } from "./FeedbackButtons";
import { ProducerList } from "./ProducerList";
import { ProvenanceFooter } from "./ProvenanceFooter";
import { RegionPills } from "./RegionPills";
import { StyleDot } from "./StyleDot";
import { TastingNote } from "./TastingNote";
import { WhyItMatches } from "./WhyItMatches";

/** The centrepiece.
 *
 * Note what is deliberately NOT here, all of it from BRD §8: no match score, no star
 * rating, no "94% fit" badge, no position number, no "best match" language, no price,
 * no buy button, no vintage. The product recommends FIT, not quality — and a number
 * beside a wine reads as a verdict, which would make it the thing it was built to
 * replace. The cards are a list, and the list is not numbered.
 *
 * The variety leads because it is the transferable answer: learning you like Grenache
 * is worth more than learning you liked one bottle.
 */
export function RecommendationCard({
  card,
  messageId,
  animate,
}: {
  card: Card;
  messageId: string | null;
  animate?: boolean;
}) {
  const { data: axes } = useTasteAxes();
  const threshold = axes?.confidence_threshold ?? 0.75;

  return (
    <article
      className={cn(
        "rounded-card border border-line bg-surface p-4 sm:p-5",
        animate && "card-enter",
      )}
      aria-label={card.variety}
    >
      <header className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <h3 className="text-variety font-semibold tracking-tight text-ink">{card.variety}</h3>
          <div className="mt-1">
            <StyleDot style={card.style} />
          </div>
        </div>
        <FeedbackButtons messageId={messageId} rowId={card.row_id} />
      </header>

      <div className="mt-3.5 space-y-3.5">
        <TastingNote text={card.description} />
        <WhyItMatches text={card.why_it_matches} />
        <AxisReadings axes={card.axes} threshold={threshold} />

        <div className="grid gap-3.5 border-t border-line pt-3.5 sm:grid-cols-2">
          <RegionPills regions={card.typical_regions} />
          <ProducerList
            producers={card.example_producers}
            reviewStatus={card.review_status}
          />
        </div>

        <div className="border-t border-line pt-3">
          <ProvenanceFooter
            rowId={card.row_id}
            datasetVersion={card.dataset_version}
            reviewStatus={card.review_status}
          />
        </div>
      </div>
    </article>
  );
}
