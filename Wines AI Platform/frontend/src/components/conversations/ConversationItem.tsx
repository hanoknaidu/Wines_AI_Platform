import { Archive, ArchiveRestore, MoreHorizontal, Pencil, Trash2 } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";
import { IconButton } from "@/components/ui/IconButton";
import { Menu, MenuItem } from "@/components/ui/Menu";
import { cn } from "@/lib/cn";
import { TITLE_MAX_CHARS } from "@/lib/constants";
import { relativeTime } from "@/lib/format";
import type { ConversationSummary } from "@/types/api";

export function ConversationItem({
  conversation,
  active,
  onRename,
  onArchive,
  onDelete,
}: {
  conversation: ConversationSummary;
  active: boolean;
  onRename: (title: string) => void;
  onArchive: (archived: boolean) => void;
  onDelete: () => void;
}) {
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState(conversation.title);
  const inputRef = useRef<HTMLInputElement | null>(null);

  useEffect(() => {
    if (editing) inputRef.current?.select();
  }, [editing]);

  const commit = () => {
    const title = draft.trim();
    setEditing(false);
    if (title && title !== conversation.title) onRename(title);
    else setDraft(conversation.title);
  };

  if (editing) {
    return (
      <li className="px-1">
        <input
          ref={inputRef}
          value={draft}
          maxLength={TITLE_MAX_CHARS}
          onChange={(event) => setDraft(event.target.value)}
          onBlur={commit}
          onKeyDown={(event) => {
            if (event.key === "Enter") commit();
            if (event.key === "Escape") {
              setDraft(conversation.title);
              setEditing(false);
            }
          }}
          aria-label="Conversation title"
          className="h-9 w-full rounded-control border border-brand-500 bg-surface px-2.5 text-chip text-ink focus:outline-none"
        />
      </li>
    );
  }

  return (
    <li className="group relative px-1">
      <Link
        to={`/c/${conversation.id}`}
        className={cn(
          "flex min-h-9 items-center gap-2 rounded-control px-2.5 py-1.5 pr-8 text-chip transition-colors duration-150",
          active
            ? "bg-brand-50 text-brand-900 ring-1 ring-brand-100"
            : "text-muted hover:bg-sunken hover:text-ink",
        )}
        aria-current={active ? "page" : undefined}
      >
        <span className="min-w-0 flex-1 truncate">{conversation.title}</span>
        <span className="shrink-0 text-micro text-subtle tabular">
          {relativeTime(conversation.updated_at)}
        </span>
      </Link>

      <div className="absolute right-1.5 top-1/2 -translate-y-1/2 opacity-0 transition-opacity focus-within:opacity-100 group-hover:opacity-100">
        <Menu
          trigger={
            <IconButton
              label={`Actions for ${conversation.title}`}
              className="h-7 w-7 bg-surface"
            >
              <MoreHorizontal size={14} />
            </IconButton>
          }
        >
          <MenuItem onSelect={() => setEditing(true)}>
            <Pencil size={13} /> Rename
          </MenuItem>
          <MenuItem onSelect={() => onArchive(!conversation.archived)}>
            {conversation.archived ? <ArchiveRestore size={13} /> : <Archive size={13} />}
            {conversation.archived ? "Unarchive" : "Archive"}
          </MenuItem>
          <MenuItem tone="danger" onSelect={onDelete}>
            <Trash2 size={13} /> Delete
          </MenuItem>
        </Menu>
      </div>
    </li>
  );
}
