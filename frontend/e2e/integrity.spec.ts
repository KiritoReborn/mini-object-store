import { expect, test, type Page } from "@playwright/test";
import AxeBuilder from "@axe-core/playwright";
import { createHash } from "node:crypto";
import { readFile } from "node:fs/promises";

const ABC = "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad";
const EMPTY =
  "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855";
const localFile = (name: string, text: string) => ({
  name,
  mimeType: "application/octet-stream",
  buffer: Buffer.from(text),
});

async function openTool(page: Page, sha256 = ABC, size = 3) {
  const object = {
    object_id: "550e8400-e29b-41d4-a716-446655440000",
    name: "stored.bin",
    size,
    content_type: "application/octet-stream",
    status: "READY",
    created_at: "2026-11-16T08:00:00Z",
    updated_at: "2026-11-16T08:00:00Z",
    sha256,
    num_chunks: size ? 1 : 0,
    metadata: {},
  };
  // All API traffic is fulfilled here; the suite never uses the live backend.
  await page.route("**/api/v1/**", (route) => {
    const path = new URL(route.request().url()).pathname;
    if (path === "/api/v1/objects") return route.fulfill({ json: [object] });
    if (path === `/api/v1/objects/${object.object_id}/metadata`)
      return route.fulfill({ json: { ...object, chunks: [] } });
    if (path === "/api/v1/overview")
      return route.fulfill({
        json: {
          object_count: 1,
          logical_bytes: size,
          chunk_count: 1,
          healthy_replica_count: 0,
          under_replicated_chunks: 1,
          corrupt_replicas: 0,
          worker_count: 0,
          available_workers: 0,
          replication_factor: 2,
          chunk_size: 1000000,
          recovery_available: true,
          workers: [],
        },
      });
    if (path === "/api/v1/workers")
      return route.fulfill({
        json: { workers: [], placement_available_workers: 0 },
      });
    return route.fulfill({
      status: 404,
      json: { message: "No fixture for this route" },
    });
  });
  await page.goto("/");
  await page.getByRole("button", { name: "stored.bin", exact: true }).click();
  const tool = page.locator(".integrity-tool");
  await tool.locator("summary").click();
  return tool;
}

test("one file verifies against the stored checksum and exports only metadata", async ({
  page,
  context,
}) => {
  const content = "never-send-this-local-payload";
  const hash = createHash("sha256").update(content).digest("hex");
  await context.grantPermissions(["clipboard-read", "clipboard-write"]);
  const tool = await openTool(page, hash, Buffer.byteLength(content));
  const outbound: string[] = [];
  const consoleMessages: string[] = [];
  page.on("request", (request) =>
    outbound.push(
      `${request.method()} ${request.url()} ${request.postData() ?? ""}`,
    ),
  );
  page.on("console", (message) => consoleMessages.push(message.text()));
  await expect(tool.locator("input")).toHaveCount(1);
  await expect(
    tool.getByRole("button", { name: "Verify file" }),
  ).toBeDisabled();
  await tool
    .getByLabel("File to verify", { exact: true })
    .setInputFiles(localFile("local-private.bin", content));
  await tool.getByRole("button", { name: "Verify file" }).click();
  await expect(
    tool.getByRole("heading", { name: "MATCH", exact: true }),
  ).toBeVisible();
  await expect(tool.locator("code")).toHaveText(hash);
  await expect(
    tool.getByText(`${Buffer.byteLength(content)} bytes`, { exact: true }),
  ).toBeVisible();
  await tool.getByRole("button", { name: "Copy file SHA-256" }).click();
  await expect(tool.getByText("File SHA-256 copied")).toBeVisible();
  expect(await page.evaluate(() => navigator.clipboard.readText())).toBe(hash);

  const download = page.waitForEvent("download");
  await tool.getByRole("button", { name: "Export integrity report" }).click();
  const artifact = await download;
  expect(artifact.suggestedFilename()).toBe("artaud-integrity-report.json");
  const body = await readFile((await artifact.path())!, "utf8");
  const report = JSON.parse(body);
  expect(report).toMatchObject({
    algorithm: "SHA-256",
    result: "MATCH",
    expected_hash: hash,
    file: {
      name: "local-private.bin",
      size: Buffer.byteLength(content),
      sha256: hash,
    },
  });
  expect(Number.isNaN(Date.parse(report.timestamp))).toBe(false);
  expect(body).not.toContain(content);
  expect(outbound.join("\n")).not.toMatch(
    /POST|PUT|PATCH|local-private|never-send-this-local-payload/,
  );
  expect(outbound.join("\n")).not.toContain(hash);
  expect(consoleMessages.join("\n")).not.toMatch(
    /local-private|never-send-this-local-payload/,
  );
  expect(consoleMessages.join("\n")).not.toContain(hash);
});

