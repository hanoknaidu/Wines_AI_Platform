import { cn } from "@/lib/cn";
import type { ChipOption, Chips } from "@/types/api";
import { ChipRow } from "./ChipRow";

/** The live chip row, docked above the composer rather than buried in the transcript.
 *
 * The architecture puts quick-reply and refine chips in the prompt bar, and it is the
 * right call: these are the next thing to do, so they belong where the next thing to
 * do lives — reachable without scrolling, and visibly attached to the input rather
 * than to a message that has scrolled past.
 */
export function ChipDock({
  chips,
  onSelect,
  disabled,
  pendingId,
}: {
  chips: Chips;
  onSelect: (option: ChipOption) => void;
  disabled?: boolean;
  pendingId?: string | null;
}) {
  const isRefine = chips.kind === "refine";
  return (
    <div className={cn("pb-2", isRefine && "border-b border-line/0")}>
      <p className="mb-2 text-micro font-medium uppercase tracking-wide text-subtle">
        {isRefine ? "Adjust these results" : "Pick one, or say it your own way"}
      </p>
      <ChipRow
        options={chips.options}
        onSelect={onSelect}
        disabled={disabled}
        pendingId={pendingId}
      />
    </div>
  );
}
