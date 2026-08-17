from __future__ import annotations

import math
from typing import Literal

from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict, Field

from auth import require_owner

router = APIRouter(prefix="/api/drive", tags=["LUMINA Drive"])

HazardKind = Literal[
    "speed_limit",
    "fixed_camera",
    "curve",
    "school_zone",
    "roadworks",
    "road_hazard",
]


class DrivePosition(BaseModel):
    model_config = ConfigDict(extra="forbid")
    latitude: float = Field(ge=-90, le=90)
    longitude: float = Field(ge=-180, le=180)
    speed_kph: float = Field(default=0, ge=0, le=400)
    heading_deg: float | None = Field(default=None, ge=0, lt=360)
    accuracy_m: float | None = Field(default=None, ge=0, le=10000)


class DriveHazard(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str
    kind: HazardKind
    latitude: float = Field(ge=-90, le=90)
    longitude: float = Field(ge=-180, le=180)
    title: str = ""
    speed_limit_kph: float | None = Field(default=None, ge=0, le=250)
    direction_deg: float | None = Field(default=None, ge=0, lt=360)
    severity: Literal["info", "warning", "high"] = "warning"
    source: str = "local"


class DriveEvaluationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    position: DrivePosition
    hazards: list[DriveHazard] = Field(default_factory=list, max_length=2000)
    warning_distance_m: float = Field(default=1000, ge=100, le=5000)
    speed_tolerance_kph: float = Field(default=3, ge=0, le=30)


class DriveAlert(BaseModel):
    hazard_id: str
    kind: HazardKind
    title: str
    distance_m: float
    priority: int
    message: str
    source: str


def haversine_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    radius = 6_371_000.0
    p1 = math.radians(lat1)
    p2 = math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return radius * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def bearing_deg(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    p1 = math.radians(lat1)
    p2 = math.radians(lat2)
    dl = math.radians(lon2 - lon1)
    y = math.sin(dl) * math.cos(p2)
    x = math.cos(p1) * math.sin(p2) - math.sin(p1) * math.cos(p2) * math.cos(dl)
    return (math.degrees(math.atan2(y, x)) + 360) % 360


def angular_difference(a: float, b: float) -> float:
    return abs((a - b + 180) % 360 - 180)


def _approaching(position: DrivePosition, hazard: DriveHazard) -> bool:
    if position.heading_deg is None:
        return True
    target = bearing_deg(position.latitude, position.longitude, hazard.latitude, hazard.longitude)
    if angular_difference(position.heading_deg, target) > 75:
        return False
    if hazard.direction_deg is not None and angular_difference(position.heading_deg, hazard.direction_deg) > 70:
        return False
    return True


def _message(position: DrivePosition, hazard: DriveHazard, distance: float, tolerance: float) -> tuple[int, str]:
    rounded = max(0, int(round(distance / 10.0) * 10))
    prefix = f"Σε {rounded} μ."
    if hazard.kind == "speed_limit":
        limit = hazard.speed_limit_kph
        if limit is not None and position.speed_kph > limit + tolerance:
            return 100, f"{prefix} όριο {int(limit)} km/h. Τρέχουσα ταχύτητα {int(round(position.speed_kph))} km/h. Μείωσε ταχύτητα."
        return 70, f"{prefix} όριο ταχύτητας {int(limit) if limit is not None else 'άγνωστο'} km/h."
    if hazard.kind == "fixed_camera":
        return 85, f"{prefix} σταθερό σημείο ελέγχου ταχύτητας. Έλεγξε ότι κινείσαι εντός ορίου."
    if hazard.kind == "curve":
        return 90 if hazard.severity == "high" else 75, f"{prefix} {'επικίνδυνη' if hazard.severity == 'high' else 'έντονη'} στροφή. Προσαρμόσου έγκαιρα."
    if hazard.kind == "school_zone":
        return 95, f"{prefix} σχολική ζώνη. Μείωσε ταχύτητα και αύξησε προσοχή."
    if hazard.kind == "roadworks":
        return 80, f"{prefix} οδικά έργα. Πρόσεξε προσωρινή σήμανση και λωρίδες."
    return 80 if hazard.severity != "high" else 95, f"{prefix} αναφερόμενος οδικός κίνδυνος."


def evaluate_drive(request: DriveEvaluationRequest) -> list[DriveAlert]:
    alerts: list[DriveAlert] = []
    p = request.position
    for hazard in request.hazards:
        distance = haversine_m(p.latitude, p.longitude, hazard.latitude, hazard.longitude)
        if distance > request.warning_distance_m:
            continue
        if not _approaching(p, hazard):
            continue
        priority, message = _message(p, hazard, distance, request.speed_tolerance_kph)
        alerts.append(
            DriveAlert(
                hazard_id=hazard.id,
                kind=hazard.kind,
                title=hazard.title or hazard.kind.replace("_", " ").title(),
                distance_m=round(distance, 1),
                priority=priority,
                message=message,
                source=hazard.source,
            )
        )
    alerts.sort(key=lambda item: (-item.priority, item.distance_m))
    return alerts


@router.get("/health")
async def drive_health(_: str = Depends(require_owner)) -> dict:
    return {
        "status": "ready",
        "engine": "safety-alerts-v1",
        "supported_hazards": ["speed_limit", "fixed_camera", "curve", "school_zone", "roadworks", "road_hazard"],
    }


@router.post("/evaluate", response_model=list[DriveAlert])
async def drive_evaluate(body: DriveEvaluationRequest, _: str = Depends(require_owner)) -> list[DriveAlert]:
    return evaluate_drive(body)
