/** Owner-invoked live Vercel→PC check. Reads the ignored local key; creates/removes only one QA object. */
import { chromium, expect } from "@playwright/test";
import { createHash } from "node:crypto";
import { readFile, mkdir } from "node:fs/promises";
import { resolve } from "node:path";

const [frontend, backend] = process.argv.slice(2);
for (const value of [frontend, backend]) {
  if (
    !value ||
    new URL(value).origin !== value ||
    !value.startsWith("https://")
  )
    throw new Error(
      "Supply your HTTPS frontend and backend origins without paths.",
    );
}
const project = resolve(import.meta.dirname, "../..");
const key = (await readFile(resolve(project, ".env"), "utf8"))
  .split(/\r?\n/)
  .find((line) => line.startsWith("ARTAUD_API_KEY="))
  ?.slice("ARTAUD_API_KEY=".length);
if (!key) throw new Error("Configure the private local owner key first.");
const browser = await chromium.launch({ headless: true });
const context = await browser.newContext({
  viewport: { width: 1440, height: 1000 },
  acceptDownloads: true,
});
await context.addInitScript(() =>
  Object.defineProperty(window, "showSaveFilePicker", {
    value: undefined,
    configurable: true,
  }),
);
const ids = [];
try {
  const page = await context.newPage();
  await page.goto(frontend);
  await page
    .getByRole("button", { name: "Backend connection", exact: true })
    .click();
  await expect(page.getByLabel("Backend HTTPS address")).toHaveValue(backend);
  await page.getByLabel("Owner access key").fill(key);
  await page
    .getByRole("button", { name: "Test connection", exact: true })
    .click();
  await expect(page.getByRole("status")).toContainText("4 workers available");
  await expect(page.getByRole("status")).toContainText(
    "Recovery module connected",
  );
  await page
    .getByRole("button", { name: "Connect backend", exact: true })
    .click();
  await expect(
    page.getByText("Controller connected", { exact: true }),
  ).toBeVisible();
  await expect(page.getByLabel("Search scope")).toBeVisible();
  const payload = Buffer.alloc(1_000_001, 0xa7);
  const name = `public-roundtrip-${Date.now()}.bin`;
  await page
    .locator("input[type=file]")
    .setInputFiles({
      name,
      mimeType: "application/octet-stream",
      buffer: payload,
    });
  const uploaded = page.waitForResponse(
    (response) =>
      response.url() === backend + "/api/v1/objects" &&
      response.request().method() === "POST" &&
      response.status() === 201,
  );
  await page
    .getByRole("button", { name: "Upload 1 file", exact: true })
    .click();
  const object = await (await uploaded).json();
  ids.push(object.object_id);
  expect(object.sha256).toBe(
    createHash("sha256").update(payload).digest("hex"),
  );
  expect(object.num_chunks).toBe(2);
  await expect(page.getByText("Stored", { exact: true })).toBeVisible();
  await page.getByRole("button", { name, exact: true }).click();
  const dialog = page.getByRole("dialog", { name });
  await dialog.getByRole("tab", { name: "Metadata", exact: true }).click();
  await dialog
    .getByLabel("Custom metadata (JSON)")
    .fill('{"check":"public-pc-demo","reviewed":true}');
  await dialog
    .getByRole("button", { name: "Save changes", exact: true })
    .click();
  await expect(
    page.getByText("Metadata updated", { exact: true }),
  ).toBeVisible();
  await dialog.getByRole("tab", { name: "Chunks", exact: true }).click();
  await expect(dialog.getByText("Chunk 1", { exact: true })).toBeVisible();
  const downloading = page.waitForEvent("download");
  await dialog
    .getByRole("button", { name: "Download file", exact: true })
    .click();
  const download = await downloading;
  const downloaded = await readFile(await download.path());
  expect(createHash("sha256").update(downloaded).digest("hex")).toBe(
    object.sha256,
  );
  await page.keyboard.press("Escape");
  await page.getByRole("button", { name: "Cluster", exact: true }).click();
  await expect(
    page.getByRole("button", { name: "Stop worker1", exact: true }),
  ).toBeVisible();
  await page.getByLabel("File to visualize").selectOption({ label: name });
  await expect(
    page.locator(".placement-table").getByText("Healthy", { exact: true }),
  ).toHaveCount(4);
  await mkdir(resolve(project, "frontend/test-results/public"), {
    recursive: true,
  });
  await page.screenshot({
    path: resolve(project, "frontend/test-results/public/cluster-desktop.png"),
    fullPage: true,
  });
  expect(
    await page.evaluate(() =>
      JSON.stringify({ ...localStorage, ...sessionStorage }),
    ),
  ).not.toContain(key);
  await page.getByRole("button", { name: "Files", exact: true }).click();
  await page.getByRole("button", { name, exact: true }).click();
  await page
    .getByRole("dialog")
    .getByRole("button", { name: "Delete file", exact: true })
    .click();
  await page
    .getByRole("alertdialog")
    .getByRole("button", { name: "Delete file", exact: true })
    .click();
  await expect(page.getByRole("button", { name, exact: true })).toHaveCount(0);
  console.log(
    "Public Vercel demo passed: baked-in HTTPS backend, private owner access, four recovered ALIVE workers, real 1,000,001-byte upload/metadata/chunks/hash-matching download/delete, and worker controls. Temporary QA object removed.",
  );
} finally {
  for (const id of ids)
    await context.request
      .delete(`${backend}/api/v1/objects/${encodeURIComponent(id)}`, {
        headers: { "X-Artaud-Key": key, "ngrok-skip-browser-warning": "1" },
      })
      .catch(() => {});
  await context.close();
  await browser.close();
}
