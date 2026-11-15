import { expect, type Locator, type Page } from "@playwright/test";
import { existsSync, readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";

/** The bundled seed dataset: the ground truth every card citation is checked against. */
type Row = {
  row_id: string;
  variety: string;
  style: string;
  sweetness: string;
  body: string;
  description: string;
  typical_regions: string[];
};
const SEED = fileURLToPath(
  new URL("../../backend/src/wines_ai/dataset/seed/wines.seed.json", import.meta.url),
);
const seed = JSON.parse(readFileSync(SEED, "utf8")) as { dataset_version: string; rows: Row[] };
export const DATASET_VERSION = seed.dataset_version;
export const ROWS = new Map<string, Row>(seed.rows.map((r) => [r.row_id, r]));

/** Rows added through POST /tastes persist in the backend and can be recommended later,
 *  so they are ground truth too. Re-read on demand: a test may have just added one. */
const INGESTED = fileURLToPath(new URL("../../backend/data/ingested_tastes.jsonl", import.meta.url));
export function allRows(): Map<string, Row> {
  const rows = new Map(ROWS);
  if (existsSync(INGESTED)) {
    for (const line of readFileSync(INGESTED, "utf8").split("\n")) {
      if (!line.trim()) continue;
      const rec = JSON.parse(line);
      const row = (rec.row ?? rec) as Row;
      if (row.row_id) rows.set(row.row_id, row);
    }
  }
  return rows;
}

/** Fresh browser context -> fresh session cookie, so every test starts at the age gate. */
export async function enterApp(page: Page) {
  await page.goto("/");
  await page.getByRole("button", { name: "Yes, I am 21 or older" }).click();
  await expect(page.getByRole("textbox", { name: "Message" })).toBeVisible();
}

/** Waits for the stream to START and then FINISH. Waiting only for "stop is hidden"
 *  passes instantly, before the first frame has arrived. */
/** The server is the source of truth for "the answer finished": the assistant
 *  message is persisted when the turn completes. Counting DOM markers does not work
 *  (only the latest turn keeps its "What this turn did" button) and the stop button
 *  never appears for instant replies such as out-of-scope notices. */
async function assistantCount(page: Page): Promise<number> {
  const cid = page.url().split("/c/")[1];
  if (!cid) return 0;
  const res = await page.request.get(`/api/v1/conversations/${cid}`);
  if (!res.ok()) return 0;
  const detail = (await res.json()) as { messages: { role: string }[] };
  return detail.messages.filter((m) => m.role === "assistant").length;
}

async function act(page: Page, trigger: () => Promise<void>) {
  const before = await assistantCount(page);
  await trigger();
  await expect(page).toHaveURL(/\/c\//);
  await expect
    .poll(() => assistantCount(page), { timeout: 150_000, intervals: [2000, 3000] })
    .toBeGreaterThan(before);
  // ...and the UI has caught up with it.
  await expect(page.getByRole("button", { name: "Stop writing the answer" })).toBeHidden();
  await expect(page.locator("[aria-busy=true]")).toHaveCount(0);
}

export async function send(page: Page, text: string) {
  await act(page, async () => {
    await page.getByRole("textbox", { name: "Message" }).fill(text);
    await page.getByRole("button", { name: "Send" }).click();
  });
}

export async function tapChip(page: Page, label: string | RegExp) {
  await act(page, () => page.getByRole("main").getByRole("button", { name: label }).first().click());
}

export const cards = (page: Page) => page.getByRole("main").getByRole("article");

/** Reads the citation off each card ("w-0009 · seed-0.1"). */
export async function cardCitations(page: Page) {
  const out: { variety: string; rowId: string; version: string; card: Locator }[] = [];
  for (const card of await cards(page).all()) {
    const variety = (await card.getByRole("heading", { level: 3 }).innerText()).trim();
    const m = (await card.innerText()).match(/\b([a-z]+-[\w-]+) · ([\w.-]+)/);
    expect(m, `card "${variety}" has a row citation`).not.toBeNull();
    out.push({ variety, rowId: m![1], version: m![2], card });
  }
  return out;
}

/** Every card must cite a real row, and what it shows must be copied from that row. */
export async function assertCitationsGrounded(page: Page, extraRows: Row[] = []) {
  const known = allRows();
  extraRows.forEach((r) => known.set(r.row_id, r));
  const all = await cardCitations(page);
  // The footer belongs to the LATEST turn: count only its cards.
  const footers = page.getByText(/Served from \d+ dataset rows?/);
  const lastFooter = (await footers.last().innerText()).match(/Served from (\d+)/)![1];
  const cites = all.slice(all.length - Number(lastFooter));
  expect(cites.length).toBeGreaterThan(0);
  for (const c of all) {
    const row = known.get(c.rowId);
    expect(row, `cited row ${c.rowId} exists in the dataset`).toBeTruthy();
    expect(c.variety).toBe(row!.variety);
    await expect(c.card).toContainText(row!.description);
    for (const region of row!.typical_regions) await expect(c.card).toContainText(region);
  }
  // Every card on the page is cited and grounded, not just the latest turn's.
  for (const c of all) expect(known.has(c.rowId), `cited row ${c.rowId} exists`).toBe(true);
  return cites;
}

export function sidebarItem(page: Page, title: string | RegExp) {
  return page.getByRole("navigation", { name: "Conversations" }).getByRole("link", { name: title });
}

export const conversationId = (page: Page) => new URL(page.url()).pathname.split("/c/")[1];

/** Wait for the empty-state screen to mount before typing, or the remount wipes the draft. */
export async function newConversation(page: Page) {
  await page.getByRole("button", { name: "New conversation" }).first().click();
  await expect(page).toHaveURL(/\/$/);
  await expect(page.getByRole("heading", { name: "What do you feel like drinking?" })).toBeVisible();
  await expect(page.getByRole("textbox", { name: "Message" })).toHaveValue("");
}

/** A grounded answer is either cards (recommend) or cited prose (interview suggestion).
 *  The model router legitimately picks either for borderline turns. */
export async function assertGroundedAnswer(page: Page) {
  if ((await cards(page).count()) > 0) return assertCitationsGrounded(page);
  const prose = await page.getByRole("main").innerText();
  const inline = [...prose.matchAll(/\[((?:w|user)-[\w-]+)\]/g)].map((m) => m[1]);
  expect(inline.length, "interview suggestion cites at least one row").toBeGreaterThan(0);
  const rows = allRows();
  for (const id of inline) expect(rows.has(id), `inline citation ${id} is a real row`).toBe(true);
  return [];
}
