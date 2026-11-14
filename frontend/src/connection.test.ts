import { describe, expect, it } from "vitest";
import { validateBackend } from "./connection";

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
