def calculate_calorie_goal(tdee_kcal: float, goal: str, goal_rate_kg_per_week: float = 0.5) -> float:
    if goal not in ("lose", "maintain", "gain"):
        raise ValueError("goal must be 'lose', 'maintain', or 'gain'")
    daily_delta = (goal_rate_kg_per_week * 7700) / 7
    if goal == "lose":
        return round(tdee_kcal - daily_delta, 1)
    if goal == "gain":
        return round(tdee_kcal + daily_delta, 1)
    return round(tdee_kcal, 1)
