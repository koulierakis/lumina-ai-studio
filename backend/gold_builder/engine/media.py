"""Provider-independent media generation, validation and asset persistence."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Iterable, List, Tuple

from .. import workspace
from ..models import GeneratedFile, MediaAsset
from ..providers.base import ImageRequest, ProviderError, VideoRequest
from ..providers.router import router

MAX_IMAGE_INPUT_BYTES = 20 * 1024 * 1024
MAX_VIDEO_INPUT_BYTES = 200 * 1024 * 1024
_ALLOWED_IMAGE_MIMES = {"image/png", "image/jpeg", "image/webp"}
_ALLOWED_VIDEO_MIMES = {"video/mp4", "video/webm", "video/quicktime"}


def _sniff_mime(data: bytes, fallback_name: str = "") -> str:
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if data.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if data.startswith(b"RIFF") and data[8:12] == b"WEBP":
        return "image/webp"
    if len(data) > 12 and data[4:8] == b"ftyp":
        return "video/mp4"
    if len(data) >= 8 and data[4:8] in {b"moov", b"mdat", b"wide", b"free", b"skip"}:
        return "video/quicktime"
    if data.startswith(b"\x1aE\xdf\xa3"):
        return "video/webm"
    return "application/octet-stream"


def _read_project_asset(project: Path, rel_path: str, *, media_type: str) -> tuple[bytes, str]:
    target = workspace.resolve_within(project, rel_path)
    if not target.is_file():
        raise FileNotFoundError(f"media input not found: {rel_path}")
    limit = MAX_IMAGE_INPUT_BYTES if media_type == "image" else MAX_VIDEO_INPUT_BYTES
    size = target.stat().st_size
    if size <= 0 or size > limit:
        raise ValueError(f"{media_type} input size must be between 1 and {limit} bytes")
    data = target.read_bytes()
    mime = _sniff_mime(data, target.name)
    allowed = _ALLOWED_IMAGE_MIMES if media_type == "image" else _ALLOWED_VIDEO_MIMES
    if mime not in allowed:
        raise ValueError(f"unsupported {media_type} MIME type: {mime}")
    return data, target.name


def _validate_output(data: bytes, path: str, media_type: str) -> str:
    if not data:
        raise ProviderError("provider returned an empty media asset")
    mime = _sniff_mime(data, path)
    allowed = _ALLOWED_IMAGE_MIMES if media_type == "image" else _ALLOWED_VIDEO_MIMES
    if mime not in allowed:
        raise ProviderError(f"provider returned unsupported {media_type} MIME type: {mime}")
    return mime


def _write_binary(project: Path, rel_path: str, data: bytes) -> Path:
    # workspace.safe_write rejects absolute paths, traversal and symlink escapes.
    return workspace.safe_write(project, rel_path, data, binary=True)


def _metadata_path(project: Path) -> Path:
    return workspace.resolve_within(project, ".gold-builder/media-assets.json")


def persist_metadata(project: Path, assets: Iterable[MediaAsset]) -> None:
    path = _metadata_path(project)
    path.parent.mkdir(parents=True, exist_ok=True)
    existing: List[dict] = []
    if path.exists():
        try:
            loaded = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(loaded, list):
                existing = [item for item in loaded if isinstance(item, dict)]
        except (OSError, ValueError, TypeError):
            existing = []
    incoming = [a.model_dump() for a in assets]
    incoming_ids = {item.get("id") for item in incoming}
    payload = [item for item in existing if item.get("id") not in incoming_ids] + incoming
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")


async def generate_media(
    project: Path,
    image_specs: List[dict] | None = None,
    video_specs: List[dict] | None = None,
) -> Tuple[List[GeneratedFile], List[MediaAsset]]:
    """Execute planned media operations without placeholders or fabricated success."""
    files: List[GeneratedFile] = []
    assets: List[MediaAsset] = []

    for spec in image_specs or []:
        path = str(spec.get("path") or "").strip()
        prompt = str(spec.get("prompt") or "").strip()
        if not path or not prompt:
            raise ValueError("image spec requires path and prompt")

        operation = str(spec.get("operation") or "generate")
        input_paths: List[str] = []
        primary = spec.get("input_image_path")
        if primary:
            input_paths.append(str(primary))
        for ref in spec.get("reference_images") or []:
            if str(ref) not in input_paths:
                input_paths.append(str(ref))

        input_images: List[bytes] = []
        input_names: List[str] = []
        for rel in input_paths:
            data, name = _read_project_asset(project, rel, media_type="image")
            input_images.append(data)
            input_names.append(name)
        if operation == "edit" and not input_images:
            raise ValueError("image edit requires input_image_path or reference_images")

        req = ImageRequest(
            prompt=prompt,
            n=max(1, min(int(spec.get("number_of_outputs") or 1), 4)),
            size=str(spec.get("size") or "1024x1024"),
            operation=operation,
            input_images=input_images,
            input_image_names=input_names,
            negative_prompt=spec.get("negative_prompt"),
            width=spec.get("width"),
            height=spec.get("height"),
            aspect_ratio=spec.get("aspect_ratio"),
            quality=spec.get("quality"),
            style=spec.get("style"),
            seed=spec.get("seed"),
            output_format=str(spec.get("output_format") or "png"),
        )
        response = await router.generate_image(req)
        if not response.images:
            raise ProviderError("image provider returned no outputs")

        # The planner path names the primary output. Additional outputs get a stable suffix.
        base = Path(path)
        for index, data in enumerate(response.images):
            rel = path if index == 0 else str(base.with_name(f"{base.stem}-{index + 1}{base.suffix}"))
            mime = _validate_output(data, rel, "image")
            _write_binary(project, rel, data)
            files.append(GeneratedFile(path=rel, content=f"<{len(data)} bytes>", binary=True))
            assets.append(MediaAsset(
                media_type="image",
                operation=operation,
                provider=response.provider,
                model=response.model,
                path=rel,
                mime=mime,
                prompt=prompt,
                source_paths=input_paths,
                width=spec.get("width"),
                height=spec.get("height"),
                provider_attempts=list(getattr(response, "provider_attempts", []) or []),
                sequence_id=spec.get("sequence_id"),
                frame_index=spec.get("frame_index"),
                reference_asset_ids=list(spec.get("reference_asset_ids") or []),
                subject_consistency_requested=bool(spec.get("subject_consistency_requested")),
                provider_consistency_capability=(
                    "reference_conditioning"
                    if input_paths and response.provider in {"openai", "gemini", "fal"}
                    else None
                ),
            ))
            persist_metadata(project, assets)

    for spec in video_specs or []:
        path = str(spec.get("path") or "").strip()
        prompt = str(spec.get("prompt") or "").strip()
        if not path or not prompt:
            raise ValueError("video spec requires path and prompt")
        operation = str(spec.get("operation") or "generate")

        input_image = None
        input_video = None
        source_paths: List[str] = []
        if spec.get("input_image_path"):
            rel = str(spec["input_image_path"])
            input_image, _ = _read_project_asset(project, rel, media_type="image")
            source_paths.append(rel)
        if spec.get("input_video_path"):
            rel = str(spec["input_video_path"])
            input_video, _ = _read_project_asset(project, rel, media_type="video")
            source_paths.append(rel)
        references: List[bytes] = []
        for ref in spec.get("reference_images") or []:
            rel = str(ref)
            data, _ = _read_project_asset(project, rel, media_type="image")
            references.append(data)
            source_paths.append(rel)

        if operation in {"animate", "text_image"} and not (input_image or references):
            raise ValueError(f"video operation {operation} requires an input/reference image")
        if operation == "transform" and not input_video:
            raise ValueError("video transform requires input_video_path")

        req = VideoRequest(
            prompt=prompt,
            seconds=float(spec.get("seconds") or 4.0),
            size=str(spec.get("size") or "1024x576"),
            operation=operation,
            input_image=input_image,
            input_video=input_video,
            reference_images=references,
            negative_prompt=spec.get("negative_prompt"),
            aspect_ratio=spec.get("aspect_ratio"),
            quality=spec.get("quality"),
            seed=spec.get("seed"),
            output_format=str(spec.get("output_format") or "mp4"),
            fps=spec.get("fps"),
        )
        response = await router.generate_video(req)
        mime = _validate_output(response.video, path, "video")
        _write_binary(project, path, response.video)
        files.append(GeneratedFile(path=path, content=f"<{len(response.video)} bytes>", binary=True))
        assets.append(MediaAsset(
            media_type="video",
            operation=operation,
            provider=response.provider,
            model=response.model,
            path=path,
            mime=mime,
            prompt=prompt,
            source_paths=source_paths,
            duration=(
                float(response.duration)
                if getattr(response, "duration", None) is not None
                else float(spec.get("seconds") or 4.0)
            ),
            provider_attempts=list(getattr(response, "provider_attempts", []) or []),
            sequence_id=spec.get("sequence_id"),
            reference_asset_ids=list(spec.get("reference_asset_ids") or []),
            subject_consistency_requested=bool(spec.get("subject_consistency_requested")),
            provider_consistency_capability=(
                "reference_video" if response.provider == "fal" and operation == "transform"
                else "reference_conditioning" if source_paths else None
            ),
        ))
        persist_metadata(project, assets)

    persist_metadata(project, assets)
    return files, assets


async def generate_and_save(project: Path, specs: List[dict]) -> List[GeneratedFile]:
    """Backward-compatible image-only wrapper."""
    files, _ = await generate_media(project, image_specs=specs, video_specs=[])
    return files
