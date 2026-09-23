from __future__ import annotations

import asyncio

import pytest
from providers.base import ErrorKind, GenerationInput, ProviderError
from providers.flux_hf_provider import FluxHFProvider
from providers.manager import ProviderManager


def run(coro):
    return asyncio.run(coro)


class TestFluxErrorMapping:
    def test_missing_token_is_auth_kind_not_attribute_error(self, monkeypatch):
        monkeypatch.delenv("REPLICATE_API_TOKEN", raising=False)
        provider = FluxHFProvider()
        with pytest.raises(ProviderError) as exc_info:
            run(provider.generate(GenerationInput(prompt="test")))
        assert exc_info.value.kind == ErrorKind.AUTH
        assert exc_info.value.status_code == 401
        assert not exc_info.value.retryable
        assert "credentials" in exc_info.value.public_message().lower()

    def test_unauthorized_replicate_reply_maps_to_auth_kind(self, monkeypatch):
        monkeypatch.setenv("REPLICATE_API_TOKEN", "test-token")

        def boom(*args, **kwargs):
            raise RuntimeError("replicate.com returned 401: Unauthorized")

        monkeypatch.setattr("providers.flux_hf_provider.replicate.run", boom)
        provider = FluxHFProvider()
        with pytest.raises(ProviderError) as exc_info:
            run(provider.generate(GenerationInput(prompt="test")))
        assert exc_info.value.kind == ErrorKind.AUTH
        assert not exc_info.value.retryable

    def test_quota_reply_maps_to_quota_kind(self, monkeypatch):
        monkeypatch.setenv("REPLICATE_API_TOKEN", "test-token")

        def boom(*args, **kwargs):
            raise RuntimeError("402 Payment Required: billing error")

        monkeypatch.setattr("providers.flux_hf_provider.replicate.run", boom)
        provider = FluxHFProvider()
        with pytest.raises(ProviderError) as exc_info:
            run(provider.generate(GenerationInput(prompt="test")))
        assert exc_info.value.kind == ErrorKind.QUOTA

    def test_is_configured_requires_token(self, monkeypatch):
        monkeypatch.delenv("REPLICATE_API_TOKEN", raising=False)
        assert FluxHFProvider.is_configured() is False
        monkeypatch.setenv("REPLICATE_API_TOKEN", "  ")
        assert FluxHFProvider.is_configured() is False
        monkeypatch.setenv("REPLICATE_API_TOKEN", "abc")
        assert FluxHFProvider.is_configured() is True

    def test_manager_flux_path_returns_auth_kind(self, monkeypatch):
        monkeypatch.delenv("REPLICATE_API_TOKEN", raising=False)
        manager = ProviderManager({"flux": FluxHFProvider})
        with pytest.raises(ProviderError) as exc_info:
            run(manager.generate_result(GenerationInput(prompt="test"), requested="flux"))
        assert exc_info.value.kind == ErrorKind.AUTH
        assert manager.usage["flux"] == 0