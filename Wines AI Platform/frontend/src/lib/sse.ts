/** EventSource with a resume cursor and our own backoff.
 *
 * The stream is per-conversation and long-lived, NOT per-turn: it is opened when the
 * conversation mounts and `POST .../messages` returns only `{turn_id}`, with the
 * content arriving here. Built the usual way — POST and read the response body — this
 * client would render nothing at all.
 *
 * Native EventSource reconnection is deliberately defeated. Left alone it would
 * reconnect to the same URL, losing `?after=`, and in particular losing the mid-run
 * `anchor_seq - 1` rule. So on any connection error we close it ourselves and reopen
 * with a freshly computed cursor.
 */

import type { Frame, FrameName } from "@/types/sse";

const FRAME_NAMES: FrameName[] = ["token", "card", "chips", "citation", "usage", "done"];
const BACKOFF_MS = [500, 1000, 2000, 4000, 8000];

export interface StreamHandlers {
  onFrame: (frame: Frame) => void;
  /** Fires before each reconnect so the caller can discard a partial run and hand
   *  back the cursor to resume from. */
  onReconnect: () => number;
  onOpen?: () => void;
  onDrop?: (attempt: number) => void;
}

export class ConversationStream {
  private source: EventSource | null = null;
  private timer: number | null = null;
  private attempt = 0;
  private closed = false;

  constructor(
    private readonly cid: string,
    private readonly handlers: StreamHandlers,
  ) {}

  open(after: number): void {
    this.closed = false;
    this.teardown();
    const url = `/api/v1/conversations/${this.cid}/stream?after=${after}`;
    // withCredentials: the session and age-gate cookies are httpOnly, and without
    // this the stream is opened by an anonymous caller and 404s on the conversation.
    const source = new EventSource(url, { withCredentials: true });
    this.source = source;

    source.onopen = () => {
      this.attempt = 0;
      this.handlers.onOpen?.();
    };

    for (const name of FRAME_NAMES) {
      source.addEventListener(name, (event) => this.dispatch(name, event as MessageEvent));
    }

    // `error` is two different things on one listener: a server-sent `event: error`
    // frame, which is a MessageEvent with data, and EventSource's own connection
    // failure, which has none. Treating the second as the first would put a
    // network blip in the transcript as though the engine had failed.
    source.addEventListener("error", (event) => {
      const message = event as MessageEvent;
      if (typeof message.data === "string" && message.data.length > 0) {
        this.dispatch("error", message);
        return;
      }
      this.scheduleReconnect();
    });
  }

  private dispatch(name: FrameName | "error", event: MessageEvent): void {
    let data: unknown;
    try {
      data = JSON.parse(event.data);
    } catch {
      return;
    }
    const id = event.lastEventId ? Number(event.lastEventId) : null;
    this.handlers.onFrame({
      name,
      id: id !== null && Number.isFinite(id) ? id : null,
      data,
    } as Frame);
  }

  private scheduleReconnect(): void {
    if (this.closed) return;
    this.teardown();
    const delay = BACKOFF_MS[Math.min(this.attempt, BACKOFF_MS.length - 1)];
    this.attempt += 1;
    this.handlers.onDrop?.(this.attempt);
    this.timer = window.setTimeout(() => {
      if (this.closed) return;
      this.open(this.handlers.onReconnect());
    }, delay);
  }

  /** Force a drop, for the styleguide's resume test. */
  drop(): void {
    this.scheduleReconnect();
  }

  close(): void {
    this.closed = true;
    this.teardown();
  }

  private teardown(): void {
    if (this.timer !== null) {
      window.clearTimeout(this.timer);
      this.timer = null;
    }
    if (this.source) {
      this.source.onopen = null;
      this.source.close();
      this.source = null;
    }
  }
}
