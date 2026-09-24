from providers.base import ProviderCapabilities, ProviderStatus

def test_provider_status_exposes_factory_capability_contract():
    status=ProviderStatus(name="x",configured=True,healthy=True,priority=1,capabilities=ProviderCapabilities(identity_references=True,pose_conditioning=True,deterministic_seed=True,resolution_control=True))
    payload=status.as_dict()
    assert payload["supports_identity_references"] is True
    assert payload["supports_pose_conditioning"] is True
    assert payload["supports_seed"] is True
    assert payload["supports_resolution_control"] is True
    assert payload["capabilities"]["pose_conditioning"] is True
