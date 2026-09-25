from pathlib import Path

from code_builder_v2.autonomous import (
    AttemptResult,
    AutonomousBuildLoop,
    AutonomousPhase,
    FailureEvidence,
    RepairInstruction,
)


class SequenceRunner:
    def __init__(self, results):
        self.results = list(results)
        self.calls = []

    def run_attempt(
        self,
        *,
        workspace_root,
        instruction,
        attempt,
        previous_evidence,
    ):
        self.calls.append((Path(workspace_root), instruction, attempt, previous_evidence))
        return self.results.pop(0)


class Diagnoser:
    def __init__(self):
        self.calls = []

    def diagnose(self, *, original_instruction, attempt, evidence):
        self.calls.append((original_instruction, attempt, evidence))
        return RepairInstruction(
            instruction=f"Repair attempt {attempt}: {evidence.summary}",
            relevant_paths=("app.py",),
        )


def failure(summary="browser workflow failed"):
    return AttemptResult(
        successful=False,
        changed_paths=("app.py",),
        evidence=FailureEvidence(
            summary=summary,
            command="pytest -q",
            stderr="assert visible result",
            console_errors=("TypeError: failed",),
            network_errors=("POST /api/items 500",),
        ),
    )


def test_autonomous_loop_repairs_in_disposable_workspace(tmp_path: Path):
    source = tmp_path / "source"
    source.mkdir()
    (source / "app.py").write_text("VALUE = 1\n", encoding="utf-8")
    runner = SequenceRunner(
        [
            failure(),
            AttemptResult(successful=True, changed_paths=("app.py", "test_app.py")),
        ]
    )
    diagnoser = Diagnoser()
    loop = AutonomousBuildLoop(runner=runner, diagnoser=diagnoser, max_attempts=3)

    result = loop.execute(repository_root=source, instruction="Build the requested workflow")

    assert result.successful is True
    assert result.attempts == 2
    assert result.changed_paths == ("app.py", "test_app.py")
    assert [event.phase for event in result.events] == [
        AutonomousPhase.PREPARING,
        AutonomousPhase.BUILDING,
        AutonomousPhase.DIAGNOSING,
        AutonomousPhase.REPAIRING,
        AutonomousPhase.COMPLETED,
    ]
    assert len(diagnoser.calls) == 1
    assert runner.calls[0][0] != source
    assert not runner.calls[0][0].exists()
    assert (source / "app.py").read_text(encoding="utf-8") == "VALUE = 1\n"


def test_autonomous_loop_stops_repeated_identical_failure(tmp_path: Path):
    source = tmp_path / "source"
    source.mkdir()
    runner = SequenceRunner([failure(), failure()])
    loop = AutonomousBuildLoop(
        runner=runner,
        diagnoser=Diagnoser(),
        max_attempts=5,
        max_repeated_failure_fingerprints=2,
    )

    result = loop.execute(repository_root=source, instruction="Build feature")

    assert result.successful is False
    assert result.attempts == 2
    assert result.stop_reason == "Repeated identical failure evidence; repair loop stopped"
    assert result.final_evidence is not None
    assert result.events[-1].phase is AutonomousPhase.FAILED


def test_autonomous_loop_stops_at_attempt_budget(tmp_path: Path):
    source = tmp_path / "source"
    source.mkdir()
    runner = SequenceRunner(
        [
            failure("first failure"),
            failure("second failure"),
            failure("third failure"),
        ]
    )
    loop = AutonomousBuildLoop(
        runner=runner,
        diagnoser=Diagnoser(),
        max_attempts=3,
        max_repeated_failure_fingerprints=3,
    )

    result = loop.execute(repository_root=source, instruction="Build feature")

    assert result.successful is False
    assert result.attempts == 3
    assert result.stop_reason == "Maximum repair attempts reached"


def test_autonomous_loop_rejects_empty_instruction(tmp_path: Path):
    source = tmp_path / "source"
    source.mkdir()
    loop = AutonomousBuildLoop(
        runner=SequenceRunner([]),
        diagnoser=Diagnoser(),
    )

    try:
        loop.execute(repository_root=source, instruction="   ")
    except ValueError as exc:
        assert "must not be empty" in str(exc)
    else:
        raise AssertionError("Expected empty instruction to be rejected")