test("wrong files mismatch even at the same size and a replacement clears the result", async ({
  page,
}) => {
  const tool = await openTool(page);
  const file = tool.getByLabel("File to verify", { exact: true });
  const verify = tool.getByRole("button", { name: "Verify file" });
  for (const content of ["abcd", "xyz"]) {
    await file.setInputFiles(localFile("wrong.bin", content));
    await expect(tool.getByRole("heading", { name: "MISMATCH" })).toHaveCount(
      0,
    );
    await expect(
      tool.getByRole("button", { name: "Export integrity report" }),
    ).toBeDisabled();
    await verify.click();
    await expect(
      tool.getByRole("heading", { name: "MISMATCH", exact: true }),
    ).toBeVisible();
    await expect(tool.locator("code")).toHaveText(
      createHash("sha256").update(content).digest("hex"),
    );
  }
});

test("accepts an empty file and preserves its result when the picker is cancelled", async ({
  page,
}) => {
  const tool = await openTool(page, EMPTY, 0);
  const file = tool.getByLabel("File to verify", { exact: true });
  await file.setInputFiles(localFile("empty.bin", ""));
  await tool.getByRole("button", { name: "Verify file" }).click();
  await expect(
    tool.getByRole("heading", { name: "MATCH", exact: true }),
  ).toBeVisible();
  await expect(tool.locator("code")).toHaveText(EMPTY);
  await expect(tool.getByText("0 bytes", { exact: true })).toBeVisible();
  await file.dispatchEvent("cancel", { bubbles: true });
  await expect(
    tool.getByRole("heading", { name: "MATCH", exact: true }),
  ).toBeVisible();
});

test("cannot verify without a valid stored checksum", async ({ page }) => {
  const tool = await openTool(page, "");
  await expect(tool.getByRole("alert")).toContainText("stored checksum");
  await expect(tool.getByLabel("File to verify")).toBeDisabled();
  await expect(
    tool.getByRole("button", { name: "Verify file" }),
  ).toBeDisabled();
});

for (const cancellation of ["replacement selection", "cancel button"]) {
  test(`${cancellation} discards late hashes and remains responsive`, async ({
    page,
  }) => {
    const hash = createHash("sha256").update("xyz").digest("hex");
    const tool = await openTool(page, hash);
    await page.evaluate(() => {
      const digest = crypto.subtle.digest.bind(crypto.subtle);
      let first = true;
      Object.defineProperty(crypto.subtle, "digest", {
        value: (...args: Parameters<typeof digest>) => {
          const result = digest(...args);
          if (!first) return result;
          first = false;
          return new Promise<ArrayBuffer>((resolve, reject) => {
            (
              window as Window & {
                releaseIntegrityDigest?: () => Promise<void>;
              }
            ).releaseIntegrityDigest = async () => {
              try {
                resolve(await result);
              } catch (error) {
                reject(error);
              }
            };
          });
        },
      });
    });
    await tool
      .getByLabel("File to verify", { exact: true })
      .setInputFiles(localFile("old.bin", "abc"));
    await tool
      .getByRole("button", { name: "Verify file", exact: true })
      .click();
    await expect(tool.getByRole("progressbar")).toBeVisible();
    await expect(
      tool.getByRole("button", { name: "Verify file", exact: true }),
    ).toBeDisabled();
    if (cancellation === "cancel button") {
      await tool.getByRole("button", { name: "Cancel verification" }).click();
      await expect(tool.getByText(/Verification cancelled/)).toBeVisible();
    }
    await tool
      .getByLabel("File to verify", { exact: true })
      .setInputFiles(localFile("new.bin", "xyz"));
    await tool
      .getByRole("button", { name: "Verify file", exact: true })
      .click();
    await expect(
      tool.getByRole("heading", { name: "MATCH", exact: true }),
    ).toBeVisible();
    await page.evaluate(async () =>
      (
        window as Window & { releaseIntegrityDigest?: () => Promise<void> }
      ).releaseIntegrityDigest?.(),
    );
    await expect(tool.locator("code")).toHaveText(hash);
    await tool
      .getByLabel("File to verify", { exact: true })
      .setInputFiles(localFile("last.bin", "abc"));
    await expect(tool.locator("code")).toHaveCount(0);
    await expect(
      tool.getByRole("button", { name: "Export integrity report" }),
    ).toBeDisabled();
  });
}

