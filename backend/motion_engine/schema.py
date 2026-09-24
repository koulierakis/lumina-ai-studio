from __future__ import annotations
from enum import Enum
from pydantic import BaseModel, Field

class JointName(str, Enum):
    HEAD="HEAD"; NECK="NECK"; LEFT_SHOULDER="LEFT_SHOULDER"; RIGHT_SHOULDER="RIGHT_SHOULDER"
    LEFT_ELBOW="LEFT_ELBOW"; RIGHT_ELBOW="RIGHT_ELBOW"; LEFT_WRIST="LEFT_WRIST"; RIGHT_WRIST="RIGHT_WRIST"
    PELVIS="PELVIS"; LEFT_HIP="LEFT_HIP"; RIGHT_HIP="RIGHT_HIP"; LEFT_KNEE="LEFT_KNEE"; RIGHT_KNEE="RIGHT_KNEE"
    LEFT_ANKLE="LEFT_ANKLE"; RIGHT_ANKLE="RIGHT_ANKLE"; SPINE="SPINE"; LEFT_FOOT="LEFT_FOOT"; RIGHT_FOOT="RIGHT_FOOT"

class MovementFamily(str, Enum):
    SQUAT_PATTERN="SQUAT_PATTERN"

class Phase(str, Enum):
    START="START"; EXECUTION="EXECUTION"; RETURN="RETURN"

class Joint(BaseModel):
    x: float; y: float; z: float|None=None
    confidence: float|None=Field(default=None, ge=0, le=1)

class PoseProvenance(BaseModel):
    source_type: str
    confidence: str
    note: str=""

class CanonicalPose(BaseModel):
    joints: dict[JointName, Joint]
    provenance: PoseProvenance
    frame_index: int|None=None
    def joint(self, name: JointName) -> Joint|None:
        return self.joints.get(name)
