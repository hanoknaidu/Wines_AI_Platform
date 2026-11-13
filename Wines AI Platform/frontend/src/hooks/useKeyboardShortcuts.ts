import { useEffect } from "react";

export interface Shortcuts {
  onNewChat?: () => void;
  onStop?: () => void;
  onShortcuts?: () => void;
  onFocusComposer?: () => void;
}

function isTyping(target: EventTarget | null): boolean {
  if (!(target instanceof HTMLElement)) return false;
  return (
    target.tagName === "INPUT" || target.tagName === "TEXTAREA" || target.isContentEditable
  );
}

export function useKeyboardShortcuts(shortcuts: Shortcuts): void {
  useEffect(() => {
    const onKeyDown = (event: KeyboardEvent) => {
      const meta = event.metaKey || event.ctrlKey;

      if (meta && event.key.toLowerCase() === "k") {
        event.preventDefault();
        shortcuts.onNewChat?.();
        return;
      }
      if (meta && event.key === "/") {
        event.preventDefault();
        shortcuts.onShortcuts?.();
        return;
      }
      if (event.key === "Escape") {
        shortcuts.onStop?.();
        return;
      }
      // A bare keystroke must never steal focus from a field someone is typing in.
      if (!meta && !isTyping(event.target) && event.key === "/") {
        event.preventDefault();
        shortcuts.onFocusComposer?.();
      }
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [shortcuts]);
}
