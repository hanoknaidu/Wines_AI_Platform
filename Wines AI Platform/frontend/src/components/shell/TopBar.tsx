import { PanelLeftOpen, PanelRight, SlidersHorizontal } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { DatasetBadge } from "@/components/trust/DatasetBadge";
import { IconButton } from "@/components/ui/IconButton";
import { TITLE_MAX_CHARS } from "@/lib/constants";

export function TopBar({
  title,
  onRename,
  onOpenSidebar,
  showSidebarToggle,
  panelShown,
  onTogglePanel,
}: {
  title: string;
  onRename?: (title: string) => void;
  onOpenSidebar: () => void;
  showSidebarToggle: boolean;
  panelShown: boolean;
  onTogglePanel: () => void;
}) {
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState(title);
  const inputRef = useRef<HTMLInputElement | null>(null);

  useEffect(() => setDraft(title), [title]);
  useEffect(() => {
    if (editing) inputRef.current?.select();
  }, [editing]);

  const commit = () => {
    setEditing(false);
    const next = draft.trim();
    if (next && next !== title) onRename?.(next);
    else setDraft(title);
  };

  return (
    <header className="flex h-topbar shrink-0 items-center gap-2 border-b border-line bg-canvas/80 px-3 backdrop-blur">
      {showSidebarToggle ? (
        <IconButton label="Show sidebar" onClick={onOpenSidebar}>
          <PanelLeftOpen size={16} />
        </IconButton>
      ) : null}

      <div className="min-w-0 flex-1">
        {editing && onRename ? (
          <input
            ref={inputRef}
            value={draft}
            maxLength={TITLE_MAX_CHARS}
            onChange={(event) => setDraft(event.target.value)}
            onBlur={commit}
            onKeyDown={(event) => {
              if (event.key === "Enter") commit();
              if (event.key === "Escape") {
                setDraft(title);
                setEditing(false);
              }
            }}
            aria-label="Conversation title"
            className="h-8 w-full max-w-md rounded-control border border-brand-500 bg-surface px-2 text-chip font-medium text-ink focus:outline-none"
          />
        ) : onRename ? (
          <button
            type="button"
            onClick={() => setEditing(true)}
            className="max-w-full truncate rounded-control px-1.5 py-1 text-chip font-medium text-ink hover:bg-sunken"
            title="Rename"
          >
            {title}
          </button>
        ) : (
          /* Nothing to rename yet, so nothing to click: a dead button that looks
             live is worse than plain text. */
          <span className="block max-w-full truncate px-1.5 py-1 text-chip font-medium text-muted">
            {title}
          </span>
        )}
      </div>

      <DatasetBadge />

      <IconButton
        label={panelShown ? "Hide taste panel" : "Show taste panel"}
        onClick={onTogglePanel}
        tone={panelShown ? "brand" : "neutral"}
      >
        {panelShown ? <PanelRight size={16} /> : <SlidersHorizontal size={16} />}
      </IconButton>
    </header>
  );
}
