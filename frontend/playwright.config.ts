import { defineConfig, devices } from "@playwright/test";
import { API_PORT, WEB_PORT } from "./e2e/env.mjs";

// E2E: real browser -> Vite -> real FastAPI -> real PostgreSQL. Only Google/Stripe/Gmail are faked (demo mode).
// Every run starts from an empty database; tests share it, so they run one at a time (slots are a shared resource).
export default defineConfig({
  testDir: "e2e",
  fullyParallel: false,
  workers: 1,
  retries: process.env.CI ? 1 : 0,
  forbidOnly: !!process.env.CI,
  timeout: 30_000,
  reporter: process.env.CI ? [["list"], ["html", { open: "never" }]] : "list",
  use: {
    baseURL: `http://127.0.0.1:${WEB_PORT}`,
    locale: "fr-FR",
    timezoneId: "Europe/Paris",
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
    // PW_CHANNEL=msedge / chrome uses an installed browser instead of Playwright's Chromium.
    channel: process.env.PW_CHANNEL,
  },
  projects: [
    { name: "desktop", use: { ...devices["Desktop Chrome"], channel: process.env.PW_CHANNEL } },
    { name: "mobile", use: { ...devices["Pixel 7"], channel: process.env.PW_CHANNEL }, grep: /@mobile/ },
  ],
  webServer: [
    {
      command: "node e2e/api-server.mjs",
      url: `http://127.0.0.1:${API_PORT}/api/health`,
      timeout: 120_000,
      reuseExistingServer: false,
      stdout: "ignore",
      stderr: "pipe",
    },
    {
      // The production bundle, served with the same /api proxy as the dev server (preview.proxy = server.proxy).
      command: `npx vite build --logLevel warn && npx vite preview --port ${WEB_PORT} --strictPort --host 127.0.0.1`,
      url: `http://127.0.0.1:${WEB_PORT}`,
      env: { API_PROXY_TARGET: `http://127.0.0.1:${API_PORT}` },
      timeout: 120_000,
      reuseExistingServer: false,
    },
  ],
});
