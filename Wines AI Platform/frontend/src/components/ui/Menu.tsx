import * as Primitive from "@radix-ui/react-dropdown-menu";
import type { ReactNode } from "react";
import { cn } from "@/lib/cn";

export function Menu({ trigger, children }: { trigger: ReactNode; children: ReactNode }) {
  return (
    <Primitive.Root>
      <Primitive.Trigger asChild>{trigger}</Primitive.Trigger>
      <Primitive.Portal>
        <Primitive.Content
          align="end"
          sideOffset={4}
          className="z-50 min-w-44 rounded-card border border-line bg-surface p-1 shadow-pop"
        >
          {children}
        </Primitive.Content>
      </Primitive.Portal>
    </Primitive.Root>
  );
}

export function MenuItem({
  children,
  onSelect,
  tone = "neutral",
}: {
  children: ReactNode;
  onSelect: () => void;
  tone?: "neutral" | "danger";
}) {
  return (
    <Primitive.Item
      onSelect={onSelect}
      className={cn(
        "flex cursor-pointer items-center gap-2 rounded-control px-2.5 py-1.5 text-chip outline-none",
        tone === "danger"
          ? "text-danger-fg data-[highlighted]:bg-danger-bg"
          : "text-muted data-[highlighted]:bg-sunken data-[highlighted]:text-ink",
      )}
    >
      {children}
    </Primitive.Item>
  );
}
