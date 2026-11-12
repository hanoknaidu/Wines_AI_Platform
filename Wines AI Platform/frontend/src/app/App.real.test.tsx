/** The app test suite, pointed at a real FastAPI.
 *
 * Skipped unless WA_REAL_BACKEND=1, so the default suite stays offline and fast:
 *
 *   cd ../backend && .venv/bin/python -m uvicorn wines_ai.main:app --port 8001
 *   WA_REAL_BACKEND=1 npx vitest run src/app/App.real.test.tsx
 */

import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterAll, afterEach, beforeAll, beforeEach, describe, expect, it } from "vitest";
import App from "@/App";
import { installEventSource } from "@/test/eventSource";
import { REVIEW_BADGE, isSigned, reviewStatusOf } from "@/lib/review";
import { realServer, resetJar } from "@/test/realBackend";

const live = process.env.WA_REAL_BACKEND === "1";
const ORIGIN = process.env.WA_BACKEND ?? "http://127.0.0.1:8001";

/** Whatever artifact the server is actually serving.
 *
 * These assertions used to hardcode `seed-0.1`, 45 rows and "not yet reviewed", which
 * was correct for the seed and wrong for every other artifact - running against
 * `wines.demo.json` failed on the version string, the review badge and the empty
 * producer copy, none of which is a real defect. The server already reports all of it,
 * so ask rather than assume.
 */
interface Artifact {
  version: string;
  rows: number;
  /** The status most rows carry, mapped through the client's own vocabulary. */
  badge: string;
  signed: boolean;
}
let artifact: Artifact;

/** `demo-0.1` in a RegExp would otherwise match `demo-0X1`. */
const rx = (literal: string) => literal.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");

/** The real age cookie is httpOnly, signed and long-lived, so a second visit in the
 *  same session legitimately skips the gate — which is the product's own behaviour.
 *  Only the first test asserts the gate; the rest pass through whichever way it goes. */
async function enter(user: ReturnType<typeof userEvent.setup>): Promise<void> {
  const gate = await Promise.race([
    screen
      .findByRole("button", { name: /Yes, I am 21 or older/ }, { timeout: 15000 })
      .catch(() => null),
    screen
      .findByRole("textbox", { name: "Message" }, { timeout: 15000 })
      .then(() => null)
      .catch(() => null),
  ]);
  if (gate) await user.click(gate);
  await screen.findByRole("textbox", { name: "Message" }, { timeout: 15000 });
}

/** Click a chip only once it is actually clickable.
 *
 * The bug this exists for: `ChipDock` is `disabled={stream.isStreaming || send.isPending}`
 * (ConversationScreen.tsx), and the `chips` frame arrives BEFORE `usage` and `done` — so
 * there is a real window in which the chip is rendered and disabled. `findByRole` resolves
 * the moment it exists, inside that window, and `userEvent.click` on a disabled button
 * silently does nothing: no request is sent, and the test then waits out its full timeout
 * on content that was never going to arrive. That is a 45-second green-looking stall.
 *
 * Against the mocks every frame lands in one tick so the window is never observed. Against
 * a real server it is, intermittently — this failed 3 runs in 6.
 *
 * Re-queries each attempt rather than holding the node, so a re-render cannot hand back a
 * detached element either.
 */
async function clickChip(
  user: ReturnType<typeof userEvent.setup>,
  name: string,
  timeout = 25000,
): Promise<void> {
  await waitFor(
    () => {
      const chip = screen.getByRole("button", { name });
      // The assertion is the wait condition: a disabled chip means the turn has not
      // finished, so keep waiting instead of clicking into the void.
      expect(chip).toBeEnabled();
    },
    { timeout },
  );
  await user.click(screen.getByRole("button", { name }));
}

