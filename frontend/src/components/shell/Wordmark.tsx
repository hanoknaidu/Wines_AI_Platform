import { cn } from "@/lib/cn";

export function Wordmark({
  className,
  compact = false,
}: {
  className?: string;
  compact?: boolean;
}) {
  return (
    <span className={cn("inline-flex items-center gap-2", className)}>
      <svg viewBox="0 0 32 32" aria-hidden className="h-5 w-5 shrink-0">
        <path
          d="M9 5h14l-1.6 9.2A5.4 5.4 0 0 1 16 18.6a5.4 5.4 0 0 1-5.4-4.4L9 5Z"
          className="fill-brand-600"
        />
        <path
          d="M16 18.5V26M11.5 26h9"
          className="stroke-brand-900"
          strokeWidth="2"
          strokeLinecap="round"
          fill="none"
        />
      </svg>
      {!compact ? (
        <span className="text-[0.9375rem] font-semibold tracking-tight text-ink">Wines AI</span>
      ) : null}
    </span>
  );
}
