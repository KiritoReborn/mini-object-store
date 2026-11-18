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

async function openTool(page: Page, sha256 = ABC) {
  const object = {
    object_id: "550e8400-e29b-41d4-a716-446655440000",
    name: "stored.bin",
    size: 3,
    content_type: "application/octet-stream",
    status: "READY",
    created_at: "2026-11-16T08:00:00Z",
    updated_at: "2026-11-16T08:00:00Z",
    sha256,
    num_chunks: 1,
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
          logical_bytes: 3,
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

test("local comparison, object checksum, copy and JSON export send no file data", async ({
  page,
  context,
}) => {
  const content = "never-send-this-local-payload";
  const hash = createHash("sha256").update(content).digest("hex");
  await context.grantPermissions(["clipboard-read", "clipboard-write"]);
  const tool = await openTool(page, hash);
  const outbound: string[] = [];
  const consoleMessages: string[] = [];
  page.on("request", (request) =>
    outbound.push(
      `${request.method()} ${request.url()} ${request.postData() ?? ""}`,
    ),
  );
  page.on("console", (message) => consoleMessages.push(message.text()));
  await expect(tool.getByLabel("Expected SHA-256 (optional)")).toHaveValue(
    hash,
  );
  await tool
    .getByLabel("Original file", { exact: true })
    .setInputFiles(localFile("original-private.bin", content));
  await tool
    .getByLabel("Downloaded file", { exact: true })
    .setInputFiles(localFile("downloaded-private.bin", content));
  await tool
    .getByRole("button", { name: "Compare files", exact: true })
    .click();
  await expect(
    tool.getByRole("heading", { name: "Files: MATCH", exact: true }),
  ).toBeVisible();
  await expect(
    tool.getByText("Original vs expected: MATCH", { exact: true }),
  ).toBeVisible();
  await expect(
    tool.getByText("Downloaded vs expected: MATCH", { exact: true }),
  ).toBeVisible();
  await expect(tool.locator("code")).toHaveText([hash, hash]);
  await expect(
    tool.getByText(`${Buffer.byteLength(content)} bytes`, { exact: true }),
  ).toHaveCount(2);
  await tool.getByRole("button", { name: "Copy original SHA-256" }).click();
  await expect(
    tool.getByText("Original SHA-256 copied", { exact: true }),
  ).toBeVisible();
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
    original: {
      name: "original-private.bin",
      size: Buffer.byteLength(content),
      sha256: hash,
    },
    downloaded: {
      name: "downloaded-private.bin",
      size: Buffer.byteLength(content),
      sha256: hash,
    },
    original_matches_expected: true,
    downloaded_matches_expected: true,
  });
  expect(Number.isNaN(Date.parse(report.timestamp))).toBe(false);
  expect(body).not.toContain(content);
  expect(outbound.join("\n")).not.toMatch(
    /POST|PUT|PATCH|original-private|downloaded-private|never-send-this-local-payload/,
  );
  expect(outbound.join("\n")).not.toContain(hash);
  expect(consoleMessages.join("\n")).not.toMatch(
    /original-private|downloaded-private|never-send-this-local-payload/,
  );
  expect(consoleMessages.join("\n")).not.toContain(hash);
});

test("different sizes and same-size different bytes both mismatch and retain both hashes", async ({
  page,
}) => {
  const tool = await openTool(page);
  await tool
    .getByLabel("Original file", { exact: true })
    .setInputFiles(localFile("original.bin", "abc"));
  await tool
    .getByLabel("Downloaded file", { exact: true })
    .setInputFiles(localFile("download.bin", "abcd"));
  await tool
    .getByRole("button", { name: "Compare files", exact: true })
    .click();
  await expect(
    tool.getByRole("heading", { name: "Files: MISMATCH", exact: true }),
  ).toBeVisible();
  await expect(tool.locator("code")).toHaveText([
    ABC,
    createHash("sha256").update("abcd").digest("hex"),
  ]);
  await expect(
    tool.getByText("Original vs expected: MATCH", { exact: true }),
  ).toBeVisible();
  await expect(
    tool.getByText("Downloaded vs expected: MISMATCH", { exact: true }),
  ).toBeVisible();
  await tool
    .getByLabel("Downloaded file", { exact: true })
    .setInputFiles(localFile("download.bin", "xyz"));
  await expect(tool.getByRole("heading", { name: /^Files:/ })).toHaveCount(0);
  await expect(
    tool.getByRole("button", { name: "Export integrity report" }),
  ).toBeDisabled();
  await tool
    .getByRole("button", { name: "Compare files", exact: true })
    .click();
  await expect(
    tool.getByRole("heading", { name: "Files: MISMATCH", exact: true }),
  ).toBeVisible();
  await expect(tool.locator("code")).toHaveText([
    ABC,
    createHash("sha256").update("xyz").digest("hex"),
  ]);
});

