"""ADR-005 contract 6 — TraceRecord schema and append-only JSONL persistence.

One `TraceRecord` is emitted per `llm_call` invocation (services/llm_call.py),
including on the retry path (`retry_count=1`) and on final failure
(`outcome="error"`). Persisted append-only, one file per calendar day, at
`calai_backend/logs/traces/{date}.jsonl` — mirrors the `evals/dataset/*.jsonl`
convention already in this repo (same JSONL family, directly convertible to
eval data later).
"""
from datetime import datetime
from pathlib import Path
from typing import Literal

from pydantic import BaseModel

from calai_backend.logging_config import get_logger

log = get_logger(__name__)

TRACES_DIR = Path(__file__).resolve().parent.parent / "logs" / "traces"


class TraceRecord(BaseModel):
    call_name: str
    correlation_id: str
    prompt: str
    raw_response: str
    parsed_output: dict
    latency_ms: float
    retry_count: int
    timestamp: datetime
    outcome: Literal["ok", "needs_more_info", "fallback", "error"]


def write_trace(record: TraceRecord) -> None:
    """Append `record` as one JSON line to today's trace file.

    Creates `calai_backend/logs/traces/` if it doesn't exist yet. Uses
    `record.timestamp`'s date (not "now") to pick the file, so a record
    stamped just before midnight lands in the file matching its own
    timestamp.
    """
    TRACES_DIR.mkdir(parents=True, exist_ok=True)
    file_date = record.timestamp.date().isoformat()
    path = TRACES_DIR / f"{file_date}.jsonl"
    with path.open("a", encoding="utf-8") as f:
        f.write(record.model_dump_json())
        f.write("\n")
    log.debug("trace written call_name=%s correlation_id=%s outcome=%s path=%s",
               record.call_name, record.correlation_id, record.outcome, path)
