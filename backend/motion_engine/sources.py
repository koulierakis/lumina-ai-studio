from __future__ import annotations
from abc import ABC, abstractmethod
from .schema import CanonicalPose, Joint, JointName, Phase, PoseProvenance

class PoseSource(ABC):
    @abstractmethod
    def load(self, exercise_id: str) -> dict[Phase, CanonicalPose]: ...

def _pose(points: dict[JointName, tuple[float,float]], note: str) -> CanonicalPose:
    return CanonicalPose(joints={k:Joint(x=x,y=y,confidence=1.0) for k,(x,y) in points.items()},
        provenance=PoseProvenance(source_type="manual_reference", confidence="verified_reference", note=note))

class BodyweightSquatReferenceSource(PoseSource):
    """Explicit PoC reference poses. They are manual references, not dataset-derived motion."""
    def load(self, exercise_id: str) -> dict[Phase, CanonicalPose]:
        if exercise_id != "bodyweight_squat": raise KeyError(exercise_id)
        start={JointName.HEAD:(.5,.10),JointName.NECK:(.5,.18),JointName.LEFT_SHOULDER:(.43,.21),JointName.RIGHT_SHOULDER:(.57,.21),
        JointName.LEFT_ELBOW:(.41,.34),JointName.RIGHT_ELBOW:(.59,.34),JointName.LEFT_WRIST:(.40,.46),JointName.RIGHT_WRIST:(.60,.46),
        JointName.PELVIS:(.5,.50),JointName.LEFT_HIP:(.46,.49),JointName.RIGHT_HIP:(.54,.49),JointName.LEFT_KNEE:(.45,.70),
        JointName.RIGHT_KNEE:(.55,.70),JointName.LEFT_ANKLE:(.44,.91),JointName.RIGHT_ANKLE:(.56,.91)}
        execution={JointName.HEAD:(.5,.20),JointName.NECK:(.5,.28),JointName.LEFT_SHOULDER:(.42,.31),JointName.RIGHT_SHOULDER:(.58,.31),
        JointName.LEFT_ELBOW:(.38,.42),JointName.RIGHT_ELBOW:(.62,.42),JointName.LEFT_WRIST:(.43,.48),JointName.RIGHT_WRIST:(.57,.48),
        JointName.PELVIS:(.5,.57),JointName.LEFT_HIP:(.45,.56),JointName.RIGHT_HIP:(.55,.56),JointName.LEFT_KNEE:(.38,.70),
        JointName.RIGHT_KNEE:(.62,.70),JointName.LEFT_ANKLE:(.36,.91),JointName.RIGHT_ANKLE:(.64,.91)}
        return {Phase.START:_pose(start,"Manual Bodyweight Squat standing reference"),
                Phase.EXECUTION:_pose(execution,"Manual Bodyweight Squat deepest-valid reference"),
                Phase.RETURN:_pose(start,"Manual Bodyweight Squat return reference")}
