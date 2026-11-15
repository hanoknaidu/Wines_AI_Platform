/** FR-11, both halves.
 *
 * The empty state was always the interesting one. The second case here is the new one:
 * names present but unsigned must not render as though a person checked them, because
 * bare pills say "verified" by omission.
 */

import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { ProducerList } from "./ProducerList";

const CAVEAT = /not yet checked by a person/i;

describe("ProducerList", () => {
  it("explains an empty list instead of leaving a blank section", () => {
    render(<ProducerList producers={[]} reviewStatus="unreviewed" />);
    expect(screen.getByText(/none listed/i)).toBeInTheDocument();
    expect(screen.queryByText(CAVEAT)).not.toBeInTheDocument();
  });

  it("caveats producer names that carry no signature", () => {
    render(
      <ProducerList producers={["Château Léoville-Barton", "Wynns"]} reviewStatus="fixture" />,
    );
    expect(screen.getByText("Château Léoville-Barton")).toBeInTheDocument();
    expect(screen.getByText("Wynns")).toBeInTheDocument();
    expect(screen.getByText(CAVEAT)).toBeInTheDocument();
  });

  it("shows reviewed names plainly, with no caveat", () => {
    render(<ProducerList producers={["Wynns Coonawarra Estate"]} reviewStatus="reviewed" />);
    expect(screen.getByText("Wynns Coonawarra Estate")).toBeInTheDocument();
    expect(screen.queryByText(CAVEAT)).not.toBeInTheDocument();
  });

  it("caveats an unrecognised status rather than trusting it", () => {
    render(<ProducerList producers={["Some Estate"]} reviewStatus="newly-invented" />);
    expect(screen.getByText(CAVEAT)).toBeInTheDocument();
  });
});
