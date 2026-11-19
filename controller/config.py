"""Environment settings shared with Member B's recovery implementation."""
import os
from pathlib import Path


def _positive(name: str, default: str, cast=int):
    value = cast(os.getenv(name, default))
    if value <= 0:
        raise ValueError(f"{name} must be positive")
    return value


CHUNK_SIZE = _positive("CHUNK_SIZE", "1000000")
REPLICATION_FACTOR = 2
WORKER_DEAD_TIMEOUT = _positive("WORKER_DEAD_TIMEOUT", "15", float)
RECONCILE_INTERVAL = _positive("RECONCILE_INTERVAL", "5", float)
HTTP_TIMEOUT = _positive("HTTP_TIMEOUT", "5", float)
DATABASE_PATH = os.getenv("DATABASE_PATH", "/data/metadata.db")
DOWNLOAD_TEMP_DIR = Path(os.getenv("DOWNLOAD_TEMP_DIR", str(Path(DATABASE_PATH).parent / "downloads")))
MAX_METADATA_BYTES = 32_768
API_KEY = os.getenv("ARTAUD_API_KEY", "")
ALLOWED_ORIGINS = [value.strip().rstrip("/") for value in os.getenv("ARTAUD_ALLOWED_ORIGINS", "").split(",") if value.strip()]
DEMO_CONTROLS = os.getenv("ARTAUD_DEMO_CONTROLS", "false").lower() == "true"
DEMO_FAULT_INJECTION = os.getenv("ARTAUD_DEMO_FAULT_INJECTION") == "1"
DOCKER_PROJECT = os.getenv("ARTAUD_DOCKER_PROJECT", "mini-object-store")
if API_KEY and len(API_KEY) < 32:
    raise ValueError("ARTAUD_API_KEY must contain at least 32 characters")
if DEMO_CONTROLS and not API_KEY:
    raise ValueError("Demo controls require ARTAUD_API_KEY")
