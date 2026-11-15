import { TrendingDown } from "lucide-react";

/** The turn produced a lower-fidelity answer than it should have, and says so.
 *
 *  Every cause here is a deliberate degradation rather than a failure: a ceiling was
 *  reached, the model was unreachable, or a generated sentence failed its grounding
 *  check and was replaced by copy drawn straight from the dataset row. In every case
 *  the recommendations themselves come from the same reviewed rows — what changed is
 *  the prose around them. The user is told rather than quietly served something
 *  different.
 *
 *  An honest empty state is NOT a degradation and never reaches this component: an
 *  abstention is the product working as specified (FR-13). */
const REASONS: Record<string, string> = {
  cost_ceiling:
    "A spending ceiling was reached, so this answer came from the free engine. The recommendations are still served from the same dataset rows.",
  turn_budget:
    "This turn reached its own spending limit partway through, so the wording was completed from the dataset rows rather than written in full.",
  generator_unavailable:
    "The language model could not be reached, so the wording was drawn straight from the dataset rows. The recommendations themselves are unaffected.",
  verify_repair:
    "Part of the wording did not trace back to a dataset row, so it was replaced with copy drawn from the row itself.",
};

const FALLBACK = REASONS.cost_ceiling;

export function DegradedNotice({ reason }: { reason?: string | null } = {}) {
  return (
    <div className="flex items-start gap-2 rounded-control border border-caution-br bg-caution-bg px-3 py-2">
      <TrendingDown size={14} className="mt-0.5 shrink-0 text-caution-fg" />
      <p className="text-micro leading-relaxed text-caution-fg">
        {(reason && REASONS[reason]) || FALLBACK}
      </p>
    </div>
  );
}
