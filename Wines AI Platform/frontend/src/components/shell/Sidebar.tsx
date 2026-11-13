import { Archive, MessageSquarePlus, PanelLeftClose } from "lucide-react";
import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { ConversationList } from "@/components/conversations/ConversationList";
import { ConversationSearch } from "@/components/conversations/ConversationSearch";
import { Button } from "@/components/ui/Button";
import { IconButton } from "@/components/ui/IconButton";
import { HowThisWorksButton } from "@/components/trust/HowThisWorksPanel";
import { useUIStore } from "@/stores/useUIStore";
import { cn } from "@/lib/cn";
import { Wordmark } from "./Wordmark";

export function Sidebar({ onNavigate }: { onNavigate?: () => void }) {
  const [query, setQuery] = useState("");
  const [archived, setArchived] = useState(false);
  const toggleSidebar = useUIStore((state) => state.toggleSidebar);
  const navigate = useNavigate();

  return (
    <div className="flex h-full flex-col bg-canvas">
      <div className="flex items-center justify-between px-3 py-2.5">
        <Wordmark />
        <IconButton label="Hide sidebar" onClick={toggleSidebar} className="lg:inline-flex">
          <PanelLeftClose size={16} />
        </IconButton>
      </div>

      <div className="space-y-2 px-3 pb-2">
        <Button
          variant="secondary"
          className="w-full justify-start"
          size="sm"
          onClick={() => {
            navigate("/");
            onNavigate?.();
          }}
        >
          <MessageSquarePlus size={15} />
          New conversation
        </Button>
        <ConversationSearch value={query} onChange={setQuery} />
      </div>

      <nav
        aria-label="Conversations"
        className="min-h-0 flex-1 overflow-y-auto overscroll-contain"
      >
        <ConversationList query={query} archived={archived} />
      </nav>

      <div className="flex items-center justify-between gap-2 border-t border-line px-3 py-2">
        <HowThisWorksButton />
        <button
          type="button"
          onClick={() => setArchived((value) => !value)}
          aria-pressed={archived}
          className={cn(
            "inline-flex items-center gap-1.5 rounded-control px-2 py-1 text-micro transition-colors",
            archived ? "bg-sunken text-ink" : "text-subtle hover:text-muted",
          )}
        >
          <Archive size={12} />
          Archived
        </button>
      </div>
    </div>
  );
}
