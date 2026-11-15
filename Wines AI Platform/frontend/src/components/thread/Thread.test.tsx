/** Render real seeded transcripts.
 *
 * The seeded conversations are produced by the engine, so this renders exactly what a
 * user would see — and it checks the STRUCTURAL framing rules, which are the part of
 * the UI most likely to break silently: an abstention that starts looking like an
 * error, or an out-of-scope reply that starts looking like an answer with results.
 */

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { beforeAll, describe, expect, it } from "vitest";
import { TastePanel } from "@/components/taste/TastePanel";
import { TooltipProvider } from "@/components/ui/Tooltip";
import { qk } from "@/lib/queryKeys";
import { buildThread, lastChipsSeq } from "@/lib/thread";
import * as db from "@/mocks/db";
import { AXES, CONFIDENCE_THRESHOLD, REFINE_CHIPS, styleOptions } from "@/mocks/engine/axes";
import { seedConversations } from "@/mocks/fixtures/conversations";
import { detail } from "@/mocks/view";
import type { ConversationDetail } from "@/types/api";
import { Thread } from "./Thread";

function client() {
  const instance = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  instance.setQueryData(qk.tasteAxes, {
    axes: AXES.map((axis) => ({
      id: axis.id,
      asked: axis.asked,
      question_order: axis.question_order,
      prompt: axis.prompt,
      applies_to: [...axis.applies_to],
      levels: axis.levels,
    })),
    refine_chips: REFINE_CHIPS,
    confidence_threshold: CONFIDENCE_THRESHOLD,
    styles: styleOptions(),
  });
  instance.setQueryData(qk.usage, {
    turns: 3,
    tokens_in: 0,
    tokens_out: 0,
    cost_usd: 0,
    engine: "deterministic",
    cache_hits: 0,
    ceiling_per_session_usd: 0.5,
    degraded: false,
  });
  return instance;
}

function mountThread(conversation: ConversationDetail) {
  const turns = buildThread(conversation, [], null, null);
  return render(
    <QueryClientProvider client={client()}>
      <TooltipProvider>
        <MemoryRouter>
          <Thread
            turns={turns}
            streaming={false}
            cancelled={false}
            reconnecting={false}
            usage={null}
            turnId={null}
            liveChipsSeq={lastChipsSeq(turns)}
            chosenChipId={null}
            pendingSeq={null}
          />
        </MemoryRouter>
      </TooltipProvider>
    </QueryClientProvider>,
  );
}

let conversations: ConversationDetail[] = [];

beforeAll(() => {
  db.reset();
  seedConversations();
  conversations = db.db.conversations.map(detail);
});

function byFirstMessage(needle: string): ConversationDetail {
  const found = conversations.find((conversation) => conversation.title.includes(needle));
  if (!found) throw new Error(`no seeded conversation titled like "${needle}"`);
  return found;
}

describe("a seeded transcript", () => {
  it("renders the completed interview with its recommendation cards", () => {
    const conversation = byFirstMessage("I want a red");
    mountThread(conversation);

    expect(screen.getByText("I want a red")).toBeInTheDocument();
    expect(screen.getByText("How sweet?")).toBeInTheDocument();
    // 3-5 cards, each an <article> labelled by its variety.
    const cards = screen.getAllByRole("article");
    expect(cards.length).toBeGreaterThanOrEqual(3);
    expect(cards.length).toBeLessThanOrEqual(5);
    expect(screen.getByText(/Served from \d+ dataset rows/)).toBeInTheDocument();
  });

  it("frames the no-match answer as an answer, not an error (FR-13)", () => {
    const conversation = byFirstMessage("dessert wine");
    mountThread(conversation);

    expect(screen.getByText("No results, and why")).toBeInTheDocument();
    expect(screen.getByText(/that combination is not covered/)).toBeInTheDocument();
    expect(screen.queryAllByRole("article")).toHaveLength(0);
  });

  it("renders an out-of-scope reply plainly, with no cards and no chips", () => {
    const conversation = byFirstMessage("crisp white");
    mountThread(conversation);
    expect(screen.getByText(/Price is out of scope here/)).toBeInTheDocument();
  });

  it("shows a refine chain's adjustments as prose plus fresh results", () => {
    const conversation = byFirstMessage("something light and red");
    mountThread(conversation);
    expect(screen.getByText(/Adjusting for bolder\./)).toBeInTheDocument();
    expect(screen.getByText(/Adjusting for smoother\./)).toBeInTheDocument();
  });
});

describe("the taste panel", () => {
  it("marks a slot read from free text as inferred, so a wrong guess is catchable", () => {
    const conversation = byFirstMessage("buttery white");
    render(
      <QueryClientProvider client={client()}>
        <TooltipProvider>
          <TastePanel profile={conversation.taste_profile} />
        </TooltipProvider>
      </QueryClientProvider>,
    );

    expect(screen.getByText("White")).toBeInTheDocument();
    expect(screen.getByText("Rounded and buttery")).toBeInTheDocument();
    expect(screen.getAllByText("read from your words").length).toBeGreaterThan(0);
    // Sweetness was never asked in this conversation, so it reads as pending.
    expect(screen.getByText("— not yet asked")).toBeInTheDocument();
    expect(screen.getByText("2 of 3 answered")).toBeInTheDocument();
  });

  it("marks a refined axis as refined", () => {
    const conversation = byFirstMessage("something light and red");
    render(
      <QueryClientProvider client={client()}>
        <TooltipProvider>
          <TastePanel profile={conversation.taste_profile} />
        </TooltipProvider>
      </QueryClientProvider>,
    );
    expect(screen.getAllByText("adjusted after results").length).toBeGreaterThan(0);
  });
});
