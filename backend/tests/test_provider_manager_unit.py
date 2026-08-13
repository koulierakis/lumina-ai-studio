import asyncio

import pytest

from providers.base import (
    ErrorKind,
    GeneratedImage,
    GenerationInput,
    ImageProvider,
    ProviderCapabilities,
    ProviderError,
    ProviderTimeoutError,
)
from providers.manager import ProviderManager
from providers.mock_provider import MockImageProvider


class WorkingProvider(ImageProvider):
    name = "working"
    priority = 2
    capabilities = ProviderCapabilities(
        generation=True,
        editing=True,
        identity_references=True,
        masks=True,
        aspect_ratios=("1:1", "16:9"),
        maximum_reference_images=5,
        maximum_outputs=4,
    )

    @classmethod
    def is_configured(cls):
        return True

    async def generate(self, spec):
        return [GeneratedImage(b"image", "image/png")]

    async def edit(self, *args, **kwargs):
        return GeneratedImage(b"edited", "image/png")


class SecondProvider(WorkingProvider):
    name = "second"
    priority = 3


class RateLimitedProvider(WorkingProvider):
    name = "limited"
    priority = 1

    async def generate(self, spec):
        raise ProviderError(self.name, "429", kind=ErrorKind.RATE_LIMIT, retryable=True, status_code=429)


class TimeoutProvider(WorkingProvider):
    name = "timeout"
    priority = 1

    async def generate(self, spec):
        raise ProviderTimeoutError(self.name)


class AuthProvider(WorkingProvider):
    name = "auth"
    priority = 1

    async def generate(self, spec):
        raise ProviderError(self.name, "bad key", kind=ErrorKind.AUTH, retryable=False, status_code=401)


class GenerateOnlyProvider(WorkingProvider):
    name = "generate-only"
    capabilities = ProviderCapabilities(generation=True, editing=False, aspect_ratios=("1:1",))


def run(coro):
    return asyncio.run(coro)


def test_first_provider_succeeds(monkeypatch):
    monkeypatch.setenv("IMAGE_PROVIDER_ORDER", "working,second")
    manager = ProviderManager({"working": WorkingProvider, "second": SecondProvider})
    result = run(manager.generate_result(GenerationInput(prompt="test")))
    assert result.provider == "working"
    assert result.attempted_providers == ["working"]
    assert result.fallback_used is False


def test_429_falls_back_to_second(monkeypatch):
    monkeypatch.setenv("IMAGE_PROVIDER_ORDER", "limited,second")
    manager = ProviderManager({"limited": RateLimitedProvider, "second": SecondProvider})
    result = run(manager.generate_result(GenerationInput(prompt="test")))
    assert result.provider == "second"
    assert result.attempted_providers == ["limited", "second"]
    assert result.fallback_used is True


def test_timeout_falls_back_to_second(monkeypatch):
    monkeypatch.setenv("IMAGE_PROVIDER_ORDER", "timeout,second")
    manager = ProviderManager({"timeout": TimeoutProvider, "second": SecondProvider})
    result = run(manager.generate_result(GenerationInput(prompt="test")))
    assert result.provider == "second"


def test_provider_in_cooldown_is_skipped(monkeypatch):
    monkeypatch.setenv("IMAGE_PROVIDER_ORDER", "limited,second")
    manager = ProviderManager({"limited": RateLimitedProvider, "second": SecondProvider})
    first = run(manager.generate_result(GenerationInput(prompt="test")))
    second = run(manager.generate_result(GenerationInput(prompt="test")))
    assert first.attempted_providers == ["limited", "second"]
    assert second.attempted_providers == ["second"]


def test_auth_error_does_not_fallback(monkeypatch):
    monkeypatch.setenv("IMAGE_PROVIDER_ORDER", "auth,second")
    manager = ProviderManager({"auth": AuthProvider, "second": SecondProvider})
    with pytest.raises(ProviderError) as exc:
        run(manager.generate_result(GenerationInput(prompt="test")))
    assert exc.value.kind == ErrorKind.AUTH
    assert manager.usage["second"] == 0


def test_capability_filtering_generate_versus_edit(monkeypatch):
    monkeypatch.setenv("IMAGE_PROVIDER_ORDER", "generate-only,working")
    manager = ProviderManager({"generate-only": GenerateOnlyProvider, "working": WorkingProvider})
    generated = run(manager.generate_result(GenerationInput(prompt="test")))
    edited = run(manager.edit_result(source_bytes=b"src", source_mime="image/png", instruction="fix"))
    assert generated.provider == "generate-only"
    assert edited.provider == "working"


def test_all_providers_fail_safe_error(monkeypatch):
    monkeypatch.setenv("IMAGE_PROVIDER_ORDER", "limited,timeout")
    manager = ProviderManager({"limited": RateLimitedProvider, "timeout": TimeoutProvider})
    with pytest.raises(ProviderError) as exc:
        run(manager.generate_result(GenerationInput(prompt="test")))
    assert "Provider rate limit reached" in exc.value.public_message()
    assert "key" not in exc.value.public_message().lower()


def test_provider_order_from_environment_is_respected(monkeypatch):
    monkeypatch.setenv("IMAGE_PROVIDER_ORDER", "second,working")
    manager = ProviderManager({"working": WorkingProvider, "second": SecondProvider})
    result = run(manager.generate_result(GenerationInput(prompt="test")))
    assert result.provider == "second"


def test_retry_after_controls_cooldown(monkeypatch):
    class RetryAfterProvider(RateLimitedProvider):
        name = "retry-after"

        async def generate(self, spec):
            raise ProviderError(
                self.name,
                "429",
                kind=ErrorKind.RATE_LIMIT,
                retryable=True,
                status_code=429,
                retry_after_seconds=17,
            )

    monkeypatch.setenv("IMAGE_PROVIDER_ORDER", "retry-after,second")
    manager = ProviderManager({"retry-after": RetryAfterProvider, "second": SecondProvider})
    run(manager.generate_result(GenerationInput(prompt="test")))
    statuses = run(manager.statuses())
    retry_after = next(item for item in statuses if item["name"] == "retry-after")
    assert retry_after["cooldown_until"] is not None
    assert retry_after["last_safe_error"]["retry_after_seconds"] == 17


def test_mock_provider_requires_explicit_test_flag(monkeypatch):
    monkeypatch.delenv("LUMINA_TEST_PROVIDER", raising=False)
    assert MockImageProvider.is_configured() is False
    monkeypatch.setenv("LUMINA_TEST_PROVIDER", "true")
    assert MockImageProvider.is_configured() is True


def test_provider_capabilities_do_not_overpromise_unimplemented_identity_or_comfyui():
    from providers.comfyui_provider import ComfyUIProvider
    from providers.openai_provider import OpenAIImageProvider

    assert ComfyUIProvider.capabilities.generation is False
    assert OpenAIImageProvider.capabilities.identity_references is False
    assert OpenAIImageProvider.capabilities.maximum_reference_images == 0
