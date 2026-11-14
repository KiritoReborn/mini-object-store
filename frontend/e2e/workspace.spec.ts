import { expect, test, type Page } from "@playwright/test";
import AxeBuilder from "@axe-core/playwright";

const names = [
  "architecture-notes.pdf",
  "mountains.jpg",
  "project-backup.zip",
  "sensor-readings.csv",
  "presentation.mp4",
  "meeting-notes.txt",
  "sample-audio.wav",
  "config.json",
];
const mimes = [
  "application/pdf",
  "image/jpeg",
  "application/zip",
  "text/csv",
  "video/mp4",
  "text/plain",
  "audio/wav",
  "application/json",
];
const makeObject = (name: string, index = 0) => ({
  object_id: `550e8400-e29b-41d4-a716-44665544000${index}`,
  name,
  size:
    [2500000, 5100000, 18400000, 420000, 32000000, 12000, 7100000, 850][
      index
    ] ?? 100,
  content_type: mimes[index] ?? "application/octet-stream",
  created_at: "2026-11-14T09:00:00+00:00",
  updated_at: "2026-11-14T09:00:00+00:00",
  sha256: "a".repeat(64),
  num_chunks: [3, 6, 19, 1, 32, 1, 8, 1][index] ?? 1,
  metadata: { project: "Cloud computing", reviewed: false },
  status: "READY" as const,
});
const workers = [1, 2, 3, 4].map((n) => ({
  worker_id: `worker${n}`,
  status: "ALIVE",
  available: true,
  chunk_count: 34 + n,
  stored_bytes: 34000000 + n * 1000000,
  last_heartbeat: "2026-11-14T09:00:00+00:00",
  heartbeat_age_seconds: n,
}));

export async function fixture(page: Page, degraded = false, empty = false) {
  let objects = empty ? [] : names.map(makeObject);
  await page.addInitScript(() =>
    Object.defineProperty(window, "showSaveFilePicker", {
      value: undefined,
      configurable: true,
    }),
  );
  await page.route("**/api/v1/**", async (route) => {
    const request = route.request(),
      url = new URL(request.url()),
      method = request.method();
    if (url.pathname.endsWith("/overview"))
      return route.fulfill({
        json: {
          object_count: objects.length,
          logical_bytes: objects.reduce((sum, o) => sum + o.size, 0),
          chunk_count: 71,
          healthy_replica_count: degraded ? 0 : 142,
          under_replicated_chunks: degraded ? 71 : 0,
          corrupt_replicas: 0,
          worker_count: 4,
          available_workers: degraded ? 0 : 4,
          replication_factor: 2,
          chunk_size: 1000000,
          recovery_available: !degraded,
          workers: workers.map((w) =>
            degraded ? { ...w, status: "JOINING", available: false } : w,
          ),
        },
      });
    if (url.pathname === "/api/v1/objects") {
      if (method === "POST") {
        const match = /filename="([^"]+)"/.exec(request.postData() ?? "");
        const obj = makeObject(match?.[1] ?? "upload.bin", objects.length);
        objects = [...objects, obj];
        return route.fulfill({ status: 201, json: obj });
      }
      return route.fulfill({ json: objects });
    }
    const oid = url.pathname.split("/")[4];
    const obj = objects.find((item) => item.object_id === oid);
    if (!obj)
      return route.fulfill({
        status: 404,
        json: { error: "OBJECT_NOT_FOUND", message: "Object does not exist" },
      });
    if (method === "DELETE") {
      objects = objects.filter((item) => item.object_id !== oid);
      return route.fulfill({ status: 204 });
    }
    if (method === "PATCH")
      obj.metadata = { ...obj.metadata, ...request.postDataJSON().metadata };
    if (url.pathname.endsWith("/metadata"))
      return route.fulfill({
        json: {
          ...obj,
          chunks: [
            {
              chunk_id: `${oid}_0`,
              index: 0,
              size: 1000000,
              sha256: "b".repeat(64),
              workers: ["worker1", "worker3"],
              replicas: ["worker1", "worker3"].map((worker_id) => ({
                worker_id,
                state: "HEALTHY",
                worker_status: "ALIVE",
                last_verified_at: obj.created_at,
              })),
            },
          ],
        },
      });
    return route.fulfill({
      status: 503,
      json: {
        error: "OBJECT_UNAVAILABLE",
        message: "No verified readable copy of a required chunk",
      },
    });
  });
}

