import * as DialogPrimitive from "@radix-ui/react-dialog";
import { X } from "lucide-react";
import { useEffect, useState } from "react";
import { Outlet, useNavigate, useParams } from "react-router-dom";
import { Sidebar } from "@/components/shell/Sidebar";
import { TopBar } from "@/components/shell/TopBar";
import { OfflineBanner } from "@/components/shell/OfflineBanner";
import { TastePanel } from "@/components/taste/TastePanel";
import { IconButton } from "@/components/ui/IconButton";
import { Dialog } from "@/components/ui/Dialog";
import { ToastHost } from "@/components/ui/Toast";
import { useConversation, useRenameConversation } from "@/hooks/useConversations";
import { useKeyboardShortcuts } from "@/hooks/useKeyboardShortcuts";
import { useHasPanelRoom, useIsNarrow } from "@/hooks/useMediaQuery";
import { useUIStore } from "@/stores/useUIStore";

export function AppShell() {
  const { cid } = useParams();
  const navigate = useNavigate();
  const narrow = useIsNarrow();
  const hasPanelRoom = useHasPanelRoom();
  const [drawerOpen, setDrawerOpen] = useState(false);

  const {
    sidebarCollapsed,
    toggleSidebar,
    panelOpen,
    togglePanel,
    panelDrawerOpen,
    setPanelDrawer,
    shortcutsOpen,
    setShortcutsOpen,
  } = useUIStore();
  const { data: detail } = useConversation(cid ?? null);
  const rename = useRenameConversation();

  useEffect(() => setDrawerOpen(false), [cid]);

  useKeyboardShortcuts({
    onNewChat: () => navigate("/"),
    onShortcuts: () => setShortcutsOpen(true),
  });

  const sidebarVisible = !narrow && !sidebarCollapsed;
  // The rail needs 1280px. Below that the same panel opens as an overlay, so the
  // toggle always does something rather than being a dead control on a laptop.
  const panelAsRail = panelOpen && hasPanelRoom;

  return (
    <div className="flex h-dvh overflow-hidden bg-canvas">
      {sidebarVisible ? (
        <div className="w-sidebar shrink-0 border-r border-line">
          <Sidebar />
        </div>
      ) : null}

      <DialogPrimitive.Root open={drawerOpen} onOpenChange={setDrawerOpen}>
        <DialogPrimitive.Portal>
          <DialogPrimitive.Overlay className="fixed inset-0 z-40 bg-ink/20 lg:hidden" />
          <DialogPrimitive.Content
            aria-label="Conversations"
            className="fixed inset-y-0 left-0 z-50 w-sidebar border-r border-line bg-canvas shadow-modal"
          >
            <DialogPrimitive.Title className="sr-only">Conversations</DialogPrimitive.Title>
            <div className="absolute right-2 top-2.5 z-10">
              <DialogPrimitive.Close asChild>
                <IconButton label="Close">
                  <X size={16} />
                </IconButton>
              </DialogPrimitive.Close>
            </div>
            <Sidebar onNavigate={() => setDrawerOpen(false)} />
          </DialogPrimitive.Content>
        </DialogPrimitive.Portal>
      </DialogPrimitive.Root>

      <div className="flex min-w-0 flex-1 flex-col">
        <OfflineBanner />
        <TopBar
          title={detail?.title ?? "New conversation"}
          onRename={detail ? (title) => rename.mutate({ cid: detail.id, title }) : undefined}
          onOpenSidebar={() => (narrow ? setDrawerOpen(true) : toggleSidebar())}
          showSidebarToggle={!sidebarVisible}
          panelShown={panelAsRail}
          onTogglePanel={() => (hasPanelRoom ? togglePanel() : setPanelDrawer(true))}
        />

        <div className="flex min-h-0 flex-1">
          <main className="min-w-0 flex-1">
            <Outlet />
          </main>
          {panelAsRail ? <TastePanel profile={detail?.taste_profile} /> : null}
        </div>
      </div>

      {/* The panel as an overlay, for anything narrower than the rail needs. */}
      <DialogPrimitive.Root open={panelDrawerOpen} onOpenChange={setPanelDrawer}>
        <DialogPrimitive.Portal>
          <DialogPrimitive.Overlay className="fixed inset-0 z-40 bg-ink/20" />
          <DialogPrimitive.Content
            aria-label="Your taste profile"
            className="fixed inset-y-0 right-0 z-50 w-[min(20rem,100vw)] border-l border-line bg-canvas shadow-modal"
          >
            <DialogPrimitive.Title className="sr-only">
              Your taste profile
            </DialogPrimitive.Title>
            <div className="absolute left-2 top-2.5 z-10">
              <DialogPrimitive.Close asChild>
                <IconButton label="Close">
                  <X size={16} />
                </IconButton>
              </DialogPrimitive.Close>
            </div>
            <TastePanel profile={detail?.taste_profile} />
          </DialogPrimitive.Content>
        </DialogPrimitive.Portal>
      </DialogPrimitive.Root>

      <ToastHost />

      <Dialog open={shortcutsOpen} onOpenChange={setShortcutsOpen} title="Keyboard shortcuts">
        <dl className="space-y-2 text-why">
          <Shortcut keys="⌘ K" action="Start a new conversation" />
          <Shortcut keys="/" action="Jump to the message box" />
          <Shortcut keys="Enter" action="Send" />
          <Shortcut keys="Shift Enter" action="New line" />
          <Shortcut keys="Esc" action="Stop the answer being written" />
          <Shortcut keys="⌘ /" action="This list" />
        </dl>
      </Dialog>
    </div>
  );
}

function Shortcut({ keys, action }: { keys: string; action: string }) {
  return (
    <div className="flex items-baseline justify-between gap-4">
      <dt className="text-muted">{action}</dt>
      <dd className="shrink-0 rounded border border-line bg-sunken px-1.5 py-0.5 font-mono text-micro text-muted">
        {keys}
      </dd>
    </div>
  );
}
