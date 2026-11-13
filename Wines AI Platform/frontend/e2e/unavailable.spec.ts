import { expect, test } from "@playwright/test";

// Regression: a rate-limited or dead backend used to show "The wine dataset is not loaded".
const problem = (status: number, code: string, title: string) => ({
  status,
  contentType: "application/problem+json",
  headers: status === 429 ? { "Retry-After": "30" } : {},
  body: JSON.stringify({ type: "about:blank", title, status, code, detail: title }),
});

test("429 from the backend shows 'too many requests', not 'dataset not loaded'", async ({ page }) => {
  await page.route("**/api/v1/readyz", (r) => r.fulfill(problem(429, "rate_limited", "Too many requests")));
  await page.goto("/");
  await expect(page.getByRole("heading", { name: /Too many requests/ })).toBeVisible();
  await expect(page.getByText(/about 30s/)).toBeVisible();
  await expect(page.getByText(/dataset is not loaded/)).toHaveCount(0);
});

test("unreachable backend shows 'can't reach'", async ({ page }) => {
  await page.route("**/api/v1/readyz", (r) => r.fulfill(problem(502, "http_error", "Bad gateway")));
  await page.goto("/");
  await expect(page.getByRole("heading", { name: "Can't reach Wines AI" })).toBeVisible();
});

test("readyz 503 still shows the dataset screen, and recovers once ready", async ({ page }) => {
  let down = true;
  await page.route("**/api/v1/readyz", (r) =>
    down
      ? r.fulfill({ status: 503, contentType: "application/json",
          body: JSON.stringify({ status: "not_ready", db: "ok", engine: "x", detail: "no dataset" }) })
      : r.fallback(),
  );
  await page.goto("/");
  await expect(page.getByRole("heading", { name: "Recommendations unavailable" })).toBeVisible();
  down = false;
  await page.getByRole("button", { name: "Check now" }).click();
  await expect(page.getByRole("heading", { name: "Are you 21 or older?" })).toBeVisible();
});

test("a rate-limited age check recovers on its own once the limit clears", async ({ page }) => {
  let limited = true;
  await page.route("**/api/v1/conversations?limit=1", (r) =>
    limited ? r.fulfill(problem(429, "rate_limited", "Too many requests")) : r.fallback(),
  );
  await page.goto("/");
  await expect(page.getByRole("heading", { name: /Too many requests/ })).toBeVisible();
  limited = false; // no click: it must recover without the user doing anything
  await expect(page.getByRole("heading", { name: "Are you 21 or older?" })).toBeVisible({ timeout: 10_000 });
});