describe.skipIf(!live)("against a real FastAPI backend", () => {
  beforeAll(async () => {
    installEventSource();
    realServer.listen({ onUnhandledRequest: "bypass" });

    // Absolute URL, so MSW's `http.all("*")` passthrough handles it rather than the
    // `/api/*` forwarder - this runs before any component exists.
    const response = await fetch(`${ORIGIN}/api/v1/meta/dataset-version`);
    const meta = (await response.json()) as {
      dataset_version: string;
      row_count: number;
      review_status_counts: Record<string, number>;
    };
    const counts = meta.review_status_counts;
    const dominant = Object.entries(counts).sort((a, b) => b[1] - a[1])[0][0];
    artifact = {
      version: meta.dataset_version,
      rows: meta.row_count,
      badge: REVIEW_BADGE[reviewStatusOf(dominant)].label,
      signed: isSigned(dominant),
    };
  });
  afterAll(() => realServer.close());
  beforeEach(() => {
    resetJar();
    window.history.pushState({}, "", "/");
  });
  // RTL unmounts the tree after each test, which closes the app's own stream — but a
  // source the app had already abandoned (a reconnect, say) would otherwise stay open
  // against the real server for the rest of the file.
  afterEach(() => {
    for (const source of openSources()) source.close();
    (globalThis as unknown as { __waSources?: unknown[] }).__waSources = [];
  });

  it("gates on age against the real cookie, then shows the real dataset", async () => {
    const user = userEvent.setup();
    render(<App />);

    // The real age cookie is httpOnly and signed: the client cannot read it, it can
    // only ask — and this is the asking.
    expect(await screen.findByText("Are you 21 or older?")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: /Yes, I am 21 or older/ }));

    expect(await screen.findByRole("button", { name: /New conversation/ })).toBeInTheDocument();
    // Served from the real frozen artifact, not from a fixture.
    expect(
      await screen.findByText(new RegExp(`${artifact.rows} rows · ${rx(artifact.version)}`)),
    ).toBeInTheDocument();
  }, 30000);

  it("runs a real interview and streams real recommendations", async () => {
    const user = userEvent.setup();
    render(<App />);
    await enter(user);

    const composer = await screen.findByRole("textbox", { name: "Message" });
    await user.type(composer, "a bold red, nothing too sweet");
    await user.click(screen.getByRole("button", { name: "Send" }));

    await waitFor(() => expect(window.location.pathname).toMatch(/^\/c\//), { timeout: 15000 });
    await waitFor(
      () => expect(screen.getAllByRole("article").length).toBeGreaterThanOrEqual(3),
      { timeout: 20000 },
    );

    // Provenance traces to a row of the artifact actually being served.
    expect(
      screen.getAllByText(new RegExp(`w-\\d{4} · ${rx(artifact.version)}`)).length,
    ).toBeGreaterThanOrEqual(3);
    expect(screen.getAllByText(artifact.badge).length).toBeGreaterThan(0);

    // FR-11, whichever way the artifact falls: the producer section is never blank,
    // and names that carry no signature never render as though they were checked.
    const empty = screen.queryAllByText(/verified by a person during review or left out/);
    const caveat = screen.queryAllByText(/not yet checked by a person/);
    const pills = screen.queryAllByText(/^Producers to look for$/);
    expect(pills.length).toBeGreaterThan(0);
    if (empty.length === 0) {
      // Names are present, so an unsigned artifact must be saying so.
      expect(artifact.signed || caveat.length > 0).toBe(true);
    }

    // The taste panel read all three slots out of one sentence.
    expect(await screen.findByText("3 of 3 answered")).toBeInTheDocument();
    expect(screen.getAllByText("read from your words").length).toBeGreaterThan(0);

    // And the live refine row is docked and ready.
    expect(screen.getByText("Adjust these results")).toBeInTheDocument();
  }, 60000);

  it("abstains honestly on a real no-match (FR-13)", async () => {
    const user = userEvent.setup();
    render(<App />);
    await enter(user);

    const composer = await screen.findByRole("textbox", { name: "Message" });
    await user.type(composer, "I'd like a dessert wine");
    await user.click(screen.getByRole("button", { name: "Send" }));

    // The interview chips come from the server's own vocabulary.
    await clickChip(user, "Not sweet at all");

    expect(
      await screen.findByText("No results, and why", {}, { timeout: 45000 }),
    ).toBeInTheDocument();
    expect(screen.queryAllByRole("article")).toHaveLength(0);
    expect(screen.getByRole("button", { name: "sweeter" })).toBeInTheDocument();
  }, 90000);

  it("re-ranks on a real refine without re-interviewing (FR-8)", async () => {
    const user = userEvent.setup();
    render(<App />);
    await enter(user);

    const composer = await screen.findByRole("textbox", { name: "Message" });
    await user.type(composer, "something light and red, not sweet");
    await user.click(screen.getByRole("button", { name: "Send" }));

    await waitFor(
      () => expect(screen.getAllByRole("article").length).toBeGreaterThanOrEqual(3),
      { timeout: 25000 },
    );
    const before = screen
      .getAllByRole("article")
      .map((card) => card.getAttribute("aria-label"));

    await clickChip(user, "bolder");
    await waitFor(() => expect(screen.getByText(/Adjusting for bolder/)).toBeInTheDocument(), {
      timeout: 25000,
    });
    await waitFor(
      () => {
        const after = screen
          .getAllByRole("article")
          .map((card) => card.getAttribute("aria-label"));
        expect(after.join()).not.toBe(before.join());
      },
      { timeout: 25000 },
    );
    expect(screen.getByText("Adjust these results")).toBeInTheDocument();
  }, 90000);

  it("survives the stream dropping mid-answer and resumes exactly once", async () => {
    const user = userEvent.setup();
    render(<App />);
    await enter(user);

    const composer = await screen.findByRole("textbox", { name: "Message" });
    await user.type(composer, "a crisp white, nothing sweet");
    await user.click(screen.getByRole("button", { name: "Send" }));

    // Kill every open EventSource the moment text starts arriving, mid-sentence.
    await screen.findByText(/Here are/, {}, { timeout: 25000 });
    for (const source of openSources()) source.close();

    await waitFor(
      () => expect(screen.getAllByRole("article").length).toBeGreaterThanOrEqual(3),
      { timeout: 30000 },
    );
    // The lead-in survived whole, exactly once — not doubled, not truncated.
    expect(screen.getAllByText(/Here are \d grape varieties worth looking for/)).toHaveLength(
      1,
    );
  }, 90000);
});

/** The shim records its instances so a test can sever the connection. */
function openSources(): { close: () => void }[] {
  const registry = (globalThis as unknown as { __waSources?: { close: () => void }[] })
    .__waSources;
  return registry ?? [];
}