test("oversized files are rejected before any read", async ({ page }) => {
  const tool = await openTool(page);
  await page.evaluate(() => {
    const size = Object.getOwnPropertyDescriptor(Blob.prototype, "size")!.get!;
    Object.defineProperty(File.prototype, "size", {
      get() {
        return this.name === "oversized.bin" ? 134217729 : size.call(this);
      },
    });
    Object.defineProperty(Blob.prototype, "arrayBuffer", {
      value() {
        throw new Error("Files must not be read");
      },
    });
  });
  await tool
    .getByLabel("File to verify", { exact: true })
    .setInputFiles(localFile("oversized.bin", "not read"));
  await expect(tool.getByRole("alert")).toContainText("exceeds 128 MiB");
  await expect(
    tool.getByRole("button", { name: "Verify file", exact: true }),
  ).toBeDisabled();
  await expect(tool.locator("code")).toHaveCount(0);
});

for (const unavailable of ["insecure context", "missing Web Crypto"]) {
  test(`explains ${unavailable} instead of starting verification`, async ({
    page,
  }) => {
    await page.addInitScript((mode) => {
      if (mode === "insecure context")
        Object.defineProperty(window, "isSecureContext", { value: false });
      else Object.defineProperty(window.crypto, "subtle", { value: undefined });
    }, unavailable);
    const tool = await openTool(page);
    await expect(tool.getByRole("alert")).toContainText(
      unavailable === "insecure context" ? "HTTPS or localhost" : "Web Crypto",
    );
    await expect(
      tool.getByLabel("File to verify", { exact: true }),
    ).toBeDisabled();
    await expect(
      tool.getByRole("button", { name: "Verify file", exact: true }),
    ).toBeDisabled();
  });
}

test("integrity controls work with the keyboard and fit narrow screens accessibly", async ({
  page,
}) => {
  const tool = await openTool(page);
  await tool
    .getByLabel("File to verify", { exact: true })
    .setInputFiles(
      localFile("original-" + "long-name-".repeat(12) + ".bin", "abc"),
    );
  const verify = tool.getByRole("button", {
    name: "Verify file",
    exact: true,
  });
  await verify.focus();
  await page.keyboard.press("Enter");
  await expect(
    tool.getByRole("heading", { name: "MATCH", exact: true }),
  ).toBeVisible();
  for (const width of [768, 390, 320]) {
    await page.setViewportSize({ width, height: 900 });
    expect(
      await page.evaluate(
        () => document.documentElement.scrollWidth <= innerWidth,
      ),
    ).toBe(true);
    expect(
      await tool.evaluate(
        (element) => element.scrollWidth <= element.clientWidth,
      ),
    ).toBe(true);
  }
  expect(
    (
      await new AxeBuilder({ page })
        .withTags(["wcag2a", "wcag2aa", "wcag21aa"])
        .analyze()
    ).violations,
  ).toEqual([]);
  await tool.screenshot({
    path: test.info().outputPath("integrity-mobile.png"),
  });
  await page.keyboard.press("Escape");
  await expect(page.getByRole("dialog")).not.toBeVisible();
  await page.getByRole("button", { name: "stored.bin", exact: true }).click();
  await page.locator(".integrity-tool summary").click();
  await expect(page.locator(".integrity-tool code")).toHaveCount(0);
});
