import { create } from "zustand";

/** Drafts are per conversation, so switching away and back does not lose what someone
 *  had half-typed. Kept in memory only — an unsent draft is not worth a storage quota. */
interface ComposerStore {
  drafts: Record<string, string>;
  setDraft: (key: string, value: string) => void;
  clearDraft: (key: string) => void;
}

export const useComposerStore = create<ComposerStore>((set) => ({
  drafts: {},
  setDraft: (key, value) => set((state) => ({ drafts: { ...state.drafts, [key]: value } })),
  clearDraft: (key) =>
    set((state) => {
      const drafts = { ...state.drafts };
      delete drafts[key];
      return { drafts };
    }),
}));
