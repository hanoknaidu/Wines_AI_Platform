import * as Primitive from "@radix-ui/react-popover";
import type { ReactNode } from "react";
import { cn } from "@/lib/cn";

export function Popover({
  trigger,
  children,
  align = "end",
  className,
}: {
  trigger: ReactNode;
  children: ReactNode;
  align?: "start" | "center" | "end";
  className?: string;
}) {
  return (
    <Primitive.Root>
      <Primitive.Trigger asChild>{trigger}</Primitive.Trigger>
      <Primitive.Portal>
        <Primitive.Content
          align={align}
          sideOffset={8}
          collisionPadding={12}
          className={cn(
            "z-50 w-80 rounded-card border border-line bg-surface p-4 text-why text-muted shadow-pop",
            "data-[state=open]:card-enter",
            className,
          )}
        >
          {children}
        </Primitive.Content>
      </Primitive.Portal>
    </Primitive.Root>
  );
}
