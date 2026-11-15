import { ArrowUp, Square } from "lucide-react";
import { forwardRef, useEffect, useImperativeHandle, useLayoutEffect, useRef } from "react";
import { cn } from "@/lib/cn";
import { COUNTER_FROM, MAX_MESSAGE_CHARS } from "@/lib/constants";

export interface ComposerHandle {
  focus: () => void;
}

/** Free text is a first-class input, not a fallback — so this is a real textarea with
 *  the conventions people already have: Enter sends, Shift+Enter breaks the line.
 *
 *  Every reason the send button is unavailable is said in words. A dead button with no
 *  explanation is the most common small cruelty in chat UIs. */
export const Composer = forwardRef<
  ComposerHandle,
  {
    value: string;
    onChange: (value: string) => void;
    onSend: () => void;
    onStop: () => void;
    streaming: boolean;
    disabledReason?: string | null;
  }
>(function Composer({ value, onChange, onSend, onStop, streaming, disabledReason }, ref) {
  const area = useRef<HTMLTextAreaElement | null>(null);

  useImperativeHandle(ref, () => ({ focus: () => area.current?.focus() }), []);

  // Auto-grow, capped — a composer that eats the thread is worse than a scrollbar.
  useLayoutEffect(() => {
    const element = area.current;
    if (!element) return;
    element.style.height = "auto";
    element.style.height = `${Math.min(element.scrollHeight, 200)}px`;
  }, [value]);

  useEffect(() => {
    if (!streaming) area.current?.focus();
  }, [streaming]);

  const tooLong = value.length > MAX_MESSAGE_CHARS;
  const blocked = Boolean(disabledReason) || tooLong;
  const canSend = value.trim().length > 0 && !blocked && !streaming;

  return (
    <div className="px-4 pb-4">
      <div className="mx-auto max-w-measure">
        <div
          className={cn(
            "flex items-end gap-2 rounded-card border bg-surface p-2 transition-colors",
            tooLong ? "border-danger-br" : "border-line focus-within:border-line-strong",
          )}
        >
          <textarea
            ref={area}
            value={value}
            rows={1}
            onChange={(event) => onChange(event.target.value)}
            onKeyDown={(event) => {
              if (event.key === "Enter" && !event.shiftKey) {
                event.preventDefault();
                if (canSend) onSend();
              }
            }}
            placeholder="Say what you like, in your own words"
            aria-label="Message"
            aria-describedby="composer-hint"
            className="max-h-[200px] min-h-9 flex-1 resize-none bg-transparent px-2 py-1.5 text-prose text-ink placeholder:text-subtle focus:outline-none"
          />

          {streaming ? (
            <button
              type="button"
              onClick={onStop}
              className="inline-flex h-9 w-9 shrink-0 items-center justify-center rounded-control border border-line text-muted transition-colors hover:bg-sunken hover:text-ink"
              aria-label="Stop writing the answer"
              title="Stop (Esc)"
            >
              <Square size={13} />
            </button>
          ) : (
            <button
              type="button"
              onClick={onSend}
              disabled={!canSend}
              className="inline-flex h-9 w-9 shrink-0 items-center justify-center rounded-control bg-brand-700 text-white transition-colors hover:bg-brand-600 disabled:bg-line-strong disabled:text-surface"
              aria-label="Send"
            >
              <ArrowUp size={16} />
            </button>
          )}
        </div>

        <div
          id="composer-hint"
          className="mt-1.5 flex min-h-4 items-baseline justify-between gap-3 px-1"
        >
          <p className="text-micro text-subtle">
            {disabledReason ? (
              <span className="text-caution-fg">{disabledReason}</span>
            ) : streaming ? (
              "Writing the answer — press Esc to stop."
            ) : (
              "Enter to send · Shift + Enter for a new line"
            )}
          </p>
          {value.length >= COUNTER_FROM ? (
            <p
              className={cn(
                "shrink-0 text-micro tabular",
                tooLong ? "text-danger-fg" : "text-subtle",
              )}
            >
              {value.length} / {MAX_MESSAGE_CHARS}
            </p>
          ) : null}
        </div>
      </div>
    </div>
  );
});
