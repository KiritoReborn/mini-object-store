import { describe, expect, it } from "vitest";
import { listingCsv, matchesObject } from "./object-tools";
import type { StoredObject } from "./types";

const file: StoredObject = {
  object_id: "abc-123",
  name: "=SUM(1,2).txt",
  size: 12,
  content_type: "text/plain",
  created_at: "2026-11-14T09:00:00Z",
  updated_at: "2026-11-14T09:00:00Z",
  sha256: "a".repeat(64),
  num_chunks: 1,
  metadata: { project: { course: "Cloud computing" }, reviewed: false },
  status: "READY",
};
describe("object listing tools", () => {
  it("matches literal quotes, backslashes and nested metadata string values", () => {
    const special = {
      ...file,
      metadata: {
        note: 'He said "hello"',
        nested: [{ path: "C:\\reports\\demo", message: "first\nsecond" }],
      },
    };
    expect(matchesObject(special, 'He said "hello"', "metadata")).toBe(true);
    expect(matchesObject(special, "C:\\reports\\demo", "all")).toBe(true);
    expect(matchesObject(special, "first\nsecond", "metadata")).toBe(true);
  });
  it("searches only the chosen scope, with literal nested metadata text", () => {
    expect(matchesObject(file, "cloud COMPUTING", "metadata")).toBe(true);
    expect(matchesObject(file, "reviewed", "metadata")).toBe(true);
    expect(matchesObject(file, "false", "metadata")).toBe(true);
    expect(matchesObject(file, "cloud", "name")).toBe(false);
    expect(matchesObject(file, "123", "id")).toBe(true);
    expect(matchesObject(file, "[", "all")).toBe(false);
    expect(matchesObject(file, "  ", "all")).toBe(true);
  });
  it("quotes CSV cells and neutralizes formula prefixes even after whitespace", () => {
    const csv = listingCsv([
      file,
      { ...file, name: ' \t+malicious\n"quoted"' },
    ]);
    expect(csv).toContain('"\'=SUM(1,2).txt"');
    expect(csv).toContain('"\' \t+malicious\n""quoted"""');
    expect(csv).toContain('"12"');
    expect(csv).toContain("Cloud computing");
  });
});
