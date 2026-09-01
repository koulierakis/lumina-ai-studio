"""Coding-engine selection without removing the existing native Code Builder."""
from __future__ import annotations
from dataclasses import asdict,dataclass
from pathlib import Path
from typing import Final
from .openhands_engine import OpenHandsEngine
NATIVE_ENGINE:Final[str]="native";OPENHANDS_ENGINE:Final[str]="openhands"
@dataclass(frozen=True,slots=True)
class CodingEngineOption:name:str;available:bool;experimental:bool;safe_mode:bool
class CodingEngineRegistry:
    def __init__(self,openhands:OpenHandsEngine|None=None)->None:self.openhands=openhands or OpenHandsEngine()
    def options(self)->tuple[CodingEngineOption,...]:
        s=self.openhands.status();return(CodingEngineOption(NATIVE_ENGINE,True,False,True),CodingEngineOption(OPENHANDS_ENGINE,s.available,True,s.safe_mode))
    def public_status(self)->dict[str,object]:return{"default":NATIVE_ENGINE,"engines":[asdict(o)for o in self.options()]}
    def validate_selection(self,name:str|None)->str:
        n=(name or NATIVE_ENGINE).strip().lower()
        if n==NATIVE_ENGINE:return NATIVE_ENGINE
        if n==OPENHANDS_ENGINE:
            if not self.openhands.status().available:raise RuntimeError("OpenHands engine is not available on this machine.")
            return OPENHANDS_ENGINE
        raise ValueError(f"Unknown coding engine: {name}")
    def execute(self,*,engine:str|None,repository_root:str|Path,instruction:str):
        if self.validate_selection(engine)==OPENHANDS_ENGINE:return self.openhands.execute(repository_root=repository_root,instruction=instruction)
        raise RuntimeError("Native execution remains owned by the existing Code Builder task service.")
    def execute_for_review(self,*,engine:str|None,repository_root:str|Path,instruction:str)->dict[str,object]:
        result=self.execute(engine=engine,repository_root=repository_root,instruction=instruction);payload=result.public_summary();payload.update({"engine":OPENHANDS_ENGINE,"requires_approval":True,"safe_mode":True,"applied":False,"status":"awaiting_approval","can_apply":False,"source_repository_unchanged":True,"review_only":True,"message":"OpenHands finished in a safe copy. Review the proposed changes before LUMINA can apply anything.","next_action":"review_changes"});return payload
