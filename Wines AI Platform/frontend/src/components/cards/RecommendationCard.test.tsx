/** The card, and the prohibitions it has to keep.
 *
 * These assertions are the plan's §3.6 turned into a test, because every one of them
 * is a thing a well-meaning later change would add: a match percentage, a rating, a
 * price, a buy button. Each would quietly turn a fit recommendation into a verdict.
 */

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { TooltipProvider } from "@/components/ui/Tooltip";
import { qk } from "@/lib/queryKeys";
import { AXES, CONFIDENCE_THRESHOLD, REFINE_CHIPS, styleOptions } from "@/mocks/engine/axes";
import * as copy from "@/mocks/engine/copy";
import { ROWS } from "@/mocks/engine";
import type { Card } from "@/types/api";
import { RecommendationCard } from "./RecommendationCard";

function cardFor(rowId: string, profile: Record<string, string>): Card {
  const row = ROWS.find((r) => r.row_id === rowId) as (typeof ROWS)[number];
  return {
    row_id: row.row_id,
    variety: row.variety,
    style: row.style,
    axes: copy.axisReadings(row),
    description: row.description,
    why_it_matches: copy.whyItMatches(row, profile),
    typical_regions: [...row.typical_regions],
    example_producers: [...row.example_producers],
    review_status: row.review_status,
    dataset_version: row.dataset_version,
  };
}

function mount(card: Card, messageId: string | null = "m_1") {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  // The vocabulary arrives over the wire in the app; here it is seeded, so the test
  // exercises the same path without a network.
  client.setQueryData(qk.tasteAxes, {
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
  return render(
    <QueryClientProvider client={client}>
      <TooltipProvider>
        <RecommendationCard card={card} messageId={messageId} />
      </TooltipProvider>
    </QueryClientProvider>,
  );
}

describe("RecommendationCard", () => {
  const card = cardFor("w-0001", { style: "red", sweetness: "dry", body: "full" });

  it("leads with the grape variety and names the style in words, not just a colour", () => {
    mount(card);
    expect(screen.getByRole("heading", { name: "Cabernet Sauvignon" })).toBeInTheDocument();
    expect(screen.getByText("Red")).toBeInTheDocument();
  });

  it("shows the tasting note and the explanation verbatim from the row", () => {
    mount(card);
    expect(screen.getByText(card.description)).toBeInTheDocument();
    expect(screen.getByText(card.why_it_matches)).toBeInTheDocument();
  });

  it("says why no producers are listed instead of hiding the section (FR-11)", () => {
    mount(card);
    expect(
      screen.getByText(/verified by a person during review or left out/i),
    ).toBeInTheDocument();
  });

  it("carries its provenance: row id, dataset version, review status", () => {
    mount(card);
    expect(screen.getByText(/w-0001 · seed-0\.1/)).toBeInTheDocument();
    expect(screen.getByText("not yet reviewed")).toBeInTheDocument();
  });

  it("keeps feedback disabled until the turn has a message id", () => {
    mount(card, null);
    expect(screen.getByRole("button", { name: "This matched what I wanted" })).toBeDisabled();
  });

  it("shows no score, rating, rank, price, vintage or purchase path", () => {
    const { container } = mount(card);
    const text = container.textContent ?? "";
    expect(text).not.toMatch(/\$|€|£/); // no price, ever — it is out of scope
    expect(text).not.toMatch(/\b\d{1,3}\s?(points|pts|%)\b/i); // no critic score, no fit %
    expect(text).not.toMatch(/\b(best|top|rank|#\d|\d\s*\/\s*5|out of 5)\b/i);
    expect(text).not.toMatch(/\b(buy|purchase|add to cart|in stock|shop)\b/i);
    expect(text).not.toMatch(/\b(19|20)\d{2}\b/); // no vintage year
  });

  it("never shows the user the word 'dry'", () => {
    // BRD §3: enforced in the backend's axis table, asserted again at the surface the
    // user actually reads.
    const offDry = cardFor("w-0021", { style: "white", sweetness: "off_dry", oak: "none" });
    const { container } = mount(offDry);
    expect(container.textContent ?? "").not.toMatch(/\bdry\b/i);
  });

  it("renders a low-confidence reading as the hedge the server sent", () => {
    // w-0004's body confidence is 0.68, under the 0.75 threshold.
    const hedged = cardFor("w-0004", { style: "red", sweetness: "dry", body: "medium" });
    mount(hedged);
    expect(screen.getByText("probably medium-bodied")).toBeInTheDocument();
    expect(screen.queryByText("In the middle")).not.toBeInTheDocument();
  });
});