test("browsing, filtering and the real metadata editor", async ({ page }) => {
  await fixture(page);
  await page.goto("/");
  await expect(
    page.getByRole("heading", { name: "Object storage", exact: true }),
  ).toBeVisible();
  await page
    .getByRole("searchbox", { name: "Search files" })
    .fill("architecture");
  await expect(
    page.getByRole("button", { name: "architecture-notes.pdf", exact: true }),
  ).toBeVisible();
  await expect(
    page.getByRole("button", { name: "mountains.jpg", exact: true }),
  ).toHaveCount(0);
  await page
    .getByRole("button", { name: "architecture-notes.pdf", exact: true })
    .click();
  const dialog = page.getByRole("dialog", { name: "architecture-notes.pdf" });
  await dialog.getByRole("tab", { name: "Metadata", exact: true }).click();
  await dialog
    .getByLabel("Custom metadata (JSON)")
    .fill('{"project":"Cloud computing","reviewed":true}');
  await dialog.getByRole("button", { name: "Save changes" }).click();
  await expect(
    dialog.getByText("Metadata updated", { exact: true }),
  ).toBeVisible();
  await dialog.getByRole("tab", { name: "Chunks", exact: true }).click();
  await expect(dialog.getByText("worker3", { exact: true })).toBeVisible();
  await page.keyboard.press("Escape");
  await expect(dialog).not.toBeVisible();
});

test("multiple-file upload reports stored only after controller success", async ({
  page,
}) => {
  await fixture(page);
  await page.goto("/");
  await page.locator("input[type=file]").setInputFiles([
    { name: "first.txt", mimeType: "text/plain", buffer: Buffer.from("first") },
    {
      name: "second.txt",
      mimeType: "text/plain",
      buffer: Buffer.from("second"),
    },
  ]);
  await page
    .getByRole("button", { name: "Upload 2 files", exact: true })
    .click();
  await expect(page.getByText("Stored", { exact: true })).toHaveCount(2);
  await expect(
    page.getByRole("button", { name: "first.txt", exact: true }),
  ).toBeVisible();
});

test("delete is protected by a specific confirmation", async ({ page }) => {
  await fixture(page);
  await page.goto("/");
  await page
    .getByRole("button", { name: "architecture-notes.pdf", exact: true })
    .click();
  await page
    .getByRole("dialog")
    .getByRole("button", { name: "Delete file" })
    .click();
  const confirm = page.getByRole("alertdialog");
  await expect(
    confirm.getByText("architecture-notes.pdf", { exact: true }),
  ).toBeVisible();
  await confirm
    .getByRole("button", { name: "Delete file", exact: true })
    .click();
  await expect(
    page.getByRole("button", { name: "architecture-notes.pdf", exact: true }),
  ).toHaveCount(0);
  await expect(page.getByText("File deleted", { exact: true })).toBeVisible();
});

test("empty and joining state does not pretend uploads are ready", async ({
  page,
}) => {
  await fixture(page, true, true);
  await page.goto("/");
  await expect(
    page.getByText("Storage is connecting", { exact: true }),
  ).toBeVisible();
  await expect(
    page.getByRole("heading", { name: "Make room for your first file" }),
  ).toBeVisible();
  await page.locator("input[type=file]").setInputFiles({
    name: "first.txt",
    mimeType: "text/plain",
    buffer: Buffer.from("first"),
  });
  await expect(
    page.getByRole("button", { name: "Upload 1 file", exact: true }),
  ).toBeDisabled();
});

