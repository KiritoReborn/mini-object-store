import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import {
  compareFileDigest,
  hashFile,
  integrityReport,
  localHashUnavailable,
  MAX_INTEGRITY_FILE_BYTES,
  type HashProgress,
} from "./integrity";

const EMPTY =
  "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855";
const ABC = "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad";
const file = { name: "downloaded.txt", size: 3, sha256: ABC };

beforeEach(() => vi.stubGlobal("isSecureContext", true));
afterEach(() => {
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});

describe("local SHA-256", () => {
  it.each([
    ["", EMPTY],
    ["abc", ABC],
  ])("hashes the known vector %j", async (text, sha256) => {
    expect(await hashFile(new File([text], "vector.txt"))).toEqual({
      name: "vector.txt",
      size: text.length,
      sha256,
    });
  });

  it("hashes the million-a vector across multiple read chunks with progress", async () => {
    const file = new File(["a".repeat(1_000_000)], "million-a.bin");
    const read = vi.spyOn(file, "slice");
    const progress: HashProgress[] = [];
    expect(
      (await hashFile(file, { onProgress: (value) => progress.push(value) }))
        .sha256,
    ).toBe("cdc76e5c9914fb9281a1c7e284d73e67f1809a48a497200e046d39ccc7112cd0");
    expect(read.mock.calls.length).toBeGreaterThan(1);
    expect(progress[0]).toEqual({
      phase: "reading",
      bytesRead: 0,
      totalBytes: 1_000_000,
    });
    expect(progress.at(-1)).toEqual({
      phase: "hashing",
      bytesRead: 1_000_000,
      totalBytes: 1_000_000,
    });
  });

  it("rejects oversized files before reading them", async () => {
    const file = new File(["not read"], "large.bin");
    vi.spyOn(file, "size", "get").mockReturnValue(MAX_INTEGRITY_FILE_BYTES + 1);
    const read = vi.spyOn(file, "slice");
    await expect(hashFile(file)).rejects.toThrow("128 MiB");
    expect(read).not.toHaveBeenCalled();
  });

  it("stops between read chunks on cancellation", async () => {
    const controller = new AbortController();
    const file = new File(["a".repeat(1_000_000)], "cancel.bin");
    const read = vi.spyOn(file, "slice");
    await expect(
      hashFile(file, {
        signal: controller.signal,
        onProgress: ({ phase, bytesRead }) => {
          if (phase === "reading" && bytesRead > 0) controller.abort();
        },
      }),
    ).rejects.toMatchObject({ name: "AbortError" });
    expect(read).toHaveBeenCalledTimes(1);
  });

  it("discards a late digest after cancellation", async () => {
    let finish!: (value: ArrayBuffer) => void;
    vi.stubGlobal("crypto", {
      subtle: {
        digest: () =>
          new Promise<ArrayBuffer>((resolve) => {
            finish = resolve;
          }),
      },
    });
    const controller = new AbortController();
    const pending = hashFile(new File([], "empty.txt"), {
      signal: controller.signal,
    });
    controller.abort();
    finish(new ArrayBuffer(32));
    await expect(pending).rejects.toMatchObject({ name: "AbortError" });
  });

  it("does not return a hash from a short read", async () => {
    const file = new File(["abc"], "changed.txt");
    vi.spyOn(file, "slice").mockReturnValue(new Blob(["a"]));
    await expect(hashFile(file)).rejects.toThrow("file changed");
  });

  it("explains insecure contexts and missing Web Crypto without reading files", async () => {
    const file = new File(["abc"], "not-read.txt");
    const read = vi.spyOn(file, "slice");
    vi.stubGlobal("isSecureContext", false);
    expect(localHashUnavailable()).toContain("HTTPS or localhost");
    await expect(hashFile(file)).rejects.toThrow("HTTPS or localhost");
    vi.stubGlobal("isSecureContext", true);
    vi.stubGlobal("crypto", {});
    await expect(hashFile(file)).rejects.toThrow("Web Crypto");
    expect(read).not.toHaveBeenCalled();
  });
});

describe("verification against the stored checksum", () => {
  it("matches a single file using its SHA-256 regardless of filename", () => {
    expect(compareFileDigest(file, ABC)).toBe("MATCH");
    expect(compareFileDigest({ ...file, name: "original.txt" }, ABC)).toBe(
      "MATCH",
    );
    expect(
      compareFileDigest({ name: "empty.txt", size: 0, sha256: EMPTY }, EMPTY),
    ).toBe("MATCH");
  });

  it("mismatches when the selected file has a different SHA-256", async () => {
    const wrong = await hashFile(new File(["xyz"], file.name));
    expect(wrong.size).toBe(file.size);
    expect(compareFileDigest(wrong, ABC)).toBe("MISMATCH");
  });

  it("exports one selection, the stored checksum, and an ISO timestamp", () => {
    const timestamp = "2026-11-16T08:00:00.000Z";
    const fileWithContents = {
      ...file,
      contents: "never-export-local-file-bytes",
    };
    const report = integrityReport(fileWithContents, ABC, timestamp);
    expect(report).toEqual({
      timestamp,
      algorithm: "SHA-256",
      scope: "Local file verification against stored object checksum",
      file,
      expected_hash: ABC,
      result: "MATCH",
    });
    expect(JSON.stringify(report)).not.toContain(fileWithContents.contents);
    expect(Number.isNaN(Date.parse(integrityReport(file, ABC).timestamp))).toBe(
      false,
    );
    expect(integrityReport(file, EMPTY).result).toBe("MISMATCH");
  });
});
