from .registry import movement_family_for
from .rules import SquatRule
from .schema import MovementFamily, Phase
from .sources import BodyweightSquatReferenceSource

def build_bodyweight_squat_poc():
    exercise_id="bodyweight_squat"; family=movement_family_for(exercise_id)
    refs=BodyweightSquatReferenceSource().load(exercise_id)
    if family is not MovementFamily.SQUAT_PATTERN: raise ValueError("Bodyweight Squat must use SQUAT_PATTERN")
    ordered=[refs[Phase.START],refs[Phase.EXECUTION],refs[Phase.RETURN]]
    phases=SquatRule().classify(ordered)
    return {"exercise_id":exercise_id,"exercise_name":"Bodyweight Squat","movement_family":family,"phases":phases}
