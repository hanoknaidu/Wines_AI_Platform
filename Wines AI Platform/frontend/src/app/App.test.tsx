/** The whole app, driven the way a person drives it.
 *
 * Age gate -> shell -> a seeded conversation -> send a turn -> watch it stream -> get
 * cards. Everything below the component boundary is real: the router, the query cache,
 * the fetch client, the MSW handlers, the engine, the SSE framing and the reducer. The
 * only stand-in is EventSource, which jsdom does not implement.
 */

import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterAll, afterEach, beforeAll, beforeEach, describe, expect, it } from "vitest";
import App from "@/App";
import * as db from "@/mocks/db";
import { seedConversations } from "@/mocks/fixtures/conversations";
import { installEventSource } from "@/test/eventSource";
import { server } from "@/test/server";

beforeAll(() => {
  installEventSource();
  server.listen({ onUnhandledRequest: "error" });
});
afterAll(() => server.close());
afterEach(() => server.resetHandlers());

beforeEach(() => {
  window.history.pushState({}, "", "/");
  db.reset();
  seedConversations();
});

describe("Wines AI, end to end against mocks", () => {
  it("gates on age, then lists the seeded conversations", async () => {
    const user = userEvent.setup();
    render(<App />);

    // FR-1: nothing is reachable until this is answered.
    expect(await screen.findByText("Are you 21 or older?")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: /Yes, I am 21 or older/ }));

    expect(await screen.findByRole("button", { name: /New conversation/ })).toBeInTheDocument();
    const nav = await screen.findByRole("navigation", { name: "Conversations" });
    expect(await within(nav).findByText("I want a red")).toBeInTheDocument();
    expect(within(nav).getByText("Today")).toBeInTheDocument();
    // The dataset says what it is, unprompted.
    expect(await screen.findByText(/45 rows · seed-0\.1/)).toBeInTheDocument();
  });

  it("will not let someone under 21 through", async () => {
    const user = userEvent.setup();
    render(<App />);
    await user.click(await screen.findByRole("button", { name: /No, I am under 21/ }));
    expect(screen.getByText(/Come back when you are 21/)).toBeInTheDocument();
    expect(screen.queryByRole("navigation", { name: "Conversations" })).not.toBeInTheDocument();
  });

  it("opens a transcript and shows its cards with provenance", async () => {
    const user = userEvent.setup();
    render(<App />);
    await user.click(await screen.findByRole("button", { name: /Yes, I am 21 or older/ }));

    const nav = await screen.findByRole("navigation", { name: "Conversations" });
    await user.click(await within(nav).findByText("I want a red"));

    await waitFor(() =>
      expect(screen.getAllByRole("article").length).toBeGreaterThanOrEqual(3),
    );
    // One provenance line per card: every claim on screen names the row behind it.
    expect(screen.getAllByText(/w-\d{4} · seed-0\.1/).length).toBe(
      screen.getAllByRole("article").length,
    );
    expect(screen.getAllByText("not yet reviewed").length).toBeGreaterThan(0);
    // The taste panel shows what the answers were built on — all three slots here.
    expect(screen.getByText("3 of 3 answered")).toBeInTheDocument();
  });

  it("runs a whole interview from a typed opener and streams recommendations", async () => {
    const user = userEvent.setup();
    render(<App />);
    await user.click(await screen.findByRole("button", { name: /Yes, I am 21 or older/ }));

    const composer = await screen.findByRole("textbox", { name: "Message" });
    await user.type(composer, "a bold red, nothing too sweet");
    await user.click(screen.getByRole("button", { name: "Send" }));

    // The conversation is created on the first send, not on arrival at the page.
    await waitFor(() => expect(window.location.pathname).toMatch(/^\/c\/c_/), {
      timeout: 5000,
    });

    // Three slots came out of one sentence, so it recommends rather than interviewing.
    await waitFor(
      () => expect(screen.getAllByRole("article").length).toBeGreaterThanOrEqual(3),
      { timeout: 8000 },
    );
    expect(
      screen.getByText(/Here are \d grape varieties worth looking for/),
    ).toBeInTheDocument();
    // The refine row is live and docked above the composer.
    expect(screen.getByText("Adjust these results")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "bolder" })).toBeInTheDocument();
  }, 20000);

  it("re-ranks on a refine chip without re-interviewing", async () => {
    const user = userEvent.setup();
    render(<App />);
    await user.click(await screen.findByRole("button", { name: /Yes, I am 21 or older/ }));

    const nav = await screen.findByRole("navigation", { name: "Conversations" });
    await user.click(await within(nav).findByText("I want a red"));
    await waitFor(() =>
      expect(screen.getAllByRole("article").length).toBeGreaterThanOrEqual(3),
    );

    const before = screen
      .getAllByRole("article")
      .map((card) => card.getAttribute("aria-label"));
    await user.click(await screen.findByRole("button", { name: "lighter" }));

    await waitFor(() => expect(screen.getByText(/Adjusting for lighter/)).toBeInTheDocument(), {
      timeout: 8000,
    });
    await waitFor(
      () => {
        const after = screen
          .getAllByRole("article")
          .map((card) => card.getAttribute("aria-label"));
        expect(after.join()).not.toBe(before.join());
      },
      { timeout: 8000 },
    );
    // No NEW question was asked: refine never re-interviews (FR-8). The transcript
    // still holds the one question from the original interview, and only that one.
    expect(screen.getAllByText("How sweet?")).toHaveLength(1);
    expect(screen.getByText("Adjust these results")).toBeInTheDocument();
  }, 20000);

  it("abstains honestly instead of serving sweet wine to someone who asked for none", async () => {
    const user = userEvent.setup();
    render(<App />);
    await user.click(await screen.findByRole("button", { name: /Yes, I am 21 or older/ }));

    const nav = await screen.findByRole("navigation", { name: "Conversations" });
    await user.click(await within(nav).findByText(/dessert wine/));

    expect(await screen.findByText("No results, and why")).toBeInTheDocument();
    expect(screen.queryAllByRole("article")).toHaveLength(0);
  });

  it("renames a conversation from the sidebar", async () => {
    const user = userEvent.setup();
    render(<App />);
    await user.click(await screen.findByRole("button", { name: /Yes, I am 21 or older/ }));

    const nav = await screen.findByRole("navigation", { name: "Conversations" });
    await within(nav).findByText("I want a red");
    await user.click(screen.getByRole("button", { name: "Actions for I want a red" }));
    await user.click(await screen.findByRole("menuitem", { name: /Rename/ }));

    const input = screen.getByRole("textbox", { name: "Conversation title" });
    await user.clear(input);
    await user.type(input, "Weeknight reds{Enter}");

    expect(await within(nav).findByText("Weeknight reds")).toBeInTheDocument();
  }, 20000);
});
