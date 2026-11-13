/** Forward every /api call to a real FastAPI instead of the mock.
 *
 * This is how the claim "VITE_USE_MOCKS=false changes nothing the user can see" gets
 * tested rather than asserted: the same app tests run against the real server, through
 * the same components, the same reducer and the same EventSource.
 *
 * It keeps its own cookie jar because node's fetch has none, and the session and
 * age-gate cookies are httpOnly and load-bearing.
 */

import { http, HttpResponse, passthrough } from "msw";
import { setupServer } from "msw/node";

const ORIGIN = process.env.WA_BACKEND ?? "http://127.0.0.1:8001";
const jar = new Map<string, string>();

function cookieHeader(): string {
  return [...jar.entries()].map(([name, value]) => `${name}=${value}`).join("; ");
}

function remember(response: Response): void {
  // getSetCookie() keeps multiple Set-Cookie headers separate; a plain get() would
  // join them into one unsplittable string.
  for (const line of response.headers.getSetCookie?.() ?? []) {
    const [pair] = line.split(";");
    const index = pair.indexOf("=");
    if (index > 0) jar.set(pair.slice(0, index).trim(), pair.slice(index + 1).trim());
  }
}

const DEBUG = process.env.WA_SSE_DEBUG === "1";
const t0 = Date.now();
let reqSeq = 0;

function rtrace(id: number, event: string, detail = ""): void {
  if (!DEBUG) return;
  // eslint-disable-next-line no-console
  console.log(`[fwd +${String(Date.now() - t0).padStart(6)}ms] #${id} ${event.padEnd(12)} ${detail}`);
}

async function forward(request: Request): Promise<Response> {
  const url = new URL(request.url);
  const headers = new Headers(request.headers);
  headers.delete("host");
  if (jar.size) headers.set("cookie", cookieHeader());

  const id = ++reqSeq;
  rtrace(id, "start", `${request.method} ${url.pathname}`);
  const response = await fetch(`${ORIGIN}${url.pathname}${url.search}`, {
    method: request.method,
    headers,
    body:
      request.method === "GET" || request.method === "HEAD" ? undefined : await request.text(),
    redirect: "manual",
  });
  remember(response);
  rtrace(
    id,
    "headers",
    `${response.status} len=${response.headers.get("content-length")} ` +
      `te=${response.headers.get("transfer-encoding")} ct=${response.headers.get("content-type")}`,
  );

  // The SSE response is handed back as a live stream, not buffered — and cancelling
  // it downstream must cancel it UPSTREAM too. Without this the connection to the
  // real server is never released, node's per-origin pool fills with abandoned
  // streams, and a later request simply queues until the test times out. (An
  // AbortSignal cannot do this job here: under jsdom the signal belongs to the wrong
  // realm and node's fetch rejects it.)
  const upstream = response.body?.getReader() ?? null;
  const body =
    upstream === null
      ? null
      : new ReadableStream<Uint8Array>({
          async pull(controller) {
            const { value, done } = await upstream.read();
            if (done) {
              rtrace(id, "body-done");
              controller.close();
              return;
            }
            rtrace(id, "body-chunk", `${value.byteLength}B`);
            controller.enqueue(value);
          },
          cancel(reason) {
            rtrace(id, "body-cancel", String(reason));
            void upstream.cancel(reason).catch(() => {});
          },
        });

  return new HttpResponse(body, {
    status: response.status,
    headers: response.headers,
  });
}

export const realServer = setupServer(
  http.all("/api/*", ({ request }) => forward(request)),
  http.all("*", () => passthrough()),
);

export function resetJar(): void {
  jar.clear();
}
