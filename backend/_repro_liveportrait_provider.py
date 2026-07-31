    52import asyncio
import json
import tempfile
from pathlib import Path

from talking_portrait_providers import TalkingPortraitInput, get_talking_portrait_provider


async def main() -> None:
    provider = get_talking_portrait_provider("liveportrait", require_installed=True)
    temp_dir = tempfile.mkdtemp(prefix="lumina_lp_repro_")
    output_path = Path(temp_dir) / "lumina_talking_portrait.mp4"
    repo_root = Path(__file__).resolve().parents[1]
    spec = TalkingPortraitInput(
        portrait_path=repo_root / "local_models" / "LivePortrait" / "assets" / "examples" / "source" / "s0.jpg",
        portrait_mime="image/jpeg",
        audio_path=repo_root / "playable_release_evidence" / "samples" / "voice_input.wav",
        audio_mime="audio/wav",
        output_path=output_path,
        fps=25,
        resolution="512",
    )

    async def progress(value: int, message: str) -> None:
        print(f"PROGRESS {value} {message}", flush=True)

    try:
        result = await provider.generate(spec, progress)
        print(json.dumps({
            "ok": True,
            "temp_dir": temp_dir,
            "output": str(output_path),
            "bytes": len(result.data),
            "metadata": result.metadata,
        }, indent=2), flush=True)
    except Exception as exc:
        print(json.dumps({
            "ok": False,
            "temp_dir": temp_dir,
            "exception_type": type(exc).__name__,
            "exception": repr(exc),
            "stage": getattr(exc, "stage", None),
            "safe_message": getattr(exc, "safe_message", None),
            "stdout": getattr(exc, "stdout", None),
            "stderr": getattr(exc, "stderr", None),
            "technical_details": getattr(exc, "technical_details", None),
        }, indent=2), flush=True)
        raise


if __name__ == "__main__":
    asyncio.run(main())
