/** Explicit local demo-control check; reads the ignored owner key without printing it. */
import { chromium, expect } from "@playwright/test";
import { readFile, mkdir } from "node:fs/promises";
import { resolve } from "node:path";

const project = resolve(import.meta.dirname, "../..");
const env = await readFile(resolve(project, ".env"), "utf8");
const key = env
  .split(/\r?\n/)
  .find((line) => line.startsWith("ARTAUD_API_KEY="))
  ?.split("=")
  .slice(1)
  .join("=");
if (!key)
  throw new Error(
    "Configure the local owner key before running this explicit control check.",
  );
const browser = await chromium.launch({ headless: true });
const context = await browser.newContext({
  baseURL: "http://127.0.0.1:8000",
  viewport: { width: 1440, height: 1000 },
});
const page = await context.newPage();
try {
  await page.goto("/");
  await page
    .getByRole("button", { name: "Backend connection", exact: true })
    .click();
  await page.getByLabel("Owner access key").fill(key);
  await page
    .getByRole("button", { name: "Connect backend", exact: true })
    .click();
  await expect(
    page.getByText("Controller connected", { exact: true }),
  ).toBeVisible();
  await page.getByRole("button", { name: "Cluster", exact: true }).click();
  await page.getByRole("button", { name: "Stop worker4", exact: true }).click();
  await page
    .getByRole("dialog")
    .getByRole("button", { name: "Stop worker4", exact: true })
    .click();
  await expect(
    page
      .locator('[data-managed-worker="worker4"]')
      .getByText("Container: exited", { exact: true }),
  ).toBeVisible();
  await page
    .getByRole("button", { name: "Start worker4", exact: true })
    .click();
  await page
    .getByRole("dialog")
    .getByRole("button", { name: "Start worker4", exact: true })
    .click();
  await expect(
    page.getByRole("button", { name: "Stop worker4", exact: true }),
  ).toBeVisible();
  await mkdir(resolve(project, "frontend/test-results/demo"), {
    recursive: true,
  });
  await page.screenshot({
    path: resolve(project, "frontend/test-results/demo/cluster.png"),
    fullPage: true,
  });
  console.log(
    "Real browser: private owner-key connection, confirmed worker4 stop/start and restored running state passed.",
  );
} finally {
  await context.request
    .post("/api/v1/demo/workers/worker4/start", {
      headers: { "X-Artaud-Key": key, "X-Artaud-Admin": "1" },
    })
    .catch(() => {});
  await context.close();
  await browser.close();
}
