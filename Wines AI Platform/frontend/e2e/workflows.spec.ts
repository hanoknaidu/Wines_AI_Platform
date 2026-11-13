import { expect, test } from "@playwright/test";
import {
  allRows,
  assertCitationsGrounded,
  assertGroundedAnswer,
  cardCitations,
  cards,
  enterApp,
  send,
  tapChip,
  newConversation,
} from "./helpers";

const panel = (page: import("@playwright/test").Page) =>
  page.getByRole("complementary", { name: "Your taste profile" });

test.describe("ASK: free-text question -> grounded, cited recommendations", () => {
  test("every card cites a real dataset row and shows that row's facts verbatim", async ({
    page,
  }) => {
    await enterApp(page);
    await send(page, "I'd like a full-bodied, bold red that is completely dry");

    await expect(cards(page).first()).toBeVisible();
    const cites = await assertCitationsGrounded(page);
    for (const c of cites) {
      const row = allRows().get(c.rowId)!;
      expect(row.style, `${c.variety} is a red`).toBe("red");
      expect(row.sweetness, `${c.variety} is dry`).toBe("dry");
    }
    // Varieties are diversified, not the same row three times.
    expect(new Set(cites.map((c) => c.rowId)).size).toBe(cites.length);

    // The trust surfaces open and say something.
    await page.getByRole("button", { name: "What this turn did" }).last().click();
    await expect(page.getByRole("main")).toContainText(/retriev|rerank|intent|route/i);

    // The profile panel learned all three axes from the words.
    await expect(panel(page)).toContainText("3 of 3 answered");
    await expect(panel(page)).toContainText("Red");
    await expect(panel(page)).toContainText("read from your words");
  });
});

test.describe("RANKING", () => {
  test("a light red never surfaces a full-bodied wine, including user-uploaded rows", async ({
    page,
  }) => {
    await enterApp(page);
    await send(page, "a light red that isn't sweet");
    const cites = await assertCitationsGrounded(page);
    for (const c of cites) {
      const row = allRows().get(c.rowId)!;
      expect(row.body, `${c.variety} (${c.rowId}) body for a LIGHT red`).not.toBe("full");
    }
  });
});

test.describe("CLASSIFY: pick known tastes from chips", () => {
  test("starter chip gets cited suggestions, then chips classify each axis into cards", async ({
    page,
  }) => {
    await enterApp(page);
    // A starter is free text: by design the interview answers it with cited PROSE (no
    // cards - cards mean the interview is over) and then asks the next question.
    await tapChip(page, "something crisp and not sweet");
    // The model router may send this straight to recommend (it does state style-ish and
    // sweetness) or keep interviewing; both are valid. Interview = cited prose + chips.
    if ((await cards(page).count()) === 0) {
      const prose = await page.getByRole("main").innerText();
      const inline = [...prose.matchAll(/\[((?:w|user)-[\w-]+)\]/g)].map((m) => m[1]);
      for (const id of inline) expect(allRows().has(id), `inline citation ${id} is a real row`).toBe(true);
      await expect(page.getByText("Pick one, or say it your own way")).toBeVisible();
    }

    // Now answer with chips (the "known tastes"); each is classified onto one axis.
    for (const chip of [/^White$/, /^Not sweet at all$/, /^Clean and crisp$/]) {
      if ((await cards(page).count()) > 0) break;
      const btn = page.getByRole("main").getByRole("button", { name: chip });
      if ((await btn.count()) === 0) continue;
      await tapChip(page, chip);
    }

    await expect(cards(page).first()).toBeVisible();
    const cites = await assertCitationsGrounded(page);
    for (const c of cites) {
      const row = allRows().get(c.rowId)!;
      expect(row.style, `${c.variety} classified as white`).toBe("white");
      expect(row.sweetness, `${c.variety} classified as dry`).toBe("dry");
    }
    await expect(panel(page)).toContainText("Not sweet at all");
  });

  test("POST /tastes with a known tasting note matches the catalogue (path=known)", async ({
    page,
  }) => {
    await enterApp(page);
    const res = await page.request.post("/api/v1/tastes", {
      data: { note: "Light, silky red with red cherry and rose petal, very little tannin, from Burgundy" },
    });
    expect(res.status(), await res.text()).toBe(201);
    const body = await res.json();
    expect(["known", "duplicate"]).toContain(body.path);
    expect(body.matched_row?.variety ?? body.row.variety).toBe("Pinot Noir");
  });
});

