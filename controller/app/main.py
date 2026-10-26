from fastapi import FastAPI

app = FastAPI(
    title="Mini Distributed Object Store - Controller",
    version="0.1.0",
)


@app.get("/health")
def health():
    return {
        "status": "ok",
        "service": "controller",
    }