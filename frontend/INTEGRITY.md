# Local integrity comparison

Open a stored file from Files, stay on Details, and expand **Verify integrity**.
Choose the original and downloaded files, then select **Compare files**. The
expected SHA-256 starts with that object's stored checksum; it can be replaced
with a pasted hash or cleared. **Use object checksum** restores it.

Each file is limited to **128 MiB (134,217,728 bytes), inclusive**. Oversized
files are rejected before reading. Web Crypto requires a complete input buffer
and may make internal copies, so the tool processes one file at a time. It reads
in asynchronous 256 KiB slices with read progress, then shows an indeterminate
hashing state while the browser computes SHA-256 asynchronously. This tool is
intended for bounded demonstration files, not arbitrary-size integrity scans.

HTTPS or localhost and Web Crypto support are required. Empty files are valid.
Closing a picker preserves the selection; changing either file clears results.
Cancel, replacement selections and closing the inspector invalidate outstanding
work. Web Crypto's digest itself cannot be aborted, so late results are ignored.
Selecting the same file twice is allowed and will match; it does not establish
that an upload/download round trip occurred.

**MATCH** requires equal file sizes and SHA-256 hashes. Each file's comparison
with the optional expected hash is reported separately. The JSON export contains
only file names, sizes, hashes, expected-hash comparisons, the two-file result,
and an ISO timestamp marking report generation. It is local comparison evidence,
not a live audit of worker replicas or a signed server attestation.

This feature makes no API requests, logs no file names or hashes, and sends no
file contents to the controller, telemetry or other services. It uses only
existing frontend dependencies. The surrounding dashboard keeps its existing
API behavior.
