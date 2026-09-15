from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any


@dataclass
class RuntimeProvider:
    name: str
    kind: str
    capabilities: list[str]
    configured: bool = True
    healthy: bool = True
    priority: int = 100
    detail: str = "ready"
    metadata: dict[str, Any] = field(default_factory=dict)
    handler: Any = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "kind": self.kind,
            "capabilities": self.capabilities,
            "configured": self.configured,
            "healthy": self.healthy,
            "available": self.configured and self.healthy,
            "priority": self.priority,
            "detail": self.detail,
            "metadata": self.metadata,
        }


class RuntimeProviderRegistry:
    def __init__(self) -> None:
        self.providers: dict[str, RuntimeProvider] = {}

    def register(self, provider: RuntimeProvider) -> RuntimeProvider:
        self.providers[provider.name] = provider
        return provider

    def list(self) -> list[dict[str, Any]]:
        return [
            provider.as_dict()
            for provider in sorted(self.providers.values(), key=lambda item: item.priority)
        ]

    def validate(self) -> dict[str, Any]:
        providers = self.list()
        return {
            "ok": any(item["available"] for item in providers),
            "providers": providers,
            "missing": [item["name"] for item in providers if not item["configured"]],
        }

    def route(self, task_type: str, requested: str | None = None) -> RuntimeProvider:
        if requested and requested in self.providers and self.providers[requested].configured:
            return self.providers[requested]
        candidates = [
            provider
            for provider in self.providers.values()
            if provider.configured and provider.healthy and task_type in provider.capabilities
        ]
        if not candidates:
            candidates = [
                provider
                for provider in self.providers.values()
                if provider.configured and provider.healthy
            ]
        if not candidates:
            raise RuntimeError(f"No runtime provider available for {task_type}")
        return sorted(candidates, key=lambda item: item.priority)[0]


class PluginManager:
    def __init__(self, registry: RuntimeProviderRegistry) -> None:
        self.registry = registry
        self.plugins: dict[str, dict[str, Any]] = {}

    def install(
        self,
        manifest: dict[str, Any],
        handler: Callable | None = None,
    ) -> dict[str, Any]:
        name = str(manifest.get("name") or "").strip().lower()
        if not name:
            raise ValueError("Plugin name is required")
        provider = RuntimeProvider(
            name=name,
            kind=str(manifest.get("kind") or "hybrid"),
            capabilities=[str(item) for item in manifest.get("capabilities", [])],
            configured=bool(manifest.get("configured", True)),
            healthy=bool(manifest.get("healthy", True)),
            priority=int(manifest.get("priority", 100)),
            detail=str(manifest.get("detail") or "plugin provider ready"),
            metadata=manifest.get("metadata") or {},
            handler=handler,
        )
        self.registry.register(provider)
        self.plugins[name] = {"manifest": manifest, "status": "installed"}
        return {
            "plugin": name,
            "provider": provider.as_dict(),
            "status": "installed",
        }

    def list(self) -> list[dict[str, Any]]:
        return [{"name": name, **data} for name, data in sorted(self.plugins.items())]


def build_default_provider_registry() -> RuntimeProviderRegistry:
    registry = RuntimeProviderRegistry()
    registry.register(
        RuntimeProvider(
            "local",
            "local",
            [
                "llm",
                "code",
                "embedding",
                "ocr",
                "image_generation",
                "image_editing",
                "speech",
            ],
            priority=30,
            detail="Local runtime engines registered",
        )
    )
    registry.register(
        RuntimeProvider(
            "cloud",
            "cloud",
            [
                "llm",
                "vision",
                "image_generation",
                "image_editing",
                "video",
                "speech",
                "translation",
            ],
            priority=40,
            detail="Cloud providers registered",
        )
    )
    registry.register(
        RuntimeProvider(
            "hybrid",
            "hybrid",
            [
                "voice_cloning",
                "music",
                "video",
                "speech",
                "image_generation",
                "image_editing",
            ],
            priority=50,
            detail="Hybrid runtime providers registered",
        )
    )
    return registry