test("empty files, identical selections, picker cancellation and optional expected hashes", async ({
  page,
}) => {
  const tool = await openTool(page);
  const expected = tool.getByLabel("Expected SHA-256 (optional)");
  const empty = localFile("empty.bin", "");
  await tool.getByLabel("Original file", { exact: true }).setInputFiles(empty);
  await tool
    .getByLabel("Downloaded file", { exact: true })
    .setInputFiles(empty);
  await expected.fill("  " + EMPTY.toUpperCase() + "  ");
  await tool
    .getByRole("button", { name: "Compare files", exact: true })
    .click();
  await expect(
    tool.getByRole("heading", { name: "Files: MATCH", exact: true }),
  ).toBeVisible();
  await expect(tool.locator("code")).toHaveText([EMPTY, EMPTY]);
  await expect(tool.getByText("0 bytes", { exact: true })).toHaveCount(2);
  await expect(
    tool.getByText("Downloaded vs expected: MATCH", { exact: true }),
  ).toBeVisible();
  await tool
    .getByLabel("Original file", { exact: true })
    .dispatchEvent("cancel");
  await tool.getByLabel("Downloaded file", { exact: true }).setInputFiles([]);
  await expect(
    tool.getByRole("heading", { name: "Files: MATCH", exact: true }),
  ).toBeVisible();
  await expected.fill("invalid hash");
  await expect(tool.getByRole("alert")).toContainText("64 hexadecimal");
  await expect(
    tool.getByRole("button", { name: "Export integrity report" }),
  ).toBeDisabled();
  await expected.fill("");
  await expect(
    tool.getByRole("heading", { name: "Files: MATCH", exact: true }),
  ).toBeVisible();
  await expect(tool.getByText(/vs expected:/)).toHaveCount(0);
  const download = page.waitForEvent("download");
  await tool.getByRole("button", { name: "Export integrity report" }).click();
  const report = JSON.parse(
    await readFile((await (await download).path())!, "utf8"),
  );
  expect(report.expected_hash).toBeNull();
  expect(report.original_matches_expected).toBeNull();
  await tool.getByRole("button", { name: "Use object checksum" }).click();
  await expect(expected).toHaveValue(ABC);
  await expect(
    tool.getByText("Original vs expected: MISMATCH", { exact: true }),
  ).toBeVisible();
});

for (const cancellation of ["replacement selection", "cancel button"]) {
  test(`${cancellation} discards late hashes and remains responsive`, async ({
    page,
  }) => {
    const tool = await openTool(page);
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
      .getByLabel("Original file", { exact: true })
      .setInputFiles(localFile("old.bin", "abc"));
    await tool
      .getByLabel("Downloaded file", { exact: true })
      .setInputFiles(localFile("old-copy.bin", "abc"));
    await tool
      .getByRole("button", { name: "Compare files", exact: true })
      .click();
    await expect(tool.getByRole("progressbar")).toBeVisible();
    await expect(
      tool.getByRole("button", { name: "Compare files", exact: true }),
    ).toBeDisabled();
    if (cancellation === "cancel button") {
      await tool.getByRole("button", { name: "Cancel comparison" }).click();
      await expect(tool.getByText(/Comparison cancelled/)).toBeVisible();
    }
    await tool
      .getByLabel("Original file", { exact: true })
      .setInputFiles(localFile("new.bin", "xyz"));
    await tool
      .getByLabel("Downloaded file", { exact: true })
      .setInputFiles(localFile("new-copy.bin", "xyz"));
    await tool
      .getByRole("button", { name: "Compare files", exact: true })
      .click();
    await expect(
      tool.getByRole("heading", { name: "Files: MATCH", exact: true }),
    ).toBeVisible();
    await page.evaluate(async () =>
      (
        window as Window & { releaseIntegrityDigest?: () => Promise<void> }
      ).releaseIntegrityDigest?.(),
    );
    const hash = createHash("sha256").update("xyz").digest("hex");
    await expect(tool.locator("code")).toHaveText([hash, hash]);
    await tool
      .getByLabel("Original file", { exact: true })
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
    .getByLabel("Original file", { exact: true })
    .setInputFiles(localFile("oversized.bin", "not read"));
  await tool
    .getByLabel("Downloaded file", { exact: true })
    .setInputFiles(localFile("download.bin", "abc"));
  await expect(tool.getByRole("alert")).toContainText("exceeds 128 MiB");
  await expect(
    tool.getByRole("button", { name: "Compare files", exact: true }),
  ).toBeDisabled();
  await expect(tool.locator("code")).toHaveCount(0);
});

for (const unavailable of ["insecure context", "missing Web Crypto"]) {
  test(`explains ${unavailable} instead of starting a comparison`, async ({
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
      tool.getByLabel("Original file", { exact: true }),
    ).toBeDisabled();
    await expect(
      tool.getByRole("button", { name: "Compare files", exact: true }),
    ).toBeDisabled();
  });
}

test("integrity controls work with the keyboard and fit narrow screens accessibly", async ({
  page,
}) => {
  const tool = await openTool(page);
  await tool
    .getByLabel("Original file", { exact: true })
    .setInputFiles(
      localFile("original-" + "long-name-".repeat(12) + ".bin", "abc"),
    );
  await tool
    .getByLabel("Downloaded file", { exact: true })
    .setInputFiles(localFile("download.bin", "abc"));
  const compare = tool.getByRole("button", {
    name: "Compare files",
    exact: true,
  });
  await compare.focus();
  await page.keyboard.press("Enter");
  await expect(
    tool.getByRole("heading", { name: "Files: MATCH", exact: true }),
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
  await tool.screenshot({ path: "test-results/integrity-mobile.png" });
  await page.keyboard.press("Escape");
  await expect(page.getByRole("dialog")).not.toBeVisible();
  await page.getByRole("button", { name: "stored.bin", exact: true }).click();
  await page.locator(".integrity-tool summary").click();
  await expect(page.locator(".integrity-tool code")).toHaveCount(0);
});