test("download errors stay in the workspace and never claim success", async ({
  page,
}) => {
  await fixture(page);
  await page.goto("/");
  await page
    .getByRole("button", { name: "architecture-notes.pdf", exact: true })
    .click();
  await page
    .getByRole("dialog")
    .getByRole("button", { name: "Download file" })
    .click();
  await expect(
    page
      .getByRole("dialog")
      .getByText("No verified readable copy of a required chunk", {
        exact: true,
      }),
  ).toBeVisible();
});

test("desktop and mobile fit, cluster navigation and keyboard search", async ({
  page,
}) => {
  await fixture(page);
  await page.goto("/");
  await page.keyboard.press("/");
  await expect(
    page.getByRole("searchbox", { name: "Search files" }),
  ).toBeFocused();
  await page.getByRole("button", { name: "Cluster", exact: true }).click();
  await expect(
    page.getByRole("heading", { name: "Storage cluster", exact: true }),
  ).toBeVisible();
  await page.keyboard.press("/");
  await expect(
    page.getByRole("searchbox", { name: "Search files" }),
  ).toBeFocused();
  await page.screenshot({
    path: "test-results/workspace-desktop.png",
    fullPage: true,
  });
  for (const width of [768, 390, 320]) {
    await page.setViewportSize({ width, height: 900 });
    expect(
      await page.evaluate(
        () => document.documentElement.scrollWidth <= window.innerWidth,
      ),
    ).toBe(true);
  }
  await page.screenshot({
    path: "test-results/workspace-mobile.png",
    fullPage: true,
  });
});

test("removing a waiting file prevents its upload while another file is sending", async ({
  page,
}) => {
  await fixture(page);
  let release!: () => void;
  const gate = new Promise<void>((resolve) => {
    release = resolve;
  });
  const sent: string[] = [];
  await page.route("**/api/v1/objects", async (route) => {
    if (route.request().method() !== "POST") return route.fallback();
    const name =
      /filename="([^"]+)"/.exec(route.request().postData() ?? "")?.[1] ??
      "unknown";
    sent.push(name);
    if (sent.length === 1) await gate;
    return route.fulfill({ status: 201, json: makeObject(name, 8) });
  });
  await page.goto("/");
  await page.locator("input[type=file]").setInputFiles([
    { name: "first.txt", mimeType: "text/plain", buffer: Buffer.from("first") },
    {
      name: "remove-me.txt",
      mimeType: "text/plain",
      buffer: Buffer.from("second"),
    },
  ]);
  await page
    .getByRole("button", { name: "Upload 2 files", exact: true })
    .click();
  await expect.poll(() => sent.length).toBe(1);
  await page
    .getByRole("button", { name: "Remove remove-me.txt from queue" })
    .click();
  release();
  await expect(
    page.getByRole("button", { name: "Upload 0 files", exact: true }),
  ).toBeVisible();
  expect(sent).toEqual(["first.txt"]);
});

test("file workspace, inspector and narrow layout meet accessibility checks", async ({
  page,
}) => {
  await fixture(page);
  await page.goto("/");
  await expect(
    page.getByRole("button", { name: "architecture-notes.pdf", exact: true }),
  ).toBeVisible();
  const check = async () =>
    expect(
      (
        await new AxeBuilder({ page })
          .withTags(["wcag2a", "wcag2aa", "wcag21aa"])
          .analyze()
      ).violations,
    ).toEqual([]);
  await check();
  await page
    .getByRole("button", { name: "architecture-notes.pdf", exact: true })
    .click();
  await expect(page.getByRole("dialog")).toBeVisible();
  await check();
  await page.screenshot({
    path: "test-results/object-inspector.png",
    fullPage: true,
  });
  await page.keyboard.press("Escape");
  await page.setViewportSize({ width: 390, height: 844 });
  await check();
});

