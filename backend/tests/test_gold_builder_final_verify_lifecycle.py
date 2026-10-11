"""Final verification must be able to re-run the deterministic pipeline (real-run regression)."""
from gold_builder.engine.lifecycle import can_transition
from gold_builder.models import JobStatus


def test_final_verify_can_rerun_install_build_start_verify():
    # Observed live: "illegal lifecycle transition final_verifying -> installing" killed two jobs.
    for stage in (JobStatus.INSTALLING, JobStatus.BUILDING, JobStatus.TESTING, JobStatus.STARTING, JobStatus.VERIFYING):
        assert can_transition(JobStatus.FINAL_VERIFYING, stage), stage


def test_final_verify_still_cannot_rewind_to_generation_or_planning():
    assert not can_transition(JobStatus.FINAL_VERIFYING, JobStatus.GENERATING)
    assert not can_transition(JobStatus.FINAL_VERIFYING, JobStatus.PLANNING)
