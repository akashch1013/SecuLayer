import { defineConfig, devices } from "@playwright/test";

const PORT = 8766;
const live = process.env.E2E_LIVE === "1";
const realRecordings = process.env.E2E_RECORDINGS === "real";

export default defineConfig({
  testDir: "./e2e",
  outputDir: "../artifacts/test-results",
  reporter: [["list"], ["html", { outputFolder: "../artifacts/playwright-report", open: "never" }]],
  // The laptop has 2 cores: one worker, no parallelism, no retries hiding flakes.
  workers: 1,
  fullyParallel: false,
  retries: 0,
  forbidOnly: true,
  timeout: 60_000,
  use: {
    baseURL: `http://127.0.0.1:${PORT}`,
    headless: true,
    trace: "retain-on-failure",
    ...(process.env.E2E_CHROME_CHANNEL ? { channel: process.env.E2E_CHROME_CHANNEL } : {}),
  },
  projects: [
    {
      name: "desktop-1440",
      use: { ...devices["Desktop Chrome"], viewport: { width: 1440, height: 900 } },
    },
    {
      name: "desktop-1280",
      use: { ...devices["Desktop Chrome"], viewport: { width: 1280, height: 720 } },
    },
  ],
  webServer: {
    // An empty environment value overrides a developer's .env key as well as the shell.
    env: live ? {} : { OPENAI_API_KEY: "" },
    // Replay against FakeModel fixture recordings (tests/e2e_fixtures.py), never data/recordings.
    command:
      live || realRecordings
        ? `uv run --frozen seculayer serve --port ${PORT} --mode ${live ? "live" : "replay"}`
        : `uv run --frozen python -m tests.e2e_fixtures artifacts/e2e-recordings && SECULAYER_RECORDINGS_DIR=artifacts/e2e-recordings uv run --frozen seculayer serve --port ${PORT} --mode replay`,
    cwd: "..",
    url: `http://127.0.0.1:${PORT}/api/health`,
    reuseExistingServer: false,
    timeout: 120_000,
    stdout: "ignore",
    stderr: "pipe",
  },
});
