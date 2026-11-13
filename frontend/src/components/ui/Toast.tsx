import { AlertTriangle, Info, X } from "lucide-react";
import { create } from "zustand";
import { cn } from "@/lib/cn";
import { IconButton } from "./IconButton";

export interface ToastItem {
  id: string;
  title: string;
  detail?: string;
  /** The request id from problem+json. The only honest thing to show a user about an
   *  internal error: no stack trace, but something support can trace. */
  requestId?: string | null;
  tone: "info" | "danger";
}

interface ToastStore {
  items: ToastItem[];
  push: (item: Omit<ToastItem, "id">) => void;
  dismiss: (id: string) => void;
}

export const useToasts = create<ToastStore>((set) => ({
  items: [],
  push: (item) => {
    const id = `${Date.now()}-${Math.random().toString(16).slice(2, 7)}`;
    set((state) => ({ items: [...state.items, { ...item, id }] }));
    window.setTimeout(() => set((s) => ({ items: s.items.filter((i) => i.id !== id) })), 8000);
  },
  dismiss: (id) => set((state) => ({ items: state.items.filter((i) => i.id !== id) })),
}));

export function ToastHost() {
  const { items, dismiss } = useToasts();
  if (!items.length) return null;
  return (
    <div
      className="pointer-events-none fixed bottom-4 right-4 z-50 flex w-[min(24rem,calc(100vw-2rem))] flex-col gap-2"
      role="region"
      aria-label="Notifications"
    >
      {items.map((item) => (
        <div
          key={item.id}
          role="status"
          className={cn(
            "card-enter pointer-events-auto flex items-start gap-2.5 rounded-card border bg-surface p-3 shadow-pop",
            item.tone === "danger" ? "border-danger-br" : "border-line",
          )}
        >
          <span className={item.tone === "danger" ? "text-danger-fg" : "text-info-fg"}>
            {item.tone === "danger" ? <AlertTriangle size={16} /> : <Info size={16} />}
          </span>
          <div className="min-w-0 flex-1">
            <p className="text-chip font-medium text-ink">{item.title}</p>
            {item.detail ? <p className="mt-0.5 text-micro text-muted">{item.detail}</p> : null}
            {item.requestId ? (
              <p className="mt-1 font-mono text-micro text-subtle tabular">{item.requestId}</p>
            ) : null}
          </div>
          <IconButton label="Dismiss" onClick={() => dismiss(item.id)}>
            <X size={14} />
          </IconButton>
        </div>
      ))}
    </div>
  );
}
