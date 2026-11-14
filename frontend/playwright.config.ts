import { defineConfig, devices } from "@playwright/test";

export default defineConfig({
  workers: 4,
  testDir: "./e2e",
  fullyParallel: true,
  timeout: 30_000,
  use: { baseURL: "http://127.0.0.1:5173", trace: "retain-on-failure" },
  projects: [{ name: "chromium", use: { ...devices["Desktop Chrome"] } }],
  webServer: {
    command: "npm run dev -- --port 5173 --strictPort",
    url: "http://127.0.0.1:5173",
    reuseExistingServer: true,
  },
});
