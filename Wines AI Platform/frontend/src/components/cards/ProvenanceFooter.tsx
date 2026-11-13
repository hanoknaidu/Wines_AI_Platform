import { Badge } from "@/components/ui/Badge";
import { Tooltip } from "@/components/ui/Tooltip";
import { REVIEW_BADGE, REVIEW_TOOLTIP, reviewStatusOf } from "@/lib/review";

/** Where this card came from. Every field above it was served from this row of this
 *  artifact, which is what makes "no invented bottle" checkable rather than promised.
 *
 *  The review badge is four-state, not two: a `fixture` row carries producer names that
 *  no person has checked, so it must not render as reviewed. See `lib/review.ts`. */
export function ProvenanceFooter({
  rowId,
  datasetVersion,
  reviewStatus,
}: {
  rowId: string;
  datasetVersion: string;
  reviewStatus: string;
}) {
  const status = reviewStatusOf(reviewStatus);
  const { label, tone } = REVIEW_BADGE[status];
  return (
    <div className="flex flex-wrap items-center gap-x-3 gap-y-1.5">
      <Tooltip content="Everything on this card was served from this row of this dataset version. Nothing was written at the time you asked.">
        <span className="cursor-help font-mono text-micro text-subtle tabular">
          {rowId} · {datasetVersion}
        </span>
      </Tooltip>
      <Tooltip content={REVIEW_TOOLTIP[status]}>
        <span className="cursor-help">
          <Badge tone={tone}>{label}</Badge>
        </span>
      </Tooltip>
    </div>
  );
}
