import pytest
from exercise_factory import ExerciseFactoryJob, FactoryPhase, FactoryStatus
from providers.skeletons import FalImageProvider
from providers.base import GenerationInput, ProviderConfigurationError

def test_air_squat_manifest_identity_is_canonical():
    job=ExerciseFactoryJob(owner_email="owner@example.com",identity_pack_id="pack")
    assert job.exercise_id=="master:1856:air-squat"
    assert job.exercise_name=="Air Squat"
    assert job.movement_family=="SQUAT_PATTERN"

def test_fal_qwen_contract_advertises_factory_requirements():
    caps=FalImageProvider.capabilities
    assert caps.identity_references is True
    assert caps.pose_conditioning is True
    assert caps.maximum_reference_images>=2
    assert "fal-ai/qwen-image-edit-2509" in caps.models

@pytest.mark.asyncio
async def test_fal_never_calls_paid_provider_without_credentials(monkeypatch):
    monkeypatch.delenv("FAL_KEY",raising=False)
    provider=FalImageProvider()
    with pytest.raises(ProviderConfigurationError):
        await provider.generate(GenerationInput(prompt="squat",reference_images=[b"identity",b"pose"],reference_mimes=["image/png","image/png"]))
