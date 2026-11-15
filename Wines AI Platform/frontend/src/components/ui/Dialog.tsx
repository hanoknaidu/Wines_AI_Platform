import * as Primitive from "@radix-ui/react-dialog";
import { X } from "lucide-react";
import type { ReactNode } from "react";
import { IconButton } from "./IconButton";

export function Dialog({
  open,
  onOpenChange,
  title,
  description,
  children,
  footer,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  title: string;
  description?: string;
  children?: ReactNode;
  footer?: ReactNode;
}) {
  return (
    <Primitive.Root open={open} onOpenChange={onOpenChange}>
      <Primitive.Portal>
        <Primitive.Overlay className="fixed inset-0 z-40 bg-ink/20 backdrop-blur-[1px]" />
        <Primitive.Content
          className="fixed left-1/2 top-1/2 z-50 w-[min(28rem,calc(100vw-2rem))] -translate-x-1/2 -translate-y-1/2 rounded-modal border border-line bg-surface p-5 shadow-modal"
          aria-describedby={description ? undefined : ""}
        >
          <div className="mb-3 flex items-start justify-between gap-4">
            <div>
              <Primitive.Title className="text-lg font-semibold text-ink">
                {title}
              </Primitive.Title>
              {description ? (
                <Primitive.Description className="mt-1 text-why text-muted">
                  {description}
                </Primitive.Description>
              ) : null}
            </div>
            <Primitive.Close asChild>
              <IconButton label="Close">
                <X size={16} />
              </IconButton>
            </Primitive.Close>
          </div>
          {children}
          {footer ? <div className="mt-5 flex justify-end gap-2">{footer}</div> : null}
        </Primitive.Content>
      </Primitive.Portal>
    </Primitive.Root>
  );
}
