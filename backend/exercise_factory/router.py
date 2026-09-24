from __future__ import annotations
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from auth import require_owner
from exercise_factory import ExerciseFactoryJob, ExerciseFactoryService, FactoryPhase, FactoryStatus
from motion_engine.pipeline import build_bodyweight_squat_poc
from motion_engine.pose_renderer import render_pose_png
from models import MediaAsset, now_iso
from storage import save_bytes

router=APIRouter(prefix="/api/exercise-factory",tags=["exercise-factory"])
_jobs=None; _media=None; _packs=None

def configure(*,jobs_collection,media_collection,packs_collection):
    global _jobs,_media,_packs
    _jobs=jobs_collection; _media=media_collection; _packs=packs_collection

def _ready():
    if _jobs is None or _media is None or _packs is None: raise RuntimeError("Exercise Factory router is not configured")

class CreateJob(BaseModel):
    identity_pack_id:str
    image_provider:str|None=None
    output_resolution:str="1024"

async def _load(job_id:str,owner:str)->ExerciseFactoryJob:
    _ready(); doc=await _jobs.find_one({"id":job_id,"owner_email":owner},{"_id":0})
    if not doc: raise HTTPException(404,"Exercise Factory job not found")
    return ExerciseFactoryJob.model_validate(doc)

async def _save(job:ExerciseFactoryJob):
    job.updated_at=now_iso()
    await _jobs.update_one({"id":job.id,"owner_email":job.owner_email},{"$set":job.model_dump(mode="json")})

@router.post("/jobs",response_model=ExerciseFactoryJob)
async def create_job(body:CreateJob,owner:str=Depends(require_owner)):
    _ready()
    pack=await _packs.find_one({"id":body.identity_pack_id,"owner_email":owner},{"_id":0})
    if not pack: raise HTTPException(404,"Identity Pack not found")
    job=ExerciseFactoryJob(owner_email=owner,identity_pack_id=body.identity_pack_id,image_provider=body.image_provider,output_resolution=body.output_resolution)
    poc=build_bodyweight_squat_poc()
    for phase,pose in poc["phases"].items():
        png=render_pose_png(pose,(512,512))
        filename,_,size=save_bytes(png,"image/png",kind="generated")
        media=MediaAsset(owner_email=owner,filename=filename,mime_type="image/png",kind="generated",size_bytes=size,source_module="exercise-factory",identity_pack_id=body.identity_pack_id,metadata={"exercise_id":job.exercise_id,"exercise_name":job.exercise_name,"greek_name":job.greek_name,"source_number":job.source_number,"equipment_or_subgroup":job.equipment_or_subgroup,"movement_type":job.movement_type,"movement_family":job.movement_family,"phase":phase.value,"pose_source":pose.provenance.source_type,"pose_confidence":pose.provenance.confidence,"conditioning_asset":True,"not_final_generation":True})
        await _media.insert_one(media.model_dump())
        job.phases[FactoryPhase(phase.value)].pose_media_id=media.id
        job.phases[FactoryPhase(phase.value)].metadata=media.metadata
    await _jobs.insert_one(job.model_dump(mode="json"))
    return job

@router.get("/jobs/{job_id}",response_model=ExerciseFactoryJob)
async def get_job(job_id:str,owner:str=Depends(require_owner)): return await _load(job_id,owner)

@router.post("/jobs/{job_id}/phases/{phase}/retry",response_model=ExerciseFactoryJob)
async def retry_phase(job_id:str,phase:FactoryPhase,owner:str=Depends(require_owner)):
    job=await _load(job_id,owner); ExerciseFactoryService.retry(job,phase); await _save(job); return job

@router.post("/jobs/{job_id}/phases/{phase}/approve",response_model=ExerciseFactoryJob)
async def approve_phase(job_id:str,phase:FactoryPhase,owner:str=Depends(require_owner)):
    job=await _load(job_id,owner)
    try: ExerciseFactoryService.approve(job,phase)
    except ValueError as exc: raise HTTPException(409,str(exc)) from exc
    await _save(job); return job

@router.post("/jobs/{job_id}/phases/{phase}/reject",response_model=ExerciseFactoryJob)
async def reject_phase(job_id:str,phase:FactoryPhase,owner:str=Depends(require_owner)):
    job=await _load(job_id,owner)
    try: ExerciseFactoryService.reject(job,phase)
    except ValueError as exc: raise HTTPException(409,str(exc)) from exc
    await _save(job); return job

@router.get("/capabilities")
async def capabilities(owner:str=Depends(require_owner)):
    return {"exercise_id":"master:1856:air-squat","exercise_name":"Air Squat","greek_name":"Κάθισμα με το βάρος του σώματος","source_number":"1856","equipment_or_subgroup":"Bodyweight","movement_type":"DYNAMIC","movement_family":"SQUAT_PATTERN","phases":[p.value for p in FactoryPhase],"real_generation_enabled":False,"blocker":"No existing Lumina provider has been verified to accept both identity reference and pose/keypoint conditioning. Conditioning poses are real assets; final exercise images are not fabricated."}
