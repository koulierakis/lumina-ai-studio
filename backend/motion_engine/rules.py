from __future__ import annotations
import math
from abc import ABC, abstractmethod
from .schema import CanonicalPose, JointName, Phase

def _angle(a,b,c):
    ba=(a.x-b.x,a.y-b.y); bc=(c.x-b.x,c.y-b.y)
    den=math.hypot(*ba)*math.hypot(*bc)
    if not den: return None
    return math.degrees(math.acos(max(-1,min(1,(ba[0]*bc[0]+ba[1]*bc[1])/den))))

class BiomechanicalRule(ABC):
    @abstractmethod
    def classify(self, frames:list[CanonicalPose])->dict[Phase,CanonicalPose]: ...

class SquatRule(BiomechanicalRule):
    """Selects phases using bilateral knee/hip flexion plus torso geometry, never raw min(Y)."""
    def _score(self,p):
        vals=[]
        for side in ("LEFT","RIGHT"):
            hip=p.joint(JointName[f"{side}_HIP"]); knee=p.joint(JointName[f"{side}_KNEE"]); ankle=p.joint(JointName[f"{side}_ANKLE"])
            shoulder=p.joint(JointName[f"{side}_SHOULDER"])
            if hip and knee and ankle:
                ka=_angle(hip,knee,ankle)
                if ka is not None: vals.append(180-ka)
            if shoulder and hip and knee:
                ha=_angle(shoulder,hip,knee)
                if ha is not None: vals.append((180-ha)*.65)
        neck=p.joint(JointName.NECK); pelvis=p.joint(JointName.PELVIS)
        if neck and pelvis:
            dx=abs(neck.x-pelvis.x); dy=abs(neck.y-pelvis.y)
            vals.append(max(0,45-math.degrees(math.atan2(dy,dx if dx else 1e-9)))*.15)
        if not vals: raise ValueError("Insufficient joints for squat biomechanics")
        return sum(vals)/len(vals)
    def classify(self,frames):
        if len(frames)<3: raise ValueError("At least three frames are required")
        scores=[self._score(p) for p in frames]
        peak=max(range(len(frames)),key=scores.__getitem__)
        before=list(range(0,peak+1)); after=list(range(peak,len(frames)))
        start=min(before,key=lambda i:scores[i])
        ret=min(after,key=lambda i:scores[i])
        return {Phase.START:frames[start],Phase.EXECUTION:frames[peak],Phase.RETURN:frames[ret]}
