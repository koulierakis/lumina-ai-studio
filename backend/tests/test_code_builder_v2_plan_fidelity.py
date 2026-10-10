"""Regression: Code Builder V2 must implement the APPROVED plan exactly.

Reproduces the production failure:

    missing planned files: customers.json; unplanned files: requirements.txt

The strict consistency check in transaction.py correctly rejected that result.
We must NOT weaken it — instead the generator reconciles its output against
the plan (drop unplanned, backfill missing via one bounded pass) and fails
loud if the plan still is not implemented.
"""
from code_builder_v2.applier import ProposedFileChange
from code_builder_v2.models import ChangePlan, PlannedChange, TaskRequest
from code_builder_v2.ollama import OllamaChangeGenerator, _reconcile_changes
from code_builder_v2.transaction import (
    TransactionValidationError,
    validate_generated_transaction,
)


# The exact plan from the reported failure.
PLAN = ChangePlan(
    summary="Simple customer management app",
    changes=[
        PlannedChange(path="app.py", operation="create", reason="Flask routes"),
        PlannedChange(path="templates/base.html", operation="create", reason="layout"),
        PlannedChange(path="templates/index.html", operation="create", reason="home"),
        PlannedChange(path="static/style.css", operation="create", reason="styling"),
        PlannedChange(path="customers.json", operation="create", reason="data store"),
    ],
    validation_commands=["python -m flask run"],
)


def _pc(path, content="x"):
    return ProposedFileChange(path=path, operation="create", content=content)


class _FakeClient:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = 0

    def generate_json(self, prompt, model=None, progress=None):
        self.calls += 1
        return self.responses.pop(0)


# ----------------------------------------------------------- pure reconciliation

def test_reconcile_drops_unplanned_and_flags_missing():
    proposed = [
        _pc("app.py"), _pc("templates/base.html"), _pc("templates/index.html"),
        _pc("static/style.css"),
        _pc("requirements.txt"),  # UNPLANNED (the bug)
        # customers.json MISSING (the bug)
    ]
    reconciled, missing, dropped = _reconcile_changes(PLAN, proposed)
    assert missing == {"customers.json"}
    assert dropped == {"requirements.txt"}
    assert "requirements.txt" not in {c.path for c in reconciled}


def test_reconcile_coerces_operation_to_the_approved_one():
    plan = ChangePlan(
        summary="edit", changes=[PlannedChange(path="a.py", operation="modify", reason="r")],
        validation_commands=[],
    )
    # model wrongly says "update" (alias of modify) — must be coerced, not rejected
    reconciled, missing, dropped = _reconcile_changes(
        plan, [ProposedFileChange(path="a.py", operation="update", content="y")]
    )
    assert not missing and not dropped
    assert reconciled[0].operation in {"modify", "update"}
    validate_generated_transaction(plan, [c.as_generated_change() for c in reconciled])


# --------------------------------------------------- end-to-end through generate()

def test_generator_backfills_missing_planned_file_and_drops_unplanned():
    """2-file plan (fast path). First response omits the data file and adds an
    unplanned requirements.txt; the bounded focused pass supplies the data file."""
    plan = ChangePlan(
        summary="app + data",
        changes=[
            PlannedChange(path="app.py", operation="create", reason="routes"),
            PlannedChange(path="customers.json", operation="create", reason="data"),
        ],
        validation_commands=[],
    )
    client = _FakeClient([
        # initial fast-path output: missing customers.json, unplanned requirements.txt
        {"changes": [
            {"path": "app.py", "operation": "create", "content": "print(1)\n"},
            {"path": "requirements.txt", "operation": "create", "content": "flask\n"},
        ]},
        # bounded focused pass for the missing file
        {"changes": [
            {"path": "customers.json", "operation": "create", "content": "[]\n"},
        ]},
    ])
    gen = OllamaChangeGenerator(client)
    result = gen.generate(TaskRequest(prompt="build it"), plan, {})

    paths = {c.path for c in result}
    assert paths == {"app.py", "customers.json"}      # exactly the approved set
    assert "requirements.txt" not in paths            # unplanned dropped
    assert client.calls == 2                          # one focused pass only
    # The strict validator (unchanged) now accepts the reconciled transaction.
    validate_generated_transaction(plan, [c.as_generated_change() for c in result])


