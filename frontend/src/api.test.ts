import { afterEach, expect, it, vi } from "vitest";
import { request } from "./api";

afterEach(() => vi.unstubAllGlobals());
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
