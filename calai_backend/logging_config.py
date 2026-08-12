"""ADR-005 contract 6 — shared logging/correlation-id infra.

Every module that needs a logger gets one via `get_logger(__name__)`.
`bind_correlation_id` is called once per request, at the top of
`services/agent_service.py::_run_agent_orchestrator`, so every log line and
every `TraceRecord` (services/trace.py) emitted while handling that request
reads the same correlation id from the contextvar below, without threading
it explicitly through every function's parameter list.
"""
import contextvars
import logging
import uuid
from contextlib import contextmanager
from typing import Iterator, Optional

_correlation_id_var: contextvars.ContextVar[str] = contextvars.ContextVar(
    "correlation_id", default="-"
)


def get_logger(name: str) -> logging.Logger:
    """Thin wrapper over logging.getLogger — the single place every module
    in calai_backend should get its logger from, per ADR-005 contract 6."""
    return logging.getLogger(name)


@contextmanager
def bind_correlation_id(cid: Optional[str] = None) -> Iterator[str]:
    """Bind a correlation id to the current context for the duration of the
    `with` block. Generates a UUID4 if `cid` is not supplied. Intended to be
    used exactly once per request, at the top of `_run_agent_orchestrator`.
    """
    correlation_id = cid or str(uuid.uuid4())
    token = _correlation_id_var.set(correlation_id)
    try:
        yield correlation_id
    finally:
        _correlation_id_var.reset(token)


def get_correlation_id() -> str:
    """Read the correlation id bound by the nearest enclosing
    `bind_correlation_id` context. Returns "-" if none is bound (e.g. code
    paths exercised directly in tests, outside a request context)."""
    return _correlation_id_var.get()
