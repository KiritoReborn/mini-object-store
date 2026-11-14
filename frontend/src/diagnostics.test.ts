import { beforeEach, expect, it } from "vitest";
import {
  clearRequestLog,
  getRequestLog,
  startObservation,
} from "./diagnostics";

beforeEach(clearRequestLog);
it("keeps only bounded redacted endpoint measurements, never IDs or URL values", () => {
  for (let i = 0; i < 80; i++)
    startObservation(
      "DELETE",
      "/api/v1/objects/private-filename-id?key=secret",
    )(503, "HTTP response");
  const entries = getRequestLog();
  expect(entries).toHaveLength(60);
  expect(entries[0].method).toBe("DELETE");
  expect(entries[0].endpoint).toBe("Object");
  expect(entries[0].status).toBe(503);
  expect(entries[0].duration_ms).toBeGreaterThanOrEqual(0);
  expect(JSON.stringify(entries)).not.toMatch(/private|filename|secret|key=/);
});
it("clears measurements and records an unavailable transport without a fake status", () => {
  startObservation("GET", "/api/v1/overview")(null, "Network failure");
  expect(getRequestLog()[0].status).toBeNull();
  expect(getRequestLog()[0].endpoint).toBe("Overview");
  clearRequestLog();
  expect(getRequestLog()).toEqual([]);
});

it("does not mix an old backend's late response into a new connection history", () => {
  const oldRequest = startObservation("GET", "/api/v1/overview");
  clearRequestLog();
  oldRequest(200, "HTTP response");
  expect(getRequestLog()).toEqual([]);
});
