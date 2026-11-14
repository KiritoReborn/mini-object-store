import { afterEach, describe, expect, it, vi } from "vitest";
import { testBackendConnection, validateBackend } from "./connection";
import { getRequestLog } from "./diagnostics";
afterEach(() => vi.unstubAllGlobals());

describe("public frontend backend connection", () => {
  it("accepts remote HTTPS origins and local development without a proxy", () => {
    expect(validateBackend("https://demo.ngrok-free.dev/")).toBe(
      "https://demo.ngrok-free.dev",
    );
    expect(validateBackend("http://localhost:8000")).toBe(
      "http://localhost:8000",
    );
    expect(validateBackend("")).toBe("");
  });
  it("rejects mixed-content remote HTTP, paths, credentials and non-web URLs", () => {
    for (const value of [
      "http://example.com",
      "https://example.com/api",
      "https://owner:secret@example.com",
      "file:///tmp/test",
      "https://example.com?key=secret",
    ]) {
      expect(() => validateBackend(value)).toThrow();
    }
  });
});

it("explains a static frontend HTML response instead of treating it as a backend", async () => {
  vi.stubGlobal(
    "fetch",
    vi.fn().mockResolvedValue(new Response("<!doctype html>", { status: 200 })),
  );
  await expect(
    testBackendConnection("https://frontend.example", "private-key"),
  ).rejects.toThrow("did not return a controller overview");
  expect(getRequestLog().at(-1)?.outcome).toBe("Invalid response");
});
