import { CircleSlash } from "lucide-react";
import type { ReactNode } from "react";

/** FR-13, and the hardest thing in the product to get right visually.
 *
 * "Nothing in the dataset matches that" is an ANSWER — arguably the most trustworthy
 * answer the product gives — so it must not look like an error. Neutral framing, the
 * same type as any other reply, and the adjustments stay available underneath. The
 * alternative, silently widening the filters, is what this notice exists to prevent.
 *
 * The header has to be true of two different turns, because they are structurally
 * identical on the wire: an abstention, and a refine that cannot move its axis any
 * further. Neither is an error and both end in "adjust something and I will look
 * again", so they share a frame rather than guessing between them by reading the text.
 */
export function AbstentionNotice({ children }: { children: ReactNode }) {
  return (
    <div className="rounded-card border border-line bg-sunken/60 px-4 py-3.5">
      <div className="mb-1.5 flex items-center gap-2 text-micro font-medium uppercase tracking-wide text-subtle">
        <CircleSlash size={12} />
        No results, and why
      </div>
      <div className="text-prose text-ink">{children}</div>
    </div>
  );
}
