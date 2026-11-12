import * as Primitive from "@radix-ui/react-tooltip";
import type { ReactNode } from "react";

export function TooltipProvider({ children }: { children: ReactNode }) {
  return (
    <Primitive.Provider delayDuration={250} skipDelayDuration={400}>
      {children}
    </Primitive.Provider>
  );
}

export function Tooltip({
  content,
  children,
  side = "top",
}: {
  content: ReactNode;
  children: ReactNode;
  side?: "top" | "right" | "bottom" | "left";
}) {
  return (
    <Primitive.Root>
      <Primitive.Trigger asChild>{children}</Primitive.Trigger>
      <Primitive.Portal>
        <Primitive.Content
          side={side}
          sideOffset={6}
          className="z-50 max-w-72 rounded-control border border-line bg-surface px-2.5 py-1.5 text-micro text-muted shadow-pop"
        >
          {content}
          <Primitive.Arrow className="fill-surface" />
        </Primitive.Content>
      </Primitive.Portal>
    </Primitive.Root>
  );
}