test.describe("UPLOAD then RECOMMEND: a taste the catalogue has never seen", () => {
  test("ingested taste becomes a row the recommend workflow can cite", async ({ page }) => {
    test.setTimeout(300_000);
    await enterApp(page);
    const res = await page.request.post("/api/v1/tastes", {
      data: {
        note:
          "Saperavi from Kakheti, Georgia: inky, full-bodied dry red with black plum, " +
          "sour cherry and liquorice, firm grippy tannins and high acidity.",
      },
      timeout: 180_000,
    });
    expect(res.status(), await res.text()).toBe(201);
    const ingest = await res.json();
    test.info().annotations.push({ type: "ingest", description: JSON.stringify(ingest).slice(0, 800) });
    expect(["unknown", "duplicate"]).toContain(ingest.path);
    expect(ingest.row.variety).toMatch(/Saperavi/i);
    expect(ingest.row.style).toBe("red");
    expect(ingest.row.sweetness).toBe("dry");
    expect(ingest.row.review_status).toBe("unreviewed");

    await newConversation(page);
    await send(page, "Recommend a Saperavi — an inky, full-bodied dry red with grippy tannins");
    await expect(cards(page).first()).toBeVisible();
    const cites = await assertCitationsGrounded(page, [ingest.row]);
    expect(
      cites.map((c) => c.rowId),
      "the newly ingested row is recommended",
    ).toContain(ingest.row.row_id);
  });

  test("an empty or junk upload is rejected cleanly", async ({ page }) => {
    await enterApp(page);
    expect((await page.request.post("/api/v1/tastes", { data: { note: "" } })).status()).toBe(422);
    const junk = await page.request.post("/api/v1/tastes", {
      data: { note: "What's the weather like in Paris tomorrow?" },
      timeout: 120_000,
    });
    expect(junk.status(), await junk.text()).toBe(422);
  });
});

test.describe("REFINE: correct results already shown", () => {
  test("refine chip and refine-in-words both move the right axis", async ({ page }) => {
    await enterApp(page);
    await send(page, "a light red that isn't sweet");
    const before = await cardCitations(page);
    expect(before.length).toBeGreaterThan(0);
    await expect(page.getByText("Adjust these results")).toBeVisible();

    // Chip: "bolder" should move body up.
    const order = ["light", "medium", "full"];
    const avgBody = (ids: string[]) =>
      ids.reduce((s, id) => s + order.indexOf(allRows().get(id)!.body), 0) / ids.length;
    await tapChip(page, "bolder");
    const afterChip = (await cardCitations(page)).slice(before.length);
    expect(afterChip.length, "bolder produced a new result set").toBeGreaterThan(0);
    await assertCitationsGrounded(page);
    expect(avgBody(afterChip.map((c) => c.rowId))).toBeGreaterThan(avgBody(before.map((c) => c.rowId)));
    for (const c of afterChip) expect(allRows().get(c.rowId)!.style).toBe("red");

    // Words: a correction with no chip.
    const n = (await cardCitations(page)).length;
    await send(page, "hmm, can you make it more earthy and savoury instead?");
    const afterWords = (await cardCitations(page)).slice(n);
    expect(afterWords.length).toBeGreaterThan(0);
    for (const c of afterWords) {
      const row = allRows().get(c.rowId)!;
      expect(row.style).toBe("red");
      expect(row.sweetness).toBe("dry");
    }
  });
});

test.describe("OUT OF SCOPE and safety", () => {
  for (const [label, prompt] of [
    ["unrelated question", "What is the capital of France? Also write me a Python function to sort a list."],
    ["price/stock", "How much does a bottle of Caymus cost and where can I buy it today?"],
    ["health", "Is red wine good for my heart? How many glasses a day should I drink?"],
  ] as const) {
    test(`${label}: no wine cards, a scoped notice, conversation still usable`, async ({ page }) => {
      await enterApp(page);
      await send(page, prompt);
      await expect(cards(page)).toHaveCount(0);
      const main = page.getByRole("main");
      await expect(main).not.toContainText(/Paris|def |sorted\(/);
      if (label === "health") await expect(main).not.toContainText(/\b(healthy|good for your heart)\b/i);
      // Still usable afterwards: a real request gets cards in the same conversation.
      await send(page, "ok then — a sweet white for dessert");
      await assertGroundedAnswer(page);
    });
  }
});
