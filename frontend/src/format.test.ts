import { describe, expect, it } from "vitest";
import { bytes, parseMetadata, fileKind, seenAgo } from "./format";

describe("storage display and metadata boundary", () => {
  it("does not call a future heartbeat fresh", () => {
    expect(seenAgo(-5)).toBe("Clock mismatch");
  });
  it("uses decimal units matching controller chunk sizing", () => {
    expect(bytes(0)).toBe("0 B");
    expect(bytes(1_000_000)).toBe("1 MB");
    expect(bytes(2_500_000)).toBe("2.5 MB");
  });
  it("accepts JSON metadata without changing value types", () => {
    expect(
      parseMetadata('{"course":"CC","reviewed":true,"nested":{"n":2}}'),
    ).toEqual({ course: "CC", reviewed: true, nested: { n: 2 } });
  });
  it.each(["[]", "null", "{bad", '{"size":4}', '{"x":1e400}'])(
    "rejects invalid or reserved metadata: %s",
    (text) => {
      expect(() => parseMetadata(text)).toThrow();
    },
  );
  it("checks the encoded byte limit, including non-ASCII characters", () => {
    expect(() =>
      parseMetadata(JSON.stringify({ value: "é".repeat(20_000) })),
    ).toThrow();
  });
  it("classifies files using MIME without assuming every extension is a document", () => {
    expect(fileKind("image/png")).toBe("Image");
    expect(fileKind("application/octet-stream")).toBe("File");
    expect(fileKind("application/zip")).toBe("Archive");
  });
});
