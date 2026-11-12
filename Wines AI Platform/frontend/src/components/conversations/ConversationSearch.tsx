import { Search, X } from "lucide-react";
import { IconButton } from "@/components/ui/IconButton";

export function ConversationSearch({
  value,
  onChange,
}: {
  value: string;
  onChange: (value: string) => void;
}) {
  return (
    <div className="relative">
      <Search
        size={14}
        aria-hidden
        className="pointer-events-none absolute left-2.5 top-1/2 -translate-y-1/2 text-subtle"
      />
      <input
        type="search"
        value={value}
        onChange={(event) => onChange(event.target.value)}
        placeholder="Search conversations"
        aria-label="Search conversations by title"
        className="h-9 w-full rounded-control border border-line bg-surface pl-8 pr-8 text-chip text-ink placeholder:text-subtle focus:border-line-strong focus:outline-none focus-visible:outline-2 focus-visible:outline-brand-600"
      />
      {value ? (
        <IconButton
          label="Clear search"
          onClick={() => onChange("")}
          className="absolute right-0.5 top-1/2 h-7 w-7 -translate-y-1/2"
        >
          <X size={13} />
        </IconButton>
      ) : null}
    </div>
  );
}
