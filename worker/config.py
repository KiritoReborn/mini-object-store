import os

WORKER_ID = os.getenv("WORKER_ID", "").strip()
if not WORKER_ID:
    raise RuntimeError("WORKER_ID must be set to a non-empty worker identifier")

CONTROLLER_URL = os.getenv("CONTROLLER_URL", "http://controller:8000")
WORKER_PORT = 8001  # Must match the Uvicorn port in Dockerfile.worker.
BASE_URL = os.getenv("WORKER_BASE_URL", f"http://{WORKER_ID}:{WORKER_PORT}")
STORAGE_PATH = os.getenv("WORKER_STORAGE_PATH", "/data/chunks")
CHUNK_SIZE = int(os.getenv("CHUNK_SIZE", "1000000"))
HEARTBEAT_INTERVAL = float(os.getenv("HEARTBEAT_INTERVAL", "5"))
ENABLE_FAULT_INJECTION = os.getenv("WORKER_ENABLE_FAULT_INJECTION") == "1"
