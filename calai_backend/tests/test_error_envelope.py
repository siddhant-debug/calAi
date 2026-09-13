"""Regression coverage for the normalized error envelope (main.py's
HTTPException / RequestValidationError exception handlers).

Before this change, hand-rolled `HTTPException(detail="...")` calls
(routes.py) produced `{"detail": "<string>"}` while FastAPI's own
request-validation 422s produced `{"detail": [{"loc":..., "msg":...,
"type":...}, ...]}` -- two incompatible shapes under the same top-level
key. Both are now normalized to:

    {"detail": {"message": "<str>", "errors": <list[dict] | null>}}

`errors` is populated only for request-validation failures; it is `None`
for hand-rolled HTTPExceptions. HTTP status codes are unchanged.
"""
from fastapi.testclient import TestClient

from calai_backend.api import routes
from calai_backend.main import app

client = TestClient(app)

VALID_CALC_PAYLOAD = {
    "weight_kg": 75,
    "height_cm": 178,
    "age": 30,
    "gender": "male",
    "activity_level": "moderately_active",
    "goal": "lose",
    "goal_rate_kg_per_week": 0.5,
}


# ---------------------------------------------------------------------------
# Hand-rolled HTTPException -> {"detail": {"message": str, "errors": None}}
# ---------------------------------------------------------------------------

def test_calculate_value_error_normalizes_to_message_errors_null_envelope(monkeypatch):
    """routes.py's /api/calculate handler does:
        except ValueError as e: raise HTTPException(status_code=422, detail=str(e))
    This is the hand-rolled-exception path. Before normalization the body
    would be {"detail": "boom, invalid input"} (a bare string).
    """
    def boom(profile):
        raise ValueError("boom, invalid input")

    monkeypatch.setattr(routes, "run_calc_pipeline", boom)

    response = client.post("/api/calculate", json=VALID_CALC_PAYLOAD)

    assert response.status_code == 422
    body = response.json()
    assert body == {"detail": {"message": "boom, invalid input", "errors": None}}


def test_parse_meal_connect_error_normalizes_envelope_and_keeps_503(monkeypatch):
    """routes.py's /api/parse-meal handler maps httpx.ConnectError to a
    hand-rolled HTTPException(status_code=503, detail=<str>). Confirms the
    envelope is normalized AND the pre-existing 503 status code survives
    normalization unchanged (only the body shape changed).
    """
    import httpx

    def raise_connect_error(meal_text, meal_type):
        raise httpx.ConnectError("connection refused")

    monkeypatch.setattr(routes, "parse_meal_text", raise_connect_error)

    response = client.post("/api/parse-meal", json={"meal_text": "an apple", "meal_type": "snack"})

    assert response.status_code == 503
    body = response.json()
    assert body["detail"]["errors"] is None
    assert isinstance(body["detail"]["message"], str)
    assert "NVIDIA NIM" in body["detail"]["message"]


# ---------------------------------------------------------------------------
# FastAPI RequestValidationError -> {"detail": {"message": str, "errors": [...]}}
# ---------------------------------------------------------------------------

def test_calculate_invalid_activity_level_returns_normalized_validation_envelope():
    """An invalid `activity_level` (not one of the Literal values) fails
    pydantic validation before the route body ever runs, going through
    FastAPI's RequestValidationError handler -- the other of the two
    previously-incompatible shapes.
    """
    payload = {**VALID_CALC_PAYLOAD, "activity_level": "extremely_active_typo"}

    response = client.post("/api/calculate", json=payload)

    assert response.status_code == 422
    body = response.json()
    detail = body["detail"]
    assert isinstance(detail["message"], str) and detail["message"]
    assert isinstance(detail["errors"], list)
    assert len(detail["errors"]) > 0
    for error in detail["errors"]:
        assert {"loc", "msg", "type"} <= error.keys()


def test_calculate_missing_required_field_returns_normalized_validation_envelope():
    """Missing a required field (weight_kg) is also a RequestValidationError,
    not a hand-rolled HTTPException -- same normalized shape, non-empty
    `errors` list.
    """
    payload = {k: v for k, v in VALID_CALC_PAYLOAD.items() if k != "weight_kg"}

    response = client.post("/api/calculate", json=payload)

    assert response.status_code == 422
    body = response.json()
    detail = body["detail"]
    assert detail["message"] == "Request validation failed."
    assert isinstance(detail["errors"], list)
    assert len(detail["errors"]) > 0
    assert any(err["loc"][-1] == "weight_kg" for err in detail["errors"])


def test_calculate_negative_weight_returns_normalized_validation_envelope():
    """weight_kg has `gt=0`; a negative value is a field-constraint failure,
    still routed through RequestValidationError (not a hand-rolled 422).
    """
    payload = {**VALID_CALC_PAYLOAD, "weight_kg": -1}

    response = client.post("/api/calculate", json=payload)

    assert response.status_code == 422
    body = response.json()
    detail = body["detail"]
    assert isinstance(detail["errors"], list)
    assert len(detail["errors"]) > 0
    assert any(err["loc"][-1] == "weight_kg" for err in detail["errors"])
