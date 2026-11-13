import { setupWorker } from "msw/browser";
import * as db from "./db";
import { seedConversations } from "./fixtures/conversations";
import { handlers } from "./handlers";
import { setForced } from "./handlers/shared";
import { dropStreams } from "./stream";

export const worker = setupWorker(...handlers);

/** Hooks the styleguide drives, so every state in the plan's error table and the
 *  stream-resume path can be reached on demand rather than waited for. */
export interface MockControls {
  dropStream: (cid?: string) => number;
  forceNext: (code: string | null) => void;
  setReady: (ready: boolean) => void;
  reseed: () => void;
}

export async function startMocks(): Promise<void> {
  if (!db.restore()) seedConversations();

  const controls: MockControls = {
    dropStream: dropStreams,
    forceNext: setForced,
    setReady: (ready) => {
      db.db.ready = ready;
      db.save();
    },
    reseed: () => {
      db.reset();
      seedConversations();
      window.location.reload();
    },
  };
  (window as unknown as { waMock: MockControls }).waMock = controls;

  await worker.start({
    onUnhandledRequest: "bypass",
    quiet: true,
    serviceWorker: { url: "/mockServiceWorker.js" },
  });
}
