"""API contract regression tests for the extraction (ADR-003 Action Items
2-3). Confirms /api/calculate and /api/parse-meal's request/response
contracts are unchanged after routes.py was rewired to call
run_calc_pipeline / the (now-relocated) parse_meal_text.
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


def test_calculate_valid_payload_returns_200_with_expected_shape():
    response = client.post("/api/calculate", json=VALID_CALC_PAYLOAD)

    assert response.status_code == 200
    body = response.json()
    assert set(body.keys()) == {"bmr_kcal", "tdee_kcal", "calorie_goal_kcal"}
    assert all(isinstance(v, (int, float)) for v in body.values())
    # Sanity: goal=lose should produce a calorie_goal below tdee.
    assert body["calorie_goal_kcal"] < body["tdee_kcal"]


def test_calculate_invalid_gender_returns_422():
    payload = {**VALID_CALC_PAYLOAD, "gender": "other"}
    response = client.post("/api/calculate", json=payload)

    assert response.status_code == 422


def test_parse_meal_returns_meal_parse_response_shape(monkeypatch):
    fake_result = {
        "items": [
            {
                "name": "apple",
                "quantity": 1,
                "unit": "piece",
                "calories_kcal": 95,
                "protein_g": 0.5,
                "carbs_g": 25,
                "fat_g": 0.3,
                "confidence": "high",
            }
        ],
        "total_kcal": 95,
        "meal_type": "snack",
    }
    monkeypatch.setattr(routes, "parse_meal_text", lambda meal_text, meal_type: fake_result)

    response = client.post("/api/parse-meal", json={"meal_text": "an apple", "meal_type": "snack"})

    assert response.status_code == 200
    body = response.json()
    assert set(body.keys()) == {"items", "total_kcal", "meal_type", "model_latency_ms"}
    assert body["total_kcal"] == 95
    assert body["meal_type"] == "snack"
    assert isinstance(body["model_latency_ms"], (int, float))
    assert body["model_latency_ms"] >= 0
    assert body["items"][0]["name"] == "apple"


# ---------------------------------------------------------------------------
# /api/agent — ADR-003 Action Items 5-6 route-wiring regression test.
#
# Mocks run_agent itself (the name routes.py imports it as) so this is a
# pure route-wiring check: confirms /api/agent still returns 200 with the
# AgentResponse shape unchanged, regardless of whether run_agent internally
# uses the Orchestrator or the old ReAct loop. Orchestrator/ReAct-loop
# internals are covered in test_agent_service.py.
# ---------------------------------------------------------------------------

def test_agent_route_returns_200_with_agent_response_shape(monkeypatch):
    from calai_backend.schemas import AgentResponse

    monkeypatch.setattr(
        routes, "run_agent",
        lambda message, llm, profile=None, trigger="message": AgentResponse(
            response="hello back", iterations_used=1
        ),
    )

    response = client.post("/api/agent", json={"message": "hi"})

    assert response.status_code == 200
    body = response.json()
    # ADR-007: AgentResponse gained message_type + 4 optional payload fields
    # (additive). A response built without them still defaults message_type
    # to "info" and all four payloads to None.
    assert set(body.keys()) == {
        "response",
        "iterations_used",
        "message_type",
        "slot_fill",
        "profile_confirmation",
        "recommendation",
        "weekly_checkin",
    }
    assert body["response"] == "hello back"
    assert body["iterations_used"] == 1
    assert body["message_type"] == "info"
    assert body["slot_fill"] is None
    assert body["profile_confirmation"] is None
    assert body["recommendation"] is None
    assert body["weekly_checkin"] is None
