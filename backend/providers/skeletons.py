"""Configured-only provider adapter skeletons."""
from __future__ import annotations

import os

from .base import (
    ImageProvider,
    ProviderCapabilities,
    ProviderConfigurationError,
)


class CredentialedSkeletonProvider(ImageProvider):
    env_key = ""
    config_label = "API credentials"
    capabilities = ProviderCapabilities(
        generation=True,
        editing=False,
        aspect_ratios=("1:1", "16:9", "9:16", "4:5", "3:2"),
        maximum_outputs=4,
    )

    @classmethod
    def is_configured(cls) -> bool:
        return bool(os.getenv(cls.env_key))

    async def generate(self, spec):
        raise ProviderConfigurationError(
            self.name,
            f"{self.name} adapter requires a concrete API implementation before production use.",
        )


class FalImageProvider(CredentialedSkeletonProvider):
    name = "fal"
    priority = 30
    env_key = "FAL_KEY"


class BflImageProvider(CredentialedSkeletonProvider):
    name = "bfl"
    priority = 40
    env_key = "BFL_API_KEY"


class ReplicateImageProvider(CredentialedSkeletonProvider):
    name = "replicate"
    priority = 50
    env_key = "REPLICATE_API_TOKEN"
