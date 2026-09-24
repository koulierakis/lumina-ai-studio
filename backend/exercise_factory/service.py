from __future__ import annotations
from .models import ExerciseFactoryJob, FactoryPhase, FactoryStatus

class ExerciseFactoryService:
    """Pure phase-state rules. Persistence and providers are injected by the HTTP integration."""
    @staticmethod
    def begin_phase(job:ExerciseFactoryJob, phase:FactoryPhase)->ExerciseFactoryJob:
        state=job.phases[phase]
        if state.status is FactoryStatus.APPROVED:
            return job
        state.status=FactoryStatus.GENERATING; state.error=None; state.attempts+=1
        return job

    @staticmethod
    def generated(job:ExerciseFactoryJob,phase:FactoryPhase,media_id:str)->ExerciseFactoryJob:
        state=job.phases[phase]; state.output_media_id=media_id; state.status=FactoryStatus.GENERATED; state.error=None
        return job

    @staticmethod
    def failed(job:ExerciseFactoryJob,phase:FactoryPhase,error:str)->ExerciseFactoryJob:
        state=job.phases[phase]; state.status=FactoryStatus.FAILED; state.error=error
        return job

    @staticmethod
    def retry(job:ExerciseFactoryJob,phase:FactoryPhase)->ExerciseFactoryJob:
        state=job.phases[phase]
        if state.status is FactoryStatus.APPROVED: return job
        state.status=FactoryStatus.RETRY; state.error=None
        return job

    @staticmethod
    def approve(job:ExerciseFactoryJob,phase:FactoryPhase)->ExerciseFactoryJob:
        state=job.phases[phase]
        if state.status is not FactoryStatus.GENERATED: raise ValueError("Only GENERATED output can be approved")
        state.status=FactoryStatus.APPROVED
        return job

    @staticmethod
    def reject(job:ExerciseFactoryJob,phase:FactoryPhase)->ExerciseFactoryJob:
        state=job.phases[phase]
        if state.status not in {FactoryStatus.GENERATED,FactoryStatus.APPROVED}: raise ValueError("Only generated output can be rejected")
        state.status=FactoryStatus.RETRY
        return job
