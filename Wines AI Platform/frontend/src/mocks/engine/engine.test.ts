import { describe, expect, it } from "vitest";
import artifact from "../fixtures/wines.seed.json";
import { AXES, STYLES } from "./axes";
import { ROWS, runTurn } from "./index";
import { readAny } from "./interview";
import * as copy from "./copy";
import type { DatasetArtifact, EngineEvent, Profile } from "./types";

const cards = (events: EngineEvent[]) => events.filter((e) => e.t === "card");
const text = (events: EngineEvent[]) =>
  events
    .filter((e): e is Extract<EngineEvent, { t: "token" }> => e.t === "token")
    .map((e) => e.text)
    .join("");

describe("the seed artifact", () => {
  // A probe, not a formality: a fixture edit that invents data has to fail loudly.
  const dataset = artifact as DatasetArtifact;

  it("is the backend's artifact, unedited", () => {
    expect(dataset.dataset_version).toBe("seed-0.1");
    expect(dataset.rows).toHaveLength(45);
    expect(new Set(dataset.rows.map((r) => r.style))).toEqual(new Set(STYLES));
  });

  it("names no producer and claims no review", () => {
    // FR-11 and §8: producer names are the one field a model confabulates, and a
    // plausible fake would look like real data the moment it rendered.
    expect(dataset.rows.every((r) => r.example_producers.length === 0)).toBe(true);
    expect(dataset.rows.every((r) => r.review_status === "unreviewed")).toBe(true);
  });

  it("carries at least one axis under the hedge threshold, so the hedge is reachable", () => {
    const hedged = dataset.rows.filter((r) =>
      Object.entries(r.confidence).some(([axis, value]) => value < 0.75 && axis !== "tannin"),
    );
    expect(hedged.length).toBeGreaterThan(0);
  });
});

describe("the vocabulary table", () => {
  it("never shows the user the word 'dry'", () => {
    // BRD §3: the most misused word in consumer wine language. A unit test asserts it
    // server-side too; this is the client-facing half of the same rule.
    const labels = AXES.flatMap((axis) => [
      axis.prompt ?? "",
      ...axis.levels.flatMap((level) => [level.label, level.hedged_label]),
    ]);
    for (const label of labels) {
      expect(label.toLowerCase()).not.toMatch(/\bdry\b/);
    }
  });
});

describe("reading free text", () => {
  it("reads 'nothing too sweet' as not sweet, not as sweet", () => {
    // The failure this guards against serves a dessert wine to someone who just said
    // they do not want one.
    expect(readAny("a bold red, nothing too sweet")).toMatchObject({
      style: "red",
      sweetness: "dry",
      body: "full",
    });
  });

  it("reads an explicit hint of sweetness as off-dry despite the negation cue", () => {
    expect(readAny("a white with just a hint of sweetness, not too much")).toMatchObject({
      sweetness: "off_dry",
    });
  });
});

describe("the engine", () => {
  it("asks rather than guesses when a slot is unfilled", () => {
    const events = runTurn({ utterance: "I want a red", profile: {}, previous_row_ids: [] });
    expect(cards(events)).toHaveLength(0);
    const chips = events.find((e) => e.t === "chips");
    expect(chips).toMatchObject({ chips: { kind: "interview", axis: "sweetness" } });
  });

  it("returns 3-5 rows spanning at least two varieties once the slots are filled", () => {
    const events = runTurn({
      utterance: "",
      profile: { style: "red", sweetness: "dry", body: "full" },
      previous_row_ids: [],
    });
    const found = cards(events);
    expect(found.length).toBeGreaterThanOrEqual(3);
    expect(found.length).toBeLessThanOrEqual(5);
    const varieties = new Set(found.map((c) => c.card.variety.split("(")[0].trim()));
    expect(varieties.size).toBeGreaterThanOrEqual(2);
  });

  it("abstains instead of serving sweet wine to someone who asked for none (FR-13)", () => {
    const events = runTurn({
      utterance: "",
      profile: { style: "dessert", sweetness: "dry" },
      previous_row_ids: [],
    });
    expect(cards(events)).toHaveLength(0);
    expect(text(events)).toContain("that combination is not covered");
    // The refine chips still come with it: an abstention is an answer, not a dead end.
    expect(events.some((e) => e.t === "chips")).toBe(true);
  });

  it("moves exactly one axis on a refine and re-ranks", () => {
    const before = runTurn({
      utterance: "",
      profile: { style: "red", sweetness: "dry", body: "light" },
      previous_row_ids: [],
    });
    const after = runTurn({
      utterance: "bolder",
      selected_chip_id: "bolder",
      profile: { style: "red", sweetness: "dry", body: "light" },
      previous_row_ids: cards(before).map((c) => c.row_id),
    });
    const patch = after.find((e) => e.t === "profile");
    expect(patch).toMatchObject({ values: { body: "medium" }, confidence: {} });
    expect(cards(after).map((c) => c.row_id)).not.toEqual(cards(before).map((c) => c.row_id));
  });

  it("says so when a refine cannot move any further", () => {
    const events = runTurn({
      utterance: "bolder",
      selected_chip_id: "bolder",
      profile: { style: "red", sweetness: "dry", body: "full" },
      previous_row_ids: ["w-0001"],
    });
    expect(text(events)).toContain("I cannot go further that way");
    expect(cards(events)).toHaveLength(0);
  });

  it("refuses price without retrieval", () => {
    const events = runTurn({
      utterance: "how much does it cost?",
      profile: { style: "red", sweetness: "dry", body: "full" },
      previous_row_ids: [],
    });
    expect(cards(events)).toHaveLength(0);
    expect(text(events)).toContain("Price is out of scope");
  });

  it("serves every field from a dataset row, never from a template of its own", () => {
    const events = runTurn({
      utterance: "",
      profile: { style: "white", sweetness: "dry", oak: "none" },
      previous_row_ids: [],
    });
    for (const card of cards(events)) {
      const row = ROWS.find((r) => r.row_id === card.row_id);
      expect(row).toBeDefined();
      expect(card.card.description).toBe(row?.description);
      expect(card.card.typical_regions).toEqual(row?.typical_regions);
      expect(card.card.dataset_version).toBe(row?.dataset_version);
    }
  });
});

describe("leadIn", () => {
  // The mock mirrors the backend's copy on purpose, so it mirrors the backend's
  // regression test too: this bug shipped as "worth looking for for not sweet at all".
  const PROFILES: Profile[] = [
    {},
    { sweetness: "dry" },
    { sweetness: "dry", body: "full" },
    { sweetness: "dry", body: "full", oak: "pronounced" },
    { body: "light", oak: "none" },
  ];

  it("never doubles a word", () => {
    for (const profile of PROFILES) {
      const text = copy.leadIn(5, profile);
      expect(text, `profile ${JSON.stringify(profile)}`).not.toMatch(/\b(\w+)\s+\1\b/);
    }
  });

  it("separates labels that contain their own \"and\"", () => {
    expect(copy.leadIn(5, { sweetness: "dry", body: "full", oak: "pronounced" })).toBe(
      "Here are 5 grape varieties worth looking for: not sweet at all, rich and bold, rounded and buttery.",
    );
  });

  it("drops the list entirely on an empty profile", () => {
    expect(copy.leadIn(5, {})).toBe("Here are 5 grape varieties worth looking for.");
  });
});
