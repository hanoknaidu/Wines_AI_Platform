import { create } from "zustand";
import { PANEL_STORAGE_KEY, SIDEBAR_STORAGE_KEY } from "@/lib/constants";

function read(key: string, fallback: boolean): boolean {
  try {
    const raw = localStorage.getItem(key);
    return raw === null ? fallback : raw === "true";
  } catch {
    return fallback;
  }
}

function write(key: string, value: boolean): void {
  try {
    localStorage.setItem(key, String(value));
  } catch {
    // A blocked store is not a reason to break the layout.
  }
}

interface UIStore {
  sidebarCollapsed: boolean;
  /** The rail's remembered preference, for viewports wide enough to hold it. */
  panelOpen: boolean;
  /** The same panel as an overlay, for viewports that are not. Never persisted: a
   *  drawer that reopens itself on every page load is a nuisance. */
  panelDrawerOpen: boolean;
  shortcutsOpen: boolean;
  toggleSidebar: () => void;
  setSidebar: (collapsed: boolean) => void;
  togglePanel: () => void;
  setPanelDrawer: (open: boolean) => void;
  setShortcutsOpen: (open: boolean) => void;
}

export const useUIStore = create<UIStore>((set) => ({
  sidebarCollapsed: read(SIDEBAR_STORAGE_KEY, false),
  panelOpen: read(PANEL_STORAGE_KEY, true),
  panelDrawerOpen: false,
  shortcutsOpen: false,
  toggleSidebar: () =>
    set((state) => {
      write(SIDEBAR_STORAGE_KEY, !state.sidebarCollapsed);
      return { sidebarCollapsed: !state.sidebarCollapsed };
    }),
  setSidebar: (collapsed) => {
    write(SIDEBAR_STORAGE_KEY, collapsed);
    set({ sidebarCollapsed: collapsed });
  },
  togglePanel: () =>
    set((state) => {
      write(PANEL_STORAGE_KEY, !state.panelOpen);
      return { panelOpen: !state.panelOpen };
    }),
  setPanelDrawer: (open) => set({ panelDrawerOpen: open }),
  setShortcutsOpen: (open) => set({ shortcutsOpen: open }),
}));
