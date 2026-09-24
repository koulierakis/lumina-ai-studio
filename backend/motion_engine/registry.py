from .schema import MovementFamily
_EXERCISES={"bodyweight_squat": MovementFamily.SQUAT_PATTERN}
def movement_family_for(exercise_id: str) -> MovementFamily:
    try: return _EXERCISES[exercise_id.strip().lower()]
    except KeyError as exc: raise KeyError(f"Unknown exercise: {exercise_id}") from exc