def test_generator_fails_loud_when_plan_not_implemented():
    """If even the focused pass cannot produce a planned file, raise — never
    ship a transaction that silently diverges from the approved plan."""
    plan = ChangePlan(
        summary="app + data",
        changes=[
            PlannedChange(path="app.py", operation="create", reason="routes"),
            PlannedChange(path="customers.json", operation="create", reason="data"),
        ],
        validation_commands=[],
    )
    client = _FakeClient([
        {"changes": [
            {"path": "app.py", "operation": "create", "content": "print(1)\n"},
            {"path": "requirements.txt", "operation": "create", "content": "flask\n"},
        ]},
        # focused pass STILL does not produce customers.json
        {"changes": [
            {"path": "app.py", "operation": "create", "content": "print(1)\n"},
        ]},
    ])
    gen = OllamaChangeGenerator(client)
    try:
        gen.generate(TaskRequest(prompt="build it"), plan, {})
        raise AssertionError("expected TransactionValidationError")
    except TransactionValidationError as exc:
        assert "customers.json" in str(exc)


# ---------------------------------------------------------- planner completeness

def test_planner_prompt_requires_dependency_and_data_files():
    from code_builder_v2.ollama import OllamaPlanner

    class CapturingClient:
        prompt = ""

        def generate_json(self, prompt, model=None):
            self.prompt = prompt
            return {"summary": "x", "changes": [], "validation_commands": []}

    client = CapturingClient()
    OllamaPlanner(client).create_plan(TaskRequest(prompt="Build a Flask customer app"))
    assert "requirements.txt" in client.prompt
    assert "package.json" in client.prompt
    assert "data files" in client.prompt


def test_end_to_end_greek_plan_generates_exactly_approved_files(tmp_path):
    """Full flow (plan approval -> generate -> apply -> validate) for the EXACT
    reported Greek Flask customer-manager plan. The model omits customers.json
    and injects an unplanned requirements.txt on the data-file batch; the fix
    must still land EXACTLY the five approved files on disk, drop the unplanned
    one, and strict validation must pass."""
    from code_builder_v2.applier import AtomicChangeApplier
    from code_builder_v2.backup import BackupService
    from code_builder_v2.executor import CommandResult
    from code_builder_v2.pipeline import ExecutionPipeline
    from code_builder_v2.repository import Repository
    from code_builder_v2.validation import ValidationRunner

    class _OkExecutor:
        def run(self, command, timeout_seconds):
            return CommandResult(command, 0, "ok", "")

    # Incremental batches run in sorted path order:
    # app.py, customers.json, static/style.css, templates/base.html, templates/index.html
    responses = [
        {"changes": [{"path": "app.py", "operation": "create", "content": "# flask app\n"}]},
        # BUG: the data-file batch returns an unplanned requirements.txt instead of customers.json
        {"changes": [{"path": "requirements.txt", "operation": "create", "content": "flask\n"}]},
        {"changes": [{"path": "static/style.css", "operation": "create", "content": "body{}\n"}]},
        {"changes": [{"path": "templates/base.html", "operation": "create", "content": "<html></html>\n"}]},
        {"changes": [{"path": "templates/index.html", "operation": "create", "content": "<h1>\u03a0\u03b5\u03bb\u03ac\u03c4\u03b5\u03c2</h1>\n"}]},
        # bounded focused backfill supplies the omitted planned file
        {"changes": [{"path": "customers.json", "operation": "create", "content": "[]\n"}]},
    ]
    client = _FakeClient(responses)

    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    repository = Repository(repo_root)
    applier = AtomicChangeApplier(repository, BackupService(repo_root, tmp_path / "backups"))
    pipeline = ExecutionPipeline(
        repository, OllamaChangeGenerator(client), applier, ValidationRunner(_OkExecutor())
    )

    result = pipeline.execute(
        TaskRequest(prompt="\u0394\u03b7\u03bc\u03b9\u03bf\u03cd\u03c1\u03b3\u03b7\u03c3\u03b5 Flask customer manager"),
        PLAN,
    )

    approved = {
        "app.py", "templates/base.html", "templates/index.html",
        "static/style.css", "customers.json",
    }
    assert set(result.changed_paths) == approved          # exactly the approved files
    assert (repo_root / "customers.json").read_text(encoding="utf-8") == "[]\n"
    assert not (repo_root / "requirements.txt").exists()  # unplanned never written
    assert client.calls == 6                              # 5 batches + 1 bounded focused backfill
