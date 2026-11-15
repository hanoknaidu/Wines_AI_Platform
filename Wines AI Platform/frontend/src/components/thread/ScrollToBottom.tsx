import { ArrowDown } from "lucide-react";

export function ScrollToBottom({ onClick }: { onClick: () => void }) {
  return (
    <button
      type="button"
      onClick={onClick}
      className="absolute bottom-3 left-1/2 -translate-x-1/2 rounded-full border border-line bg-surface px-3 py-1.5 text-micro text-muted shadow-pop transition-colors hover:text-ink"
    >
      <span className="inline-flex items-center gap-1.5">
        <ArrowDown size={12} />
        Jump to the latest
      </span>
    </button>
  );
}
