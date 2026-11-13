/** A minimal EventSource over fetch, for jsdom — which has none.
 *
 * It exists so the full app can be driven in a test the way a browser drives it:
 * through the same long-lived SSE connection, the same `id:`/`event:`/`data:` framing
 * and the same resume URL. A hand-rolled transport in the test would prove nothing
 * about the transport the app actually uses.
 */

type Listener = (event: MessageEvent) => void;

/** Set WA_SSE_DEBUG=1 to trace every open, frame, close and error with a timestamp.
 *  The integration suite's failures are stalls - a test that waits on content that
 *  never arrives - and a stall is only diagnosable from the transport's own timeline. */
const DEBUG = process.env.WA_SSE_DEBUG === "1";
let seq = 0;
const t0 = Date.now();

function trace(id: number, event: string, detail = ""): void {
  if (!DEBUG) return;
  const live = ((globalThis as { __waSources?: FetchEventSource[] }).__waSources ?? []).filter(
    (s) => s.readyState !== FetchEventSource.CLOSED,
  ).length;
  // eslint-disable-next-line no-console
  console.log(
    `[sse +${String(Date.now() - t0).padStart(6)}ms] #${id} ${event.padEnd(10)} live=${live} ${detail}`,
  );
}

export class FetchEventSource {
  static readonly CONNECTING = 0;
  static readonly OPEN = 1;
  static readonly CLOSED = 2;

  readyState = FetchEventSource.CONNECTING;
  onopen: ((event: Event) => void) | null = null;
  onerror: ((event: Event) => void) | null = null;
  onmessage: Listener | null = null;
  lastEventId = "";

  private listeners = new Map<string, Set<Listener>>();
  /** No AbortSignal: jsdom's AbortController and node's fetch live in different
   *  realms, and undici rejects the foreign signal outright. Cancelling the body
   *  reader closes the connection just as well. */
  private reader: ReadableStreamDefaultReader<Uint8Array> | null = null;
  readonly id: number = 0;

  constructor(
    readonly url: string,
    _init?: { withCredentials?: boolean },
  ) {
    // Registered so a test can sever the connection mid-answer and watch the client
    // resume. A browser gives no such handle; this is the shim's one extra.
    const registry = globalThis as unknown as { __waSources?: FetchEventSource[] };
    registry.__waSources = [...(registry.__waSources ?? []), this];
    this.id = ++seq;
    trace(this.id, "construct", url);
    void this.run();
  }

  addEventListener(name: string, listener: Listener): void {
    let set = this.listeners.get(name);
    if (!set) {
      set = new Set();
      this.listeners.set(name, set);
    }
    set.add(listener);
  }

  removeEventListener(name: string, listener: Listener): void {
    this.listeners.get(name)?.delete(listener);
  }

  close(): void {
    trace(this.id, "close", `was=${this.readyState}`);
    this.readyState = FetchEventSource.CLOSED;
    void this.reader?.cancel().catch(() => {});
  }

  private emit(name: string, data: string, id: string): void {
    const event = new MessageEvent(name, { data, lastEventId: id });
    // The real EventSource sets lastEventId before dispatch; the client reads it off
    // the event, so both paths have to agree.
    for (const listener of this.listeners.get(name) ?? []) listener(event);
    if (name === "message") this.onmessage?.(event);
  }

  private async run(): Promise<void> {
    try {
      const response = await fetch(this.url, {
        headers: { Accept: "text/event-stream" },
      });
      if (!response.ok || !response.body) {
        trace(this.id, "http-fail", `status=${response.status}`);
        this.fail();
        return;
      }
      this.readyState = FetchEventSource.OPEN;
      trace(this.id, "open");
      this.onopen?.(new Event("open"));

      const reader = response.body.getReader();
      this.reader = reader;
      const decoder = new TextDecoder();
      let buffer = "";

      for (;;) {
        const { value, done } = await reader.read();
        if (done) {
          trace(this.id, "body-end", "signalling error so the client can resume");
          // A real EventSource treats a closed connection as an error and reconnects.
          // The app deliberately defeats native reconnection and drives resume off this
          // listener instead (lib/sse.ts), so a shim that just returned here left the
          // client with no way to learn it should reopen with `?after=` — it would wait
          // on a stream that had already ended. Only when we did not close it ourselves.
          this.fail();
          break;
        }
        buffer += decoder.decode(value, { stream: true });
        const chunks = buffer.split("\n\n");
        buffer = chunks.pop() ?? "";
        for (const chunk of chunks) {
          if (!chunk.trim() || chunk.startsWith(":")) continue;
          const id = /^id: (.*)$/m.exec(chunk)?.[1] ?? this.lastEventId;
          const name = /^event: (.*)$/m.exec(chunk)?.[1] ?? "message";
          const data = /^data: (.*)$/m.exec(chunk)?.[1] ?? "";
          if (/^id: /m.test(chunk)) this.lastEventId = id;
          trace(this.id, "frame", `${name} id=${id}`);
          this.emit(name, data, id);
        }
      }
    } catch (cause) {
      trace(this.id, "throw", String(cause));
      this.fail();
    }
  }

  /** Signal a connection failure, exactly once and never after our own `close()`.
   *
   *  The `error` listener in `lib/sse.ts` is overloaded: a server-sent `event: error`
   *  frame arrives as a MessageEvent WITH data, while a connection failure has none.
   *  This is the second kind, so it must carry no data — give it any and the client
   *  would put a dropped connection in the transcript as an engine failure. */
  private fail(): void {
    if (this.readyState === FetchEventSource.CLOSED) return;
    this.readyState = FetchEventSource.CLOSED;
    for (const listener of this.listeners.get("error") ?? []) {
      listener(new MessageEvent("error"));
    }
    this.onerror?.(new Event("error"));
  }
}

export function installEventSource(): void {
  (globalThis as unknown as { EventSource: unknown }).EventSource = FetchEventSource;
}
