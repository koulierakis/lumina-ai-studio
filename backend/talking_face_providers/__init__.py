"""Provider-neutral talking-face registry with a local simulation."""
import asyncio
from video_providers.mock_provider import MockVideoProvider
from video_providers.base import VideoGenerationInput

class MockTalkingFaceProvider:
    name = "mock"
    capabilities = {"portrait_to_video": True, "audio_to_lip_sync": True, "image_formats": ["image/png", "image/jpeg", "image/webp"], "audio_formats": ["audio/wav", "audio/mpeg", "audio/ogg", "audio/webm"], "output_formats": ["image/gif"], "max_duration_seconds": 8, "resolutions": ["360x640", "640x360"], "languages": ["en", "el"], "cancellation": True, "credential_ready": True, "simulation": True}
    async def generate(self, script, portrait, audio):
        return await MockVideoProvider().generate(VideoGenerationInput(mode="image-to-video", prompt=script or "Simulated talking portrait", duration_seconds=3, aspect_ratio="16:9", source_images=[portrait], source_mimes=["image/png"]))

def get_talking_face_provider(name="mock"):
    if name != "mock": raise ValueError("The selected talking-video provider is not configured.")
    return MockTalkingFaceProvider()

def talking_face_catalog():
    return [{"name": "mock", "available": True, "capabilities": MockTalkingFaceProvider.capabilities}, *[{"name": n, "available": False, "capabilities": {"credential_ready": False}} for n in ("heygen", "d-id", "tavus", "sync-labs")]]
