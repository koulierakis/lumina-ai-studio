from __future__ import annotations
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from auth import require_owner
from exercise_factory import ExerciseFactoryJob, ExerciseFactoryService, FactoryPhase, FactoryStatus
from motion_engine.pipeline import build_bodyweight_squat_poc
from motion_engine.pose_renderer import render_pose_png
from models import MediaAsset, now_iso
from storage import save_bytes, read_bytes
from providers import get_provider
from providers.base import GenerationInput, ProviderError

router=APIRouter(prefix="/api/exercise-factory",tags=["exercise-factory"])
_jobs=None; _media=None; _packs=None

def configure(*,jobs_collection,media_collection,packs_collection):
    global _jobs,_media,_packs
    _jobs=jobs_collection; _media=media_collection; _packs=packs_collection

def _ready():
    if _jobs is None or _media is None or _packs is None: raise RuntimeError("Exercise Factory router is not configured")

class CreateJob(BaseModel):
    identity_pack_id:str
    image_provider:str|None="fal"
    output_resolution:str="1024"

class GeneratePhaseRequest(BaseModel):
    seed:int|None=1856

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


_SHARED_VISUAL_PROMPT = """Create a photorealistic Athletico Wellness Center exercise reference image. Preserve the exact woman identity from the first reference image: same face, body proportions, dark tied-back hair, black sports bra, black high-waisted leggings and black athletic shoes. Preserve a premium charcoal-black, cool-gray and natural-wood wellness studio environment, front camera, full body visible, neutral professional lighting. The second reference image is a POSE CONDITION, not a person identity reference: follow its joint geometry and body position accurately. Do not copy skeleton lines into the result. Exercise: Air Squat / Κάθισμα με το βάρος του σώματος. Phase: {phase}. Keep anatomy realistic, both feet fully visible, no extra limbs or fingers, no text, no labels, no collage."""
_NEGATIVE = "different person, different face, different outfit, cropped feet, extra limbs, malformed hands, malformed knees, text, watermark, collage, split screen, skeleton overlay"

async def _media_doc(media_id:str,owner:str):
    doc=await _media.find_one({"id":media_id,"owner_email":owner},{"_id":0})
    if not doc: raise HTTPException(404,"Factory media not found")
    return doc

def _read_media(doc:dict)->bytes:
    return read_bytes(doc["filename"],kind="reference" if doc.get("kind")=="reference" else "generated")

@router.post("/jobs/{job_id}/phases/{phase}/generate",response_model=ExerciseFactoryJob)
async def generate_phase(job_id:str,phase:FactoryPhase,body:GeneratePhaseRequest,owner:str=Depends(require_owner)):
    job=await _load(job_id,owner)
    state=job.phases[phase]
    if state.status is FactoryStatus.APPROVED:
        return job
    pack=await _packs.find_one({"id":job.identity_pack_id,"owner_email":owner},{"_id":0})
    if not pack: raise HTTPException(404,"Identity Pack not found")
    identity_id=pack.get("primary_photo_id") or next(iter(pack.get("photo_ids") or []),None)
    if not identity_id: raise HTTPException(409,"Identity Pack has no reference photograph")
    if not state.pose_media_id: raise HTTPException(409,"Pose condition is missing")
    identity_doc=await _media_doc(identity_id,owner); pose_doc=await _media_doc(state.pose_media_id,owner)
    provider=get_provider(job.image_provider or "fal")
    caps=provider.capabilities
    if not (caps.identity_references and caps.pose_conditioning):
        raise HTTPException(409,"Selected provider is not verified for identity + pose conditioning")
    ExerciseFactoryService.begin_phase(job,phase); await _save(job)
    prompt=_SHARED_VISUAL_PROMPT.format(phase=phase.value)
    try:
        images=await provider.generate(GenerationInput(prompt=prompt,negative_prompt=_NEGATIVE,resolution=job.output_resolution,seed=body.seed,mode="image-edit",identity_lock="high",reference_images=[_read_media(identity_doc),_read_media(pose_doc)],reference_mimes=[identity_doc.get("mime_type","image/png"),pose_doc.get("mime_type","image/png")],metadata={"exercise_id":job.exercise_id,"phase":phase.value,"identity_pack_id":job.identity_pack_id,"pose_media_id":state.pose_media_id}))
        if not images: raise RuntimeError("Provider returned no image")
        generated=images[0]
        filename,_,size=save_bytes(generated.data,generated.mime_type,kind="generated")
        media=MediaAsset(owner_email=owner,filename=filename,mime_type=generated.mime_type,kind="generated",size_bytes=size,source_module="exercise-factory",job_id=job.id,identity_pack_id=job.identity_pack_id,provider=provider.name,metadata={"exercise_id":job.exercise_id,"exercise_name":job.exercise_name,"greek_name":job.greek_name,"movement_family":job.movement_family,"phase":phase.value,"pose_source":state.metadata.get("pose_source"),"pose_confidence":state.metadata.get("pose_confidence"),"pose_media_id":state.pose_media_id,"identity_pack_id":job.identity_pack_id,"image_provider":provider.name,"model":getattr(provider,"model",None),"prompt":prompt,"negative_prompt":_NEGATIVE,"seed":body.seed,"generation_job_id":job.id,"approval_status":"GENERATED","real_generation":True,"requested_filename":f"bodyweight_squat_{phase.value}.png"})
        await _media.insert_one(media.model_dump())
        ExerciseFactoryService.generated(job,phase,media.id)
        state.metadata={**state.metadata,**media.metadata}
    except ProviderError as exc:
        ExerciseFactoryService.failed(job,phase,exc.public_message()); await _save(job)
        raise HTTPException(503,exc.public_message()) from exc
    except Exception as exc:
        ExerciseFactoryService.failed(job,phase,"Generation failed"); await _save(job)
        raise HTTPException(500,"Exercise Factory generation failed") from exc
    await _save(job); return job

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
    provider=get_provider("fal"); status=await provider.health_check()
    return {"exercise_id":"master:1856:air-squat","exercise_name":"Air Squat","greek_name":"Κάθισμα με το βάρος του σώματος","source_number":"1856","equipment_or_subgroup":"Bodyweight","movement_type":"DYNAMIC","movement_family":"SQUAT_PATTERN","phases":[p.value for p in FactoryPhase],"real_generation_enabled":bool(status.available and provider.capabilities.identity_references and provider.capabilities.pose_conditioning),"provider":"fal","provider_configured":status.configured,"blocker":None if status.configured else "fal Qwen provider is implemented but FAL_KEY is not configured. No paid request will be made without credentials."}
