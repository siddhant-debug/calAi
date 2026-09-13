from calai_backend.services.meal_parse_agent import parse_meal


def parse_meal_text(meal_text: str, meal_type: str = "snack") -> dict:
    """Parse a natural-language meal description into structured nutrition data.

    Thin wrapper preserving the plain-function tool convention
    (this module stays plain; the @tool wrapper around it lives in
    calai_backend/tools/registry.py). Actual prompt construction, LLM call, and JSON
    validation now live in calai_backend/services/meal_parse_agent.py::parse_meal
    (ADR-003 Action Item 3).
    """
    return parse_meal(meal_text, meal_type)
