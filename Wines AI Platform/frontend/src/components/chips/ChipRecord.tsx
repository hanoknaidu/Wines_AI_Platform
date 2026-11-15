import { Check } from "lucide-react";
import type { Chips } from "@/types/api";

/** An older chip row, kept as a record of what was offered and what was taken.
 *
 * Clicking a chip three turns up is ambiguous — it would refine the CURRENT profile
 * while pointing at a result set that has scrolled away — so only the newest row stays
 * live, and the history reads as history rather than as a field of stale buttons.
 */
export function ChipRecord({ chips, chosen }: { chips: Chips; chosen?: string | null }) {
  return (
    <div className="flex flex-wrap items-center gap-1.5">
      {chips.options.map((option) => {
        const taken = chosen === option.id;
        return (
          <span
            key={option.id}
            className={
              taken
                ? "inline-flex items-center gap-1 rounded-full border border-brand-100 bg-brand-50 px-2.5 py-1 text-micro text-brand-900"
                : "inline-flex items-center rounded-full border border-line px-2.5 py-1 text-micro text-subtle"
            }
          >
            {taken ? <Check size={10} /> : null}
            {option.label}
          </span>
        );
      })}
    </div>
  );
}
