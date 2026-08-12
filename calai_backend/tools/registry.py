from langchain_core.tools import tool

from calai_backend.tools.bmr import calculate_bmr
from calai_backend.tools.calorie_goal import calculate_calorie_goal
from calai_backend.tools.meal_parser import parse_meal_text
from calai_backend.tools.tdee import calculate_tdee


@tool("calculate_bmr")
def _bmr_tool(weight_kg: float, height_cm: float, age: int, gender: str) -> float:
    """Calculate Basal Metabolic Rate using Mifflin-St Jeor. gender must be 'male' or 'female'."""
    return calculate_bmr(weight_kg, height_cm, age, gender)


@tool("calculate_tdee")
def _tdee_tool(bmr_kcal: float, activity_level: str) -> float:
    """Calculate Total Daily Energy Expenditure.
    activity_level must be one of: sedentary, lightly_active, moderately_active, very_active, extra_active."""
    return calculate_tdee(bmr_kcal, activity_level)


@tool("calculate_calorie_goal")
def _calorie_goal_tool(tdee_kcal: float, goal: str, goal_rate_kg_per_week: float = 0.5) -> float:
    """Calculate daily calorie goal. goal must be 'lose', 'maintain', or 'gain'.
    goal_rate_kg_per_week is ignored when goal is 'maintain'."""
    return calculate_calorie_goal(tdee_kcal, goal, goal_rate_kg_per_week)


@tool("parse_meal_text")
def _parse_meal_tool(meal_text: str, meal_type: str = "snack") -> dict:
    """Parse a natural-language meal description into structured nutrition data.
    meal_type: breakfast, lunch, dinner, or snack."""
    return parse_meal_text(meal_text, meal_type)


_TOOLS = [_bmr_tool, _tdee_tool, _calorie_goal_tool, _parse_meal_tool]
_TOOLS_DICT = {t.name: t for t in _TOOLS}


def get_tools() -> list:
    return list(_TOOLS)


def get_dict() -> dict:
    return dict(_TOOLS_DICT)
