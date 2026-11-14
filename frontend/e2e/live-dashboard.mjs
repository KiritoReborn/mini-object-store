/** Real backend/worker browser check. No API interception and no demo data switch. */
import { chromium, expect } from "@playwright/test";
import { createHash } from "node:crypto";
import { mkdir, readFile, unlink } from "node:fs/promises";
import { resolve } from "node:path";

const [baseURL, stage] = process.argv.slice(2);
if (!baseURL || !["connecting", "workflow"].includes(stage))
  throw new Error("Supply the disposable controller URL and a check stage.");
const artifacts = resolve("test-results/live");
await mkdir(artifacts, { recursive: true });
const browser = await chromium.launch({ headless: true });
const context = await browser.newContext({
  baseURL,
  viewport: { width: 1440, height: 1000 },
  acceptDownloads: true,
});
await context.addInitScript(() =>
  Object.defineProperty(window, "showSaveFilePicker", {
    value: undefined,
    configurable: true,
  }),
);
const page = await context.newPage();
const errors = [];
page.on("pageerror", (error) => errors.push(error.message));
try {
  for (let attempt = 0; attempt < 100; attempt++) {
    try {
      const response = await context.request.get("/health");
      if (response.ok()) break;
    } catch {
      /* Container startup is asynchronous. */
    }
    await new Promise((resolve) => setTimeout(resolve, 200));
  }
  await page.goto("/");
  await expect(
    page.getByRole("heading", { name: "Object storage", exact: true }),
  ).toBeVisible();
  if (stage === "connecting") {
    await expect(
      page.getByText("Storage is connecting", { exact: true }),
    ).toBeVisible();
    await expect(
      page.getByRole("heading", { name: "Make room for your first file" }),
    ).toBeVisible();
    await page.screenshot({
      path: resolve(artifacts, "connecting-desktop.png"),
      fullPage: true,
    });
    console.log(
      "Real dashboard: same-origin assets/API load; joining state and empty workspace are honest",
    );
  } else {
    const payload = Buffer.alloc(1_000_001, 0x61),
      name = `browser-roundtrip-${Date.now()}.bin`;
    await page.locator("input[type=file]").setInputFiles({
      name,
      mimeType: "application/octet-stream",
      buffer: payload,
    });
    await page
      .getByRole("button", { name: "Upload 1 file", exact: true })
      .click();
    await expect(page.getByText("Stored", { exact: true })).toBeVisible({
      timeout: 30_000,
    });
    await page.getByRole("button", { name, exact: true }).click();
    const dialog = page.getByRole("dialog", { name });
    await dialog.getByRole("tab", { name: "Metadata", exact: true }).click();
    await dialog
      .getByLabel("Custom metadata (JSON)")
      .fill('{"owner":"Member A","reviewed":true}');
    await dialog.getByRole("button", { name: "Save changes" }).click();
    await expect(
      page.getByText("Metadata updated", { exact: true }),
    ).toBeVisible();
    await dialog.getByRole("tab", { name: "Chunks", exact: true }).click();
    await expect(dialog.getByText("Chunk 1", { exact: true })).toBeVisible();
    const downloading = page.waitForEvent("download");
    await dialog.getByRole("button", { name: "Download file" }).click();
    const download = await downloading,
      path = resolve(artifacts, name);
    await download.saveAs(path);
    const retrieved = await readFile(path);
    if (
      createHash("sha256").update(retrieved).digest("hex") !==
      createHash("sha256").update(payload).digest("hex")
    )
      throw new Error("Browser-downloaded checksum mismatch");
    await unlink(path);
    await page.screenshot({
      path: resolve(artifacts, "inspector-desktop.png"),
      fullPage: true,
    });
    await page.keyboard.press("Escape");
    await page.getByRole("button", { name: "Clear finished" }).click();
    await page.screenshot({
      path: resolve(artifacts, "workspace-desktop.png"),
      fullPage: true,
    });
    await page.getByRole("button", { name: "Cluster", exact: true }).click();
    await expect(page.locator(".topology-wires .wire-base")).toHaveCount(4);
    await page.getByLabel("File to visualize").selectOption({ label: name });
    await expect(page.getByRole("button", { name: /Chunk 1/ })).toBeVisible();
    await expect(page.getByRole("button", { name: /Chunk 2/ })).toBeVisible();
    await expect(
      page.locator(".placement-table").getByText("Healthy", { exact: true }),
    ).toHaveCount(4);
    await page.getByRole("button", { name: /Chunk 1/ }).click();
    await expect(page.locator(".topology-worker.holds-copy")).toHaveCount(2);
    await page.getByLabel("Activity type").selectOption("transfers");
    await expect(
      page
        .locator(".activity-list")
        .getByText(/^Copy acknowledged/)
        .first(),
    ).toBeVisible();
    await expect(
      page
        .locator(".activity-list")
        .getByText(/^Chunk verified/)
        .first(),
    ).toBeVisible();
    await page
      .getByRole("button", { name: /^Replay transfer/ })
      .first()
      .click();
    await expect(page.getByText(/Replay of observed event/)).toBeVisible();
    await page.screenshot({
      path: resolve(artifacts, "system-desktop.png"),
      fullPage: true,
    });
    await page.setViewportSize({ width: 390, height: 844 });
    if (
      !(await page.evaluate(
        () => document.documentElement.scrollWidth <= innerWidth,
      ))
    )
      throw new Error("Real mobile system explorer overflows");
    await page.screenshot({
      path: resolve(artifacts, "system-mobile.png"),
      fullPage: true,
    });
    await page.getByRole("button", { name: "Files", exact: true }).click();
    if (
      !(await page.evaluate(
        () => document.documentElement.scrollWidth <= window.innerWidth,
      ))
    )
      throw new Error("Mobile workspace overflows");
    await page.screenshot({
      path: resolve(artifacts, "workspace-mobile.png"),
      fullPage: true,
    });
    await page.getByRole("button", { name, exact: true }).click();
    await page
      .getByRole("dialog")
      .getByRole("button", { name: "Delete file" })
      .click();
    await page
      .getByRole("alertdialog")
      .getByRole("button", { name: "Delete file", exact: true })
      .click();
    await expect(page.getByRole("button", { name, exact: true })).toHaveCount(
      0,
    );
    await expect(page.getByText("File deleted", { exact: true })).toBeVisible();
    console.log(
      "Real dashboard + four workers: upload, metadata, chunk placement/highlights, observed transfer activity/replay, checksum download, delete and mobile layout passed",
    );
  }
  if (errors.length) throw new Error(errors.join("\n"));
} finally {
  await context.close();
  await browser.close();
}
