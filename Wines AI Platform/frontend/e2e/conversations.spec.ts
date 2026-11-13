import { expect, test } from "@playwright/test";
import { conversationId, enterApp, newConversation, send, sidebarItem } from "./helpers";

test.describe("age gate", () => {
  test("declining blocks the app; confirming lets you in and persists across reload", async ({
    page,
  }) => {
    await page.goto("/");
    await page.getByRole("button", { name: "No, I am under 21" }).click();
    await expect(page.getByRole("heading", { name: "Come back when you are 21." })).toBeVisible();
    await expect(page.getByRole("textbox", { name: "Message" })).toHaveCount(0);

    // The server is the authority: no cookie, no data.
    const blocked = await page.request.get("/api/v1/conversations");
    expect(blocked.status()).toBe(403);

    await page.reload();
    await page.getByRole("button", { name: "Yes, I am 21 or older" }).click();
    await expect(page.getByRole("heading", { name: "What do you feel like drinking?" })).toBeVisible();
    await page.reload();
    await expect(page.getByRole("textbox", { name: "Message" })).toBeVisible();
  });
});

test.describe("conversation lifecycle", () => {
  test("create -> rename -> search -> archive -> delete", async ({ page }) => {
    await enterApp(page);
    await expect(page.getByText("No conversations yet.")).toBeVisible();

    // CREATE: the first message mints the conversation.
    await send(page, "a light red that isn't sweet");
    await expect(page).toHaveURL(/\/c\/c-/);
    const cid = conversationId(page);
    const nav = page.getByRole("navigation", { name: "Conversations" });
    await expect(nav.getByRole("link")).toHaveCount(1);
    const api = await page.request.get(`/api/v1/conversations/${cid}`);
    expect(api.status()).toBe(200);
    const detail = await api.json();
    expect(detail.messages?.length ?? detail.turns?.length).toBeGreaterThanOrEqual(2);

    // RENAME via the row menu; Enter commits.
    const oldTitle = (await nav.getByRole("link").first().innerText()).split("\n")[0].trim();
    await page.getByRole("button", { name: `Actions for ${oldTitle}` }).click();
    await page.getByRole("menuitem", { name: "Rename" }).click();
    const input = page.getByRole("textbox", { name: "Conversation title" });
    await input.fill("Light reds for Friday");
    await input.press("Enter");
    await expect(sidebarItem(page, /Light reds for Friday/)).toBeVisible();
    await expect
      .poll(async () => (await (await page.request.get(`/api/v1/conversations/${cid}`)).json()).title)
      .toBe("Light reds for Friday");
    await page.reload();
    await expect(sidebarItem(page, /Light reds for Friday/)).toBeVisible();

    // RENAME cancelled with Escape keeps the old title.
    await page.getByRole("button", { name: "Actions for Light reds for Friday" }).click();
    await page.getByRole("menuitem", { name: "Rename" }).click();
    await page.getByRole("textbox", { name: "Conversation title" }).fill("Should not stick");
    await page.getByRole("textbox", { name: "Conversation title" }).press("Escape");
    await expect(sidebarItem(page, /Light reds for Friday/)).toBeVisible();

    // A second conversation, so search has something to filter out.
    await newConversation(page);
    await send(page, "something crisp and not sweet");
    await expect(nav.getByRole("link")).toHaveCount(2);

    // SEARCH by title.
    const search = page.getByRole("searchbox", { name: "Search conversations by title" });
    await search.fill("Friday");
    await expect(nav.getByRole("link")).toHaveCount(1);
    await expect(sidebarItem(page, /Light reds for Friday/)).toBeVisible();
    await search.fill("zzz-no-such-title");
    await expect(nav.getByRole("link")).toHaveCount(0);
    await search.fill("");
    await expect(nav.getByRole("link")).toHaveCount(2);

    // ARCHIVE moves it to the Archived view; UNARCHIVE brings it back.
    await page.getByRole("button", { name: "Actions for Light reds for Friday" }).click();
    await page.getByRole("menuitem", { name: "Archive" }).click();
    await expect(sidebarItem(page, /Light reds for Friday/)).toHaveCount(0);
    await page.getByRole("button", { name: "Archived" }).click();
    await expect(sidebarItem(page, /Light reds for Friday/)).toBeVisible();
    await page.getByRole("button", { name: "Actions for Light reds for Friday" }).click();
    await page.getByRole("menuitem", { name: "Unarchive" }).click();
    await expect(sidebarItem(page, /Light reds for Friday/)).toHaveCount(0);
    await page.getByRole("button", { name: /Archived|Back|Conversations/ }).first().click();
    await expect(sidebarItem(page, /Light reds for Friday/)).toBeVisible();

    // DELETE: "Keep it" cancels; "Delete" removes from UI and server.
    await page.getByRole("button", { name: "Actions for Light reds for Friday" }).click();
    await page.getByRole("menuitem", { name: "Delete" }).click();
    const dialog = page.getByRole("dialog", { name: "Delete this conversation?" });
    await expect(dialog).toContainText("Light reds for Friday");
    await dialog.getByRole("button", { name: "Keep it" }).click();
    await expect(sidebarItem(page, /Light reds for Friday/)).toBeVisible();

    await page.getByRole("button", { name: "Actions for Light reds for Friday" }).click();
    await page.getByRole("menuitem", { name: "Delete" }).click();
    await dialog.getByRole("button", { name: "Delete" }).click();
    await expect(sidebarItem(page, /Light reds for Friday/)).toHaveCount(0);
    await expect(nav.getByRole("link")).toHaveCount(1);
    expect((await page.request.get(`/api/v1/conversations/${cid}`)).status()).toBe(404);

    // A stale link to the deleted conversation must not render it.
    await page.goto(`/c/${cid}`);
    await expect(page.getByText("a light red that isn't sweet")).toHaveCount(0);
  });
});
