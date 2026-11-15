import type { ReactNode } from "react";
import { cn } from "@/lib/cn";

export type Tone = "neutral" | "ok" | "caution" | "danger" | "info" | "brand";

const TONES: Record<Tone, string> = {
  neutral: "bg-sunken text-muted border-line",
  ok: "bg-ok-bg text-ok-fg border-ok-br",
  caution: "bg-caution-bg text-caution-fg border-caution-br",
  danger: "bg-danger-bg text-danger-fg border-danger-br",
  info: "bg-info-bg text-info-fg border-info-br",
  brand: "bg-brand-50 text-brand-700 border-brand-100",
};

export function Badge({
  tone = "neutral",
  className,
  children,
}: {
  tone?: Tone;
  className?: string;
  children: ReactNode;
}) {
  return (
    <span
      className={cn(
        "inline-flex items-center gap-1 rounded-full border px-2 py-0.5 text-micro font-medium",
        TONES[tone],
        className,
      )}
    >
      {children}
    </span>
  );
}

/** A region or a producer. Flat, bordered, never a button — these are not filters. */
export function Pill({ children, className }: { children: ReactNode; className?: string }) {
  return (
    <span
      className={cn(
        "inline-flex items-center rounded-full border border-line bg-surface px-2.5 py-1 text-chip text-muted",
        className,
      )}
    >
      {children}
    </span>
  );
}
