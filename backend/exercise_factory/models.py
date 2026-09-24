from __future__ import annotations
from enum import Enum
from typing import Any
from pydantic import BaseModel, ConfigDict, Field
from models import new_id, now_iso

class FactoryStatus(str, Enum):
    PENDING="PENDING"; GENERATING="GENERATING"; GENERATED="GENERATED"; APPROVED="APPROVED"; RETRY="RETRY"; FAILED="FAILED"

class FactoryPhase(str, Enum):
    START="START"; EXECUTION="EXECUTION"; RETURN="RETURN"

class FactoryPhaseState(BaseModel):
    model_config=ConfigDict(extra="ignore")
    phase: FactoryPhase
    status: FactoryStatus=FactoryStatus.PENDING
    pose_media_id: str|None=None
    output_media_id: str|None=None
    error: str|None=None
    attempts: int=0
    metadata: dict[str,Any]=Field(default_factory=dict)
    updated_at: str=Field(default_factory=now_iso)

class ExerciseFactoryJob(BaseModel):
    model_config=ConfigDict(extra="ignore")
    id: str=Field(default_factory=new_id)
    owner_email: str
    exercise_id: str="bodyweight_squat"
    exercise_name: str="Bodyweight Squat"
    movement_family: str="SQUAT_PATTERN"
    identity_pack_id: str
    image_provider: str|None=None
    output_resolution: str="1024"
    phases: dict[FactoryPhase,FactoryPhaseState]=Field(default_factory=lambda:{p:FactoryPhaseState(phase=p) for p in FactoryPhase})
    created_at: str=Field(default_factory=now_iso)
    updated_at: str=Field(default_factory=now_iso)
