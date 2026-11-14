import { afterEach, expect, it, vi } from "vitest";
import { downloadFile, request, uploadFile } from "./api";
import { clearRequestLog, getRequestLog } from "./diagnostics";
import type { StoredObject } from "./types";

afterEach(() => {
  vi.unstubAllGlobals();
  clearRequestLog();
});
it("returns real JSON from a successful controller response", async () => {
  vi.stubGlobal(
    "fetch",
    vi
      .fn()
      .mockResolvedValue(new Response('[{"object_id":"id"}]', { status: 200 })),
  );
  expect(await request("/api/v1/objects")).toEqual([{ object_id: "id" }]);
});
it("shows the controller message for service unavailability", async () => {
  vi.stubGlobal(
    "fetch",
    vi
      .fn()
      .mockResolvedValue(
        new Response(
          '{"error":"STORAGE_UNAVAILABLE","message":"Two available copies are required"}',
          { status: 503 },
        ),
      ),
  );
  await expect(request("/api/v1/objects")).rejects.toThrow(
    "Two available copies are required",
  );
});
it("does not show a proxy HTML error as product content", async () => {
  vi.stubGlobal(
    "fetch",
    vi
      .fn()
      .mockResolvedValue(
        new Response("<html>private stack</html>", { status: 502 }),
      ),
  );
  await expect(request("/api/v1/objects")).rejects.toThrow(
    "The controller could not complete this request",
  );
});
it("retains malformed upload responses in failure diagnostics", async () => {
  class InvalidXHR {
    upload = {};
    status = 201;
    responseText = "<html>bad gateway</html>";
    onload?: () => void;
    onloadend?: () => void;
    open() {}
    setRequestHeader() {}
    abort() {}
    send() {
      this.onload?.();
      this.onloadend?.();
    }
  }
  vi.stubGlobal("XMLHttpRequest", InvalidXHR);
  await expect(
    uploadFile(
      new File([""], "private-file"),
      {},
      new AbortController().signal,
      () => {},
    ),
  ).rejects.toThrow("Unexpected controller response");
  expect(getRequestLog().at(-1)?.outcome).toBe("Invalid response");
  expect(getRequestLog().at(-1)?.status).toBe(201);
});
it("shows a response-body interruption after HTTP 200 in failure diagnostics", async () => {
  vi.stubGlobal("window", { dispatchEvent() {} });
  const body = new ReadableStream<Uint8Array>({
    start(controller) {
      controller.error(new Error("Connection lost during file bytes"));
    },
  });
  vi.stubGlobal(
    "fetch",
    vi.fn().mockResolvedValue(new Response(body, { status: 200 })),
  );
  await expect(
    downloadFile({
      object_id: "private-id",
      name: "private-name",
    } as StoredObject),
  ).rejects.toThrow("Connection lost");
  expect(getRequestLog().at(-1)?.status).toBe(200);
  expect(getRequestLog().at(-1)?.outcome).toBe("Response handling failed");
});
