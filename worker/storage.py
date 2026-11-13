import hashlib
import logging
import os
import re
import tempfile
import threading
from pathlib import Path

from . import config

CHUNK_ID_RE = re.compile(
    r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}_[0-9]+"
)
HEX64_RE = re.compile(r"[0-9a-f]{64}")
ROOT = Path(config.STORAGE_PATH)
log = logging.getLogger("worker")

# One Uvicorn process owns each worker volume. Bound the number of locks even
# when clients send many distinct IDs; every operation uses the same stripe.
_locks = [threading.Lock() for _ in range(64)]


def _lock(chunk_id):
    return _locks[hash(chunk_id) % len(_locks)]


def valid_id(chunk_id):
    return CHUNK_ID_RE.fullmatch(chunk_id) is not None


def chunk_path(chunk_id):
    if not valid_id(chunk_id):
        raise ValueError("invalid chunk id")
    return ROOT / chunk_id


def sha_path(chunk_id):
    if not valid_id(chunk_id):
        raise ValueError("invalid chunk id")
    return ROOT / (chunk_id + ".sha256")


def sha256_hex(data):
    return hashlib.sha256(data).hexdigest()


def _fsync_dir():
    fd = os.open(ROOT, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def _write_atomic(path, data):
    fd, tmp = tempfile.mkstemp(dir=ROOT, suffix=".tmp")
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(data)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    finally:
        Path(tmp).unlink(missing_ok=True)


def cleanup_tmp():
    """Remove abandoned temporary files before accepting any requests."""
    removed = 0
    for path in ROOT.glob("*.tmp"):
        if path.is_file() or path.is_symlink():
            path.unlink(missing_ok=True)
            removed += 1
    if removed:
        _fsync_dir()
        log.info("CLEANUP worker=%s temporary_files=%s", config.WORKER_ID, removed)


def _read_sha(chunk_id):
    try:
        stored = sha_path(chunk_id).read_text(encoding="ascii").strip()
    except (FileNotFoundError, UnicodeError):
        return None
    return stored if HEX64_RE.fullmatch(stored) else None


def _check(chunk_id):
    """Caller holds the chunk lock; return (ok / missing / corrupt, data, sha)."""
    try:
        data = chunk_path(chunk_id).read_bytes()
    except FileNotFoundError:
        return "missing", None, None
    stored = _read_sha(chunk_id)
    if stored is None or sha256_hex(data) != stored:
        return "corrupt", None, None
    return "ok", data, stored


def check(chunk_id):
    with _lock(chunk_id):
        return _check(chunk_id)


def put(chunk_id, data, sha):
    with _lock(chunk_id):
        state, _, old_sha = _check(chunk_id)
        if state == "ok":
            if old_sha != sha:
                return "conflict"
            # A prior attempt may have committed both names but failed to sync
            # the directory. An acknowledged retry must finish that commit.
            _fsync_dir()
            return "exists"
        # Data first: interruption before the sidecar commit fails verification.
        _write_atomic(chunk_path(chunk_id), data)
        _write_atomic(sha_path(chunk_id), sha.encode("ascii"))
        _fsync_dir()
        return "created"


def delete(chunk_id):
    with _lock(chunk_id):
        for p in (chunk_path(chunk_id), sha_path(chunk_id)):
            p.unlink(missing_ok=True)
        _fsync_dir()


def inventory():
    out = []
    for p in ROOT.iterdir():
        if not valid_id(p.name):  # skips .sha256 and .tmp files
            continue
        with _lock(p.name):
            try:
                if not p.is_file():
                    continue
                size = p.stat().st_size
            except FileNotFoundError:
                continue
            out.append({
                "chunk_id": p.name,
                "size": size,
                "sha256": _read_sha(p.name),
            })
    return out
