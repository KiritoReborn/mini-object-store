import os

from fastapi import FastAPI

WORKER_ID = os.getenv("WORKER_ID", "worker-local")

app = FastAPI(
    title=f"Storage Worker - {WORKER_ID}",
    version="0.1.0",
)


@app.get("/health")
def health():
    return {
        "status": "ok",
        "service": "worker",
        "worker_id": WORKER_ID,
    }