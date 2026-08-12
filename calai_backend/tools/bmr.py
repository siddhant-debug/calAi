def calculate_bmr(weight_kg: float, height_cm: float, age: int, gender: str) -> float:
    if gender not in ("male", "female"):
        raise ValueError("gender must be 'male' or 'female'")
    if gender == "male":
        return round(10 * weight_kg + 6.25 * height_cm - 5 * age + 5, 1)
    return round(10 * weight_kg + 6.25 * height_cm - 5 * age - 161, 1)
