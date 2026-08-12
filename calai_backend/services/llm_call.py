"""ADR-005 contract 5 — the single failure mode for every LLM surface in
this system.

`llm_call` is a single-shot, JSON-mode LLM call validated against a
caller-supplied Pydantic `schema`, with exactly one retry on malformed JSON
or schema-validation failure, then `raise ValueError`. This matches
`extract_request_fields`'s and `parse_meal`'s pre-existing failure contract
(both used to raise `ValueError` on the *first* failure, zero retries) — the
one retry is a pure improvement, not a contract change, since callers
already translate `ValueError` -> HTTP 422 (`agent_service.py`'s
`_run_agent_orchestrator`).

No exponential backoff, no second retry: a malformed JSON-mode response from
a small local model is usually a one-off decoding artifact, not a systematic
failure a second retry would fix. A persistent failure should surface as an
error, not be silently masked by more attempts.

Every invocation emits exactly one `TraceRecord` (services/trace.py),
including on the retry path (`retry_count=1`) and final failure
(`outcome="error"`).
"""
import json
import time
from datetime import datetime, timezone

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import HumanMessage
from pydantic import BaseModel, ValidationError

from calai_backend.logging_config import get_correlation_id, get_logger
from calai_backend.services.trace import TraceRecord, write_trace

log = get_logger(__name__)

# Exactly one retry, per ADR-005 contract 5 — total attempts = 2.
_MAX_ATTEMPTS = 2


class LLMCallResult(BaseModel):
    model_config = {"arbitrary_types_allowed": True}

    output: BaseModel
    raw_response: str
    latency_ms: float
    retry_count: int


def llm_call(name: str, prompt: str, schema: type[BaseModel], llm: BaseChatModel) -> LLMCallResult:
    """Invoke `llm` with `prompt`, parse the response as JSON, and validate
    it against `schema`. Retries exactly once on malformed JSON, non-object
    JSON, or schema-validation failure; raises `ValueError` if the retry
    also fails. `retry_count` on the returned `LLMCallResult` (and the
    emitted `TraceRecord`) is 0 if the first attempt succeeded, 1 if the
    retry fired (whether it succeeded or is the attempt that finally failed).
    """
    t_start = time.perf_counter()
    correlation_id = get_correlation_id()
    last_error: ValueError | None = None
    raw_response = ""
    parsed_for_trace: dict = {}

    for attempt in range(_MAX_ATTEMPTS):
        response = llm.invoke([HumanMessage(content=prompt)])
        raw_response = response.content

        try:
            data = json.loads(raw_response)
        except json.JSONDecodeError as e:
            last_error = ValueError(f"Model returned invalid JSON: {e}\nRaw: {raw_response[:300]}")
            data = None
        else:
            if not isinstance(data, dict):
                last_error = ValueError(f"Model returned non-object JSON: {raw_response[:300]}")
                data = None

        output = None
        if data is not None:
            try:
                output = schema(**data)
            except ValidationError as e:
                last_error = ValueError(f"Model returned data that failed schema validation: {e}")

        if output is not None:
            latency_ms = (time.perf_counter() - t_start) * 1000
            parsed_for_trace = output.model_dump(mode="json")
            log.debug(
                "llm_call ok name=%s latency_ms=%.1f retry_count=%d outcome=ok correlation_id=%s",
                name, latency_ms, attempt, correlation_id,
            )
            write_trace(TraceRecord(
                call_name=name,
                correlation_id=correlation_id,
                prompt=prompt,
                raw_response=raw_response,
                parsed_output=parsed_for_trace,
                latency_ms=latency_ms,
                retry_count=attempt,
                timestamp=datetime.now(timezone.utc),
                outcome="ok",
            ))
            return LLMCallResult(
                output=output, raw_response=raw_response, latency_ms=latency_ms, retry_count=attempt,
            )

        if attempt < _MAX_ATTEMPTS - 1:
            log.warning(
                "llm_call retry name=%s reason=%s correlation_id=%s",
                name, last_error, correlation_id,
            )

    latency_ms = (time.perf_counter() - t_start) * 1000
    log.debug(
        "llm_call failed name=%s latency_ms=%.1f retry_count=%d outcome=error correlation_id=%s",
        name, latency_ms, _MAX_ATTEMPTS - 1, correlation_id,
    )
    write_trace(TraceRecord(
        call_name=name,
        correlation_id=correlation_id,
        prompt=prompt,
        raw_response=raw_response,
        parsed_output=parsed_for_trace,
        latency_ms=latency_ms,
        retry_count=_MAX_ATTEMPTS - 1,
        timestamp=datetime.now(timezone.utc),
        outcome="error",
    ))
    assert last_error is not None
    raise last_error