test("failed refresh marks node and replica status unknown until reconnect", async ({
  page,
}) => {
  await fixture(page);
  let offline = false;
  await page.route("**/api/v1/**", (route) =>
    offline
      ? route.fulfill({ status: 503, json: { message: "Controller offline" } })
      : route.fallback(),
  );
  await page.goto("/");
  await expect(
    page.getByText("4 of 4 nodes available", { exact: true }),
  ).toBeVisible();
  offline = true;
  await page.getByRole("button", { name: "Refresh workspace" }).click();
  await expect(page.getByText("Unknown", { exact: true })).toHaveCount(4);
  await expect(
    page.getByText("Replica status unavailable", { exact: true }),
  ).toBeVisible();
  offline = false;
  await page.getByRole("button", { name: "Try again", exact: true }).click();
  await expect(
    page.getByText("4 of 4 nodes available", { exact: true }),
  ).toBeVisible();
});

test("metadata save preserves unrelated changes from another session", async ({
  page,
}) => {
  await fixture(page);
  await page.goto("/");
  await page
    .getByRole("button", { name: "architecture-notes.pdf", exact: true })
    .click();
  const dialog = page.getByRole("dialog");
  await dialog.getByRole("tab", { name: "Metadata", exact: true }).click();
  const editor = dialog.getByLabel("Custom metadata (JSON)");
  await expect(editor).toHaveValue(/Cloud computing/);
  await page.evaluate(async () => {
    await fetch(
      "/api/v1/objects/550e8400-e29b-41d4-a716-446655440000/metadata",
      {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ metadata: { project: "Other session" } }),
      },
    );
  });
  await editor.fill('{"project":"Cloud computing","reviewed":true}');
  await dialog.getByRole("button", { name: "Save changes" }).click();
  await expect(editor).toHaveValue(/Other session/);
  await expect(editor).toHaveValue(/"reviewed": true/);
});

test("replica inspector refreshes after a download discovers corruption", async ({
  page,
}) => {
  await fixture(page);
  const obj = makeObject(names[0]),
    oid = obj.object_id;
  let corrupted = false;
  await page.route(`**/api/v1/objects/${oid}/metadata`, (route) => {
    if (!corrupted) return route.fallback();
    return route.fulfill({
      json: {
        ...obj,
        chunks: [
          {
            chunk_id: `${oid}_0`,
            index: 0,
            size: obj.size,
            sha256: obj.sha256,
            workers: ["worker3"],
            replicas: ["worker1", "worker3"].map((worker_id) => ({
              worker_id,
              state: worker_id === "worker1" ? "CORRUPT" : "HEALTHY",
              worker_status: "ALIVE",
              last_verified_at: obj.created_at,
            })),
          },
        ],
      },
    });
  });
  await page.route(`**/api/v1/objects/${oid}`, (route) => {
    corrupted = true;
    return route.fulfill({
      status: 200,
      body: Buffer.from("valid bytes"),
      contentType: "application/octet-stream",
    });
  });
  await page.goto("/");
  await page.getByRole("button", { name: names[0], exact: true }).click();
  const dialog = page.getByRole("dialog");
  await dialog.getByRole("tab", { name: "Chunks", exact: true }).click();
  await expect(dialog.getByText(/2 available copies/)).toBeVisible();
  await dialog.getByRole("button", { name: "Download file" }).click();
  await expect(dialog.getByText(/1 available copy/)).toBeVisible();
});

test("the close control reflects deletion in progress", async ({ page }) => {
  await fixture(page);
  let release!: () => void;
  const gate = new Promise<void>((resolve) => {
    release = resolve;
  });
  await page.route("**/api/v1/objects/*", async (route) => {
    if (route.request().method() !== "DELETE") return route.fallback();
    await gate;
    return route.fulfill({ status: 204 });
  });
  await page.goto("/");
  await page.getByRole("button", { name: names[0], exact: true }).click();
  await page
    .getByRole("dialog")
    .getByRole("button", { name: "Delete file" })
    .click();
  const confirm = page.getByRole("alertdialog");
  await confirm
    .getByRole("button", { name: "Delete file", exact: true })
    .click();
  try {
    await expect(
      confirm.getByRole("button", { name: "Close dialog" }),
    ).toBeDisabled();
  } finally {
    release();
  }
});
