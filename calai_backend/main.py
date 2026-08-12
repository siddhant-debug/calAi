import logging

from fastapi import FastAPI

from calai_backend.api.routes import router

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(name)s  %(message)s",
    datefmt="%H:%M:%S",
)

app = FastAPI(title="CalAI API", version="0.1.0")
app.include_router(router, prefix="/api")


@app.get("/api/health")
def health():
    return {"status": "ok"}
