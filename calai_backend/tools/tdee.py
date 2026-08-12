ACTIVITY_MULTIPLIERS = {
    "sedentary": 1.2,
    "lightly_active": 1.375,
    "moderately_active": 1.55,
    "very_active": 1.725,
    "extra_active": 1.9,
}


def calculate_tdee(bmr_kcal: float, activity_level: str) -> float:
    if activity_level not in ACTIVITY_MULTIPLIERS:
        raise ValueError(f"activity_level must be one of: {list(ACTIVITY_MULTIPLIERS.keys())}")
    return round(bmr_kcal * ACTIVITY_MULTIPLIERS[activity_level], 1)
