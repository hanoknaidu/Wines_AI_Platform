import { defineConfig } from "@playwright/test";
import { tmpdir } from "node:os";
import { join } from "node:path";

// Output MUST live outside the Vite root: Vite watches frontend/, and every trace/report
// .html written there triggers a full page reload mid-test (which then trips the
// backend read rate limit and shows "Recommendations unavailable").
const OUT = process.env.E2E_OUT ?? join(tmpdir(), "wines-ai-e2e");
// Real end-to-end: browser -> Vite (VITE_USE_MOCKS=false) -> FastAPI on 8010 -> LLM.
// Start the stack first (see e2e/README section in frontend/README.md); set E2E_BASE_URL to override.
export default defineConfig({
  testDir: "e2e",
  outputDir: join(OUT, "artifacts"),
  timeout: 180_000,
  expect: { timeout: 90_000 },
  workers: 1,
  reporter: [["list"], ["html", { outputFolder: join(OUT, "report"), open: "never" }]],
  use: {
    baseURL: process.env.E2E_BASE_URL ?? "http://localhost:5181",
    screenshot: "only-on-failure",
    trace: "retain-on-failure",
  },
});
