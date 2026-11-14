/** Explicit local smoke check: creates/removes only two uniquely named empty QA objects. */
import { chromium, expect } from "@playwright/test";
import { readFile, mkdir } from "node:fs/promises";
import { resolve } from "node:path";

const project = resolve(import.meta.dirname, "../..");
const env = await readFile(resolve(project, ".env"), "utf8");
const key = env
  .split(/\r?\n/)
  .find((line) => line.startsWith("ARTAUD_API_KEY="))
  ?.slice("ARTAUD_API_KEY=".length);
if (!key) throw new Error("Configure the local owner key first.");
const browser = await chromium.launch({ headless: true });
const context = await browser.newContext({
  baseURL: "http://127.0.0.1:8000",
  viewport: { width: 1440, height: 1000 },
});
const created = [];
const run = "qa-file-tools-" + Date.now();
const headers = { "X-Artaud-Key": key };
try {
  for (const suffix of ["a", "b"]) {
    const result = await context.request.post("/api/v1/objects", {
      headers,
      multipart: {
        file: {
          name: `${run}-${suffix}.txt`,
          mimeType: "text/plain",
          buffer: Buffer.alloc(0),
        },
        metadata: JSON.stringify({
          qa_run: run,
          note: `He said "hello" ${run}`,
          path: "C:\\reports\\demo",
        }),
      },
    });
    expect(result.status()).toBe(201);
    const file = await result.json();
    created.push(file.object_id);
    expect(file.size).toBe(0);
  }
  const page = await context.newPage();
  await page.goto("/");
  await page
    .getByRole("button", { name: "Backend connection", exact: true })
    .click();
  await page.getByLabel("Owner access key").fill(key);
  await page
    .getByRole("button", { name: "Test connection", exact: true })
    .click();
  await expect(page.getByRole("status")).toContainText("API access accepted");
  await page
    .getByRole("button", { name: "Connect backend", exact: true })
    .click();
  await page.getByLabel("Search scope").selectOption("metadata");
  await page
    .getByRole("searchbox", { name: "Search files" })
    .fill(`He said "hello" ${run}`);
  await expect(page.locator(".object-table tbody tr")).toHaveCount(2);
  const download = page.waitForEvent("download");
  await page
    .getByRole("button", { name: "Export filtered CSV", exact: true })
    .click();
  const csv = await readFile(await (await download).path(), "utf8");
  expect(csv).toContain(`${run}-a.txt`);
  expect(csv).toContain(`${run}-b.txt`);
  await page
    .getByRole("checkbox", { name: "Select this page", exact: true })
    .check();
  await page
    .getByRole("button", { name: "Delete selected", exact: true })
    .click();
  const dialog = page.getByRole("alertdialog", {
    name: "Delete selected files",
  });
  await dialog.getByLabel("Type DELETE to confirm").fill("DELETE");
  await dialog
    .getByRole("button", { name: "Delete 2 files", exact: true })
    .click();
  await expect(dialog.getByText("Removed", { exact: true })).toHaveCount(2);
  await dialog.getByRole("button", { name: "Done", exact: true }).click();
  await expect(
    page.getByText("No matching files", { exact: true }),
  ).toBeVisible();
  await mkdir(resolve(project, "frontend/test-results/connected"), {
    recursive: true,
  });
  await page.screenshot({
    path: resolve(
      project,
      "frontend/test-results/connected/local-file-tools.png",
    ),
    fullPage: true,
  });
  console.log(
    "Real local controller: connection probe, literal metadata search, CSV export and confirmed two-file deletion passed. Empty QA objects only; no worker admission or recovery claim.",
  );
} finally {
  for (const id of created)
    await context.request
      .delete(`/api/v1/objects/${encodeURIComponent(id)}`, { headers })
      .catch(() => {});
  await context.close();
  await browser.close();
}
