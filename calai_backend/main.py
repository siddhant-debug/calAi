import logging

from fastapi import FastAPI, HTTPException, Request
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from calai_backend.api.routes import router

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(name)s  %(message)s",
    datefmt="%H:%M:%S",
)

log = logging.getLogger("calai.main")

app = FastAPI(title="CalAI API", version="0.1.0")
app.include_router(router, prefix="/api")


# ---------------------------------------------------------------------------
# One error envelope, always (rules/backend-facts.md).
#
# Hand-rolled `HTTPException(detail="...")` calls (routes.py, services/)
# yield {"detail": "..."} — a string. FastAPI's own request-validation
# failures (`RequestValidationError`, raised before a route body even runs)
# yield {"detail": [{"loc": ..., "msg": ..., "type": ...}, ...]} — a list of
# objects. Same top-level key, two incompatible shapes a client can't handle
# uniformly. Both handlers below normalize to a single shape:
#
#   {"detail": {"message": <str>, "errors": <list[dict] | null>}}
#
# - `message` is always a human-readable string (never null).
# - `errors` is the raw Pydantic error list when the failure was a request
#   validation error, otherwise null.
# - HTTP status codes are unchanged (400/404/422/500/502/503/504 etc. — this
#   only normalizes the body, not the status line).
# ---------------------------------------------------------------------------

@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException) -> JSONResponse:
    # Every current `HTTPException(...)` call site (routes.py, services/) passes a
    # bare string `detail` — there is no producer of an already-normalized dict
    # detail today, so we always build the envelope fresh here. If a future call
    # site needs to pass through a pre-built {"message": ..., "errors": ...} dict,
    # re-add that branch alongside a regression test for it.
    body = {"message": str(exc.detail), "errors": None}
    log.info(
        "http_exception_normalized path=%s status_code=%d message=%s",
        request.url.path, exc.status_code, body["message"],
    )
    return JSONResponse(status_code=exc.status_code, content={"detail": body}, headers=exc.headers)


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
    errors = jsonable_encoder(exc.errors())
    log.info(
        "request_validation_error_normalized path=%s status_code=%d error_count=%d",
        request.url.path, 422, len(errors),
    )
    return JSONResponse(
        status_code=422,
        content={"detail": {"message": "Request validation failed.", "errors": errors}},
    )


@app.get("/api/health")
def health():
    return {"status": "ok"}
