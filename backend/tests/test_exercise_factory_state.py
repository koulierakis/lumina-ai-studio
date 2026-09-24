from exercise_factory import ExerciseFactoryJob, ExerciseFactoryService, FactoryPhase, FactoryStatus

def job(): return ExerciseFactoryJob(owner_email="owner@example.com",identity_pack_id="master-woman")

def test_failure_is_phase_isolated():
    j=job(); s=ExerciseFactoryService(); s.begin_phase(j,FactoryPhase.START); s.generated(j,FactoryPhase.START,"m1"); s.failed(j,FactoryPhase.EXECUTION,"provider failed")
    assert j.phases[FactoryPhase.START].status is FactoryStatus.GENERATED
    assert j.phases[FactoryPhase.EXECUTION].status is FactoryStatus.FAILED
    assert j.phases[FactoryPhase.RETURN].status is FactoryStatus.PENDING

def test_approved_phase_is_idempotently_skipped():
    j=job(); s=ExerciseFactoryService(); s.begin_phase(j,FactoryPhase.START); s.generated(j,FactoryPhase.START,"m1"); s.approve(j,FactoryPhase.START); attempts=j.phases[FactoryPhase.START].attempts; s.begin_phase(j,FactoryPhase.START)
    assert j.phases[FactoryPhase.START].status is FactoryStatus.APPROVED
    assert j.phases[FactoryPhase.START].output_media_id=="m1"
    assert j.phases[FactoryPhase.START].attempts==attempts

def test_retry_does_not_touch_other_phases():
    j=job(); s=ExerciseFactoryService(); s.failed(j,FactoryPhase.EXECUTION,"x"); s.retry(j,FactoryPhase.EXECUTION)
    assert j.phases[FactoryPhase.EXECUTION].status is FactoryStatus.RETRY
    assert j.phases[FactoryPhase.START].status is FactoryStatus.PENDING
    assert j.phases[FactoryPhase.RETURN].status is FactoryStatus.PENDING

def test_approve_requires_generated_output():
    import pytest
    with pytest.raises(ValueError): ExerciseFactoryService.approve(job(),FactoryPhase.START)
