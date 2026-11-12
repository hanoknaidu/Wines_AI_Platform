import { cn } from "@/lib/cn";
import type { ChipOption } from "@/types/api";

/** Option buttons emitted by the engine, so a novice never has to type a wine word.
 *  Every label here comes from the `chips` frame — nothing in this file knows what a
 *  single one of them says. */
export function ChipRow({
  options,
  onSelect,
  disabled,
  pendingId,
}: {
  options: ChipOption[];
  onSelect: (option: ChipOption) => void;
  disabled?: boolean;
  pendingId?: string | null;
}) {
  return (
    <div className="flex flex-wrap gap-2">
      {options.map((option) => (
        <button
          key={option.id}
          type="button"
          onClick={() => onSelect(option)}
          disabled={disabled}
          aria-busy={pendingId === option.id}
          className={cn(
            "rounded-full border px-3.5 py-1.5 text-chip transition-colors duration-150",
            "disabled:cursor-not-allowed disabled:opacity-60",
            pendingId === option.id
              ? "border-brand-500 bg-brand-50 text-brand-900"
              : "border-line bg-surface text-ink hover:border-brand-500 hover:bg-brand-50 hover:text-brand-900",
          )}
        >
          {option.label}
        </button>
      ))}
    </div>
  );
}
