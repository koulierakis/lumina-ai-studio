from code_builder.models import ChangeType, RiskLevel
from code_builder.openhands_change_capture_service import OpenHandsFileChange
from code_builder.openhands_proposal_service import OpenHandsProposalService


def test_proposal_service_maps_sandbox_changes_to_native_contract():
    service = OpenHandsProposalService()
    proposals = service.convert((
        OpenHandsFileChange("src/new.py", "created", None, "print('new')\n"),
        OpenHandsFileChange("src/existing.py", "modified", "a=1\n", "a=2\n"),
        OpenHandsFileChange("src/old.py", "deleted", "old\n", None),
    ))
    assert [proposal.change_type for proposal in proposals] == [
        ChangeType.CREATE, ChangeType.MODIFY, ChangeType.DELETE,
    ]
    assert proposals[0].old_content is None
    assert proposals[0].new_content == "print('new')\n"
    assert proposals[1].old_sha256 and proposals[1].new_sha256
    assert proposals[1].old_sha256 != proposals[1].new_sha256
    assert proposals[2].new_content is None
    assert all(proposal.approved is False for proposal in proposals)


def test_proposal_service_marks_shared_infrastructure_as_higher_risk():
    service = OpenHandsProposalService()
    proposals = service.convert((
        OpenHandsFileChange("backend/server.py", "modified", "old\n", "new\n"),
        OpenHandsFileChange("frontend/src/App.js", "modified", "old\n", "new\n"),
    ))
    assert proposals[0].risk_level == RiskLevel.MEDIUM
    assert proposals[1].risk_level == RiskLevel.LOW
