# Verify one local file against a stored checksum

Open a stored object from **Files**, stay on **Details**, and expand **Verify integrity**.
Choose one local file and select **Verify file**. The browser computes its SHA-256
and compares it with the checksum the controller recorded when the object was
uploaded. Choose a downloaded copy to check the bytes you retrieved. You can also
check your original file against the same stored object.

**MATCH** means the two SHA-256 values agree. **MISMATCH** means the selected
file's SHA-256 differs. The optional JSON report records the selected file's
name, size, computed SHA-256, the expected checksum, the result, and the time
the report was generated. It describes the selected file at verification time.

Files up to **128 MiB (134,217,728 bytes)** are accepted, including empty files.
The tool checks the limit before reading, reads in 256 KiB slices with progress,
and uses Web Crypto to hash the full buffer. Use HTTPS or localhost with Web
Crypto support.

Cancelling the file picker keeps the current selection and result. Selecting a
different file clears the result. Cancelling verification, replacing the
selection, or closing the inspector discards pending results. A Web Crypto
digest already in progress can finish internally.

The selected file stays in the browser. Only the object's existing metadata is
needed, and the tool sends no additional API requests.
