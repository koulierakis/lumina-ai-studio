"""LivePortrait adapter for local talking portrait generation."""
from __future__ import annotations

import asyncio
import contextlib
import datetime
import hashlib
import json
import os
import signal
import shlex
import shutil
import subprocess
import sys
import time
import wave
from collections import deque
from pathlib import Path

from .base import GeneratedTalkingPortrait, TalkingPortraitCancelledError, TalkingPortraitCapabilities, TalkingPortraitInput, TalkingPortraitProvider, TalkingPortraitProviderError


_RUNNING_INFERENCE: dict[str, object | None] = {"pid": None, "command": None, "started_at": None, "stage": None}


class _LocalLipSyncEngine:
    """Local audio-driven lip-sync runner with MuseTalk preference and Wav2Lip fallback."""

    @classmethod
    def _repo_root(cls) -> Path:
        return Path(__file__).resolve().parents[2]

    @classmethod
    def musetalk_root(cls) -> Path:
        return Path(os.environ.get("MUSETALK_HOME", cls._repo_root() / "local_models" / "MuseTalk"))

    @classmethod
    def wav2lip_root(cls) -> Path:
        return Path(os.environ.get("WAV2LIP_HOME", cls._repo_root() / "local_models" / "Wav2Lip"))

    @classmethod
    def _venv_python(cls, root: Path) -> Path:
        return root / ".venv" / ("Scripts/python.exe" if os.name == "nt" else "bin/python")

    @classmethod
    def _system_python(cls) -> str:
        return sys.executable

    @classmethod
    def _python_for(cls, root: Path) -> str:
        venv = cls._venv_python(root)
        return str(venv if venv.exists() else cls._system_python())

    @classmethod
    def diagnostics(cls) -> dict:
        muse = cls.musetalk_root()
        wav = cls.wav2lip_root()
        muse_entrypoints = [muse / "scripts" / "inference.py", muse / "inference.py", muse / "app.py"]
        wav_entrypoints = [wav / "inference.py"]
        return {
            "preferred_engine": "musetalk",
            "fallback_engine": "wav2lip",
            "musetalk": {
                "root": str(muse),
                "installed": muse.exists() and any(item.exists() for item in muse_entrypoints),
                "python": cls._python_for(muse),
                "entrypoints": [str(item) for item in muse_entrypoints if item.exists()],
            },
            "wav2lip": {
                "root": str(wav),
                "installed": wav.exists() and any(item.exists() for item in wav_entrypoints),
                "python": cls._python_for(wav),
                "entrypoints": [str(item) for item in wav_entrypoints if item.exists()],
            },
        }

    @classmethod
    def available_engine(cls) -> str | None:
        diagnostics = cls.diagnostics()
        if diagnostics["musetalk"]["installed"]:
            return "musetalk"
        if diagnostics["wav2lip"]["installed"]:
            checkpoint = Path(os.environ.get("WAV2LIP_CHECKPOINT", cls.wav2lip_root() / "checkpoints" / "wav2lip_gan.pth"))
            if not checkpoint.exists():
                checkpoint = cls.wav2lip_root() / "checkpoints" / "wav2lip.pth"
            if not checkpoint.exists():
                return None
            return "wav2lip"
        return None

    @classmethod
    async def run(cls, base_video: Path, audio_path: Path, output_path: Path, *, ffmpeg: str, progress=None, fps: int | None = None, should_cancel=None) -> dict:
        _raise_if_cancelled(should_cancel, LivePortraitProvider.name)
        engine = cls.available_engine()
        if not engine:
            diagnostics = cls.diagnostics()
            raise TalkingPortraitProviderError(
                LivePortraitProvider.name,
                "No local audio-driven lip-sync engine is installed. Install MuseTalk in local_models/MuseTalk or Wav2Lip in local_models/Wav2Lip.",
                "A real local lip-sync engine is required. Install MuseTalk locally (preferred) or Wav2Lip before generating Talking Portrait output.",
                stage="lip_sync_preflight",
                technical_details={"lip_sync_diagnostics": diagnostics},
            )
        if progress:
            await progress(72, f"{engine} audio-driven lip-sync started")
        if engine == "musetalk":
            command, cwd = cls._musetalk_command(base_video, audio_path, output_path)
        else:
            command, cwd = cls._wav2lip_command(base_video, audio_path, output_path, fps=fps)
        (cwd / "temp").mkdir(parents=True, exist_ok=True)
        (cwd / "results").mkdir(parents=True, exist_ok=True)
        env = os.environ.copy()
        env["PYTHONIOENCODING"] = "utf-8"
        env["PYTHONUTF8"] = "1"
        env["PATH"] = str(Path(ffmpeg).parent) + os.pathsep + env.get("PATH", "")
        _log_event("lip_sync_started", "Starting local audio-driven lip-sync subprocess", engine=engine, command=command, cwd=str(cwd))
        started = time.time()
        timeout_seconds = int(os.environ.get("TALKING_PORTRAIT_LIPSYNC_TIMEOUT_SECONDS", "1800"))
        process = await asyncio.create_subprocess_exec(*command, cwd=str(cwd), env=env, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE, creationflags=subprocess.CREATE_NEW_PROCESS_GROUP if os.name == "nt" else 0, preexec_fn=None if os.name == "nt" else os.setsid)
        _RUNNING_INFERENCE.update({"pid": process.pid, "command": command, "started_at": _utc_now(), "stage": f"{engine}_lip_sync"})
        try:
            communicate_task = asyncio.create_task(process.communicate())
            while not communicate_task.done():
                _raise_if_cancelled(should_cancel, LivePortraitProvider.name, process.pid)
                await asyncio.sleep(1)
            stdout_data, stderr_data = await asyncio.wait_for(communicate_task, timeout=timeout_seconds)
        except asyncio.TimeoutError as exc:
            _terminate_process_tree(process.pid)
            raise TalkingPortraitProviderError(LivePortraitProvider.name, f"{engine} lip-sync timed out", f"{engine} lip-sync timed out before a complete talking portrait could be generated.", retryable=True, stage="lip_sync", technical_details={"engine": engine, "command": command, "timeout_seconds": timeout_seconds}) from exc
        finally:
            _RUNNING_INFERENCE.update({"pid": None, "command": None, "started_at": None, "stage": None})
        stdout = stdout_data.decode("utf-8", errors="replace") if stdout_data else ""
        stderr = stderr_data.decode("utf-8", errors="replace") if stderr_data else ""
        _log_event("lip_sync_exit", "Local lip-sync subprocess exited", engine=engine, exit_code=process.returncode, elapsed_seconds=round(time.time() - started, 3), stdout_tail=stdout[-4000:], stderr_tail=stderr[-4000:])
        if process.returncode != 0:
            raise TalkingPortraitProviderError(LivePortraitProvider.name, f"{engine} lip-sync failed with exit code {process.returncode}", f"{engine} could not complete audio-driven lip synchronization.", retryable=True, stage="lip_sync", stdout=stdout[-8000:], stderr=stderr[-8000:], technical_details={"engine": engine, "command": command, "cwd": str(cwd), "exit_code": process.returncode})
        candidate = cls._collect_output(output_path, cwd, base_video)
        if candidate != output_path:
            shutil.copyfile(candidate, output_path)
        return {"engine": engine, "command": command, "elapsed_seconds": round(time.time() - started, 3), "stdout_tail": stdout[-1200:], "stderr_tail": stderr[-1200:]}

    @classmethod
    async def run_wav2lip_longform(cls, portrait_path: Path, audio_path: Path, output_path: Path, *, ffmpeg: str, audio_duration: float, progress=None, fps: int | None = None, should_cancel=None) -> dict:
        """Run Wav2Lip in resumable chunks and merge one full-duration MP4."""
        _raise_if_cancelled(should_cancel, LivePortraitProvider.name)
        if cls.available_engine() != "wav2lip":
            return await cls.run(portrait_path, audio_path, output_path, ffmpeg=ffmpeg, progress=progress, fps=fps, should_cancel=should_cancel)
        started = time.time()
        fps = int(fps or 25)
        chunk_seconds = max(1.0, float(os.environ.get("TALKING_PORTRAIT_CHUNK_SECONDS", "10")))
        overlap_seconds = max(0.0, float(os.environ.get("TALKING_PORTRAIT_CHUNK_OVERLAP_SECONDS", "0.5")))
        overlap_seconds = min(overlap_seconds, max(0.0, chunk_seconds / 3.0))
        cleanup = os.environ.get("TALKING_PORTRAIT_CLEANUP_CHUNKS", "1").strip().lower() not in {"0", "false", "no"}
        session = cls._chunk_session_dir(portrait_path, audio_path, audio_duration, fps, chunk_seconds, overlap_seconds)
        chunks_dir = session / "chunks"
        chunks_dir.mkdir(parents=True, exist_ok=True)
        manifest_path = session / "manifest.json"
        chunks = cls._build_chunks(audio_duration, chunk_seconds, overlap_seconds)
        manifest = {"engine": "wav2lip", "portrait_sha256": cls._file_sha256(portrait_path), "audio_sha256": cls._file_sha256(audio_path), "audio_duration_seconds": audio_duration, "fps": fps, "chunk_seconds": chunk_seconds, "overlap_seconds": overlap_seconds, "chunk_count": len(chunks), "chunks": chunks, "created_at": _utc_now(), "updated_at": _utc_now(), "output_path": str(output_path)}
        if manifest_path.exists():
            with contextlib.suppress(Exception):
                previous = json.loads(manifest_path.read_text(encoding="utf-8"))
                if previous.get("audio_sha256") == manifest["audio_sha256"] and previous.get("portrait_sha256") == manifest["portrait_sha256"]:
                    manifest["created_at"] = previous.get("created_at") or manifest["created_at"]
        manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
        chunk_details = []
        concat_entries = []
        for index, chunk in enumerate(chunks):
            _raise_if_cancelled(should_cancel, LivePortraitProvider.name)
            chunk_id = f"chunk_{index:05d}"
            raw_audio = chunks_dir / f"{chunk_id}_input.wav"
            raw_video = chunks_dir / f"{chunk_id}_raw.mp4"
            trimmed_video = chunks_dir / f"{chunk_id}_trimmed.mp4"
            done_marker = chunks_dir / f"{chunk_id}.done.json"
            if trimmed_video.exists() and done_marker.exists() and trimmed_video.stat().st_size > 64 * 1024:
                marker = json.loads(done_marker.read_text(encoding="utf-8"))
                chunk_details.append(marker)
                concat_entries.append(trimmed_video)
                if progress:
                    await progress(cls._chunk_progress(index + 1, len(chunks)), f"Resumed completed Wav2Lip chunk {index + 1}/{len(chunks)}")
                continue
            if progress:
                await progress(cls._chunk_progress(index, len(chunks)), f"Rendering Wav2Lip chunk {index + 1}/{len(chunks)}")
            cls._extract_audio_chunk(ffmpeg, audio_path, raw_audio, chunk["extract_start"], chunk["extract_duration"])
            details = await cls.run(portrait_path, raw_audio, raw_video, ffmpeg=ffmpeg, progress=None, fps=fps, should_cancel=should_cancel)
            _raise_if_cancelled(should_cancel, LivePortraitProvider.name)
            cls._trim_video_chunk(ffmpeg, raw_video, trimmed_video, chunk["trim_start"], chunk["core_duration"])
            marker = {"index": index, "path": str(trimmed_video), "core_start": chunk["core_start"], "core_duration": chunk["core_duration"], "duration": cls._probe_duration(ffmpeg, trimmed_video), "details": details, "completed_at": _utc_now()}
            done_marker.write_text(json.dumps(marker, indent=2), encoding="utf-8")
            chunk_details.append(marker)
            concat_entries.append(trimmed_video)
            manifest["completed_chunks"] = index + 1
            manifest["updated_at"] = _utc_now()
            manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
            if progress:
                await progress(cls._chunk_progress(index + 1, len(chunks)), f"Completed Wav2Lip chunk {index + 1}/{len(chunks)}")
        stitched = session / "stitched_video.mp4"
        _raise_if_cancelled(should_cancel, LivePortraitProvider.name)
        cls._concat_videos(ffmpeg, concat_entries, stitched)
        _raise_if_cancelled(should_cancel, LivePortraitProvider.name)
        cls._merge_audio(ffmpeg, stitched, audio_path, output_path)
        _raise_if_cancelled(should_cancel, LivePortraitProvider.name)
        final = {"engine": "wav2lip", "mode": "chunked_longform", "chunk_seconds": chunk_seconds, "overlap_seconds": overlap_seconds, "chunk_count": len(chunks), "elapsed_seconds": round(time.time() - started, 3), "output_duration_seconds": cls._probe_duration(ffmpeg, output_path), "manifest": str(manifest_path), "chunks": chunk_details}
        manifest["completed_at"] = _utc_now()
        manifest["final"] = final
        manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
        if cleanup:
            keep_dir = session / "cleanup_manifest"
            keep_dir.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(manifest_path, keep_dir / "manifest.json")
            for item in chunks_dir.glob("*"):
                with contextlib.suppress(Exception):
                    item.unlink()
            with contextlib.suppress(Exception):
                chunks_dir.rmdir()
            with contextlib.suppress(Exception):
                stitched.unlink()
        return final

    @classmethod
    def _chunk_progress(cls, completed: int, total: int) -> int:
        return min(88, max(45, 45 + int((max(0, completed) / max(1, total)) * 43)))

    @classmethod
    def _build_chunks(cls, duration: float, chunk_seconds: float, overlap_seconds: float) -> list[dict]:
        chunks = []
        start = 0.0
        index = 0
        while start < duration - 0.001:
            core_duration = min(chunk_seconds, duration - start)
            pre = overlap_seconds if index > 0 else 0.0
            post = overlap_seconds if start + core_duration < duration - 0.001 else 0.0
            extract_start = max(0.0, start - pre)
            chunks.append({"index": index, "core_start": round(start, 6), "core_duration": round(core_duration, 6), "extract_start": round(extract_start, 6), "extract_duration": round(pre + core_duration + post, 6), "trim_start": round(pre, 6), "pre_overlap": round(pre, 6), "post_overlap": round(post, 6)})
            start += core_duration
            index += 1
        return chunks

    @classmethod
    def _chunk_session_dir(cls, portrait_path: Path, audio_path: Path, duration: float, fps: int, chunk_seconds: float, overlap_seconds: float) -> Path:
        digest = hashlib.sha256()
        digest.update(cls._file_sha256(portrait_path).encode("ascii"))
        digest.update(cls._file_sha256(audio_path).encode("ascii"))
        digest.update(f"{duration:.6f}:{fps}:{chunk_seconds}:{overlap_seconds}".encode("utf-8"))
        return cls._repo_root() / "runtime" / "talking_portrait_chunks" / digest.hexdigest()[:24]

    @classmethod
    def _file_sha256(cls, path: Path) -> str:
        digest = hashlib.sha256()
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest()

    @classmethod
    def _extract_audio_chunk(cls, ffmpeg: str, audio_path: Path, output_path: Path, start: float, duration: float) -> None:
        result = subprocess.run([ffmpeg, "-y", "-ss", f"{start:.6f}", "-i", str(audio_path), "-t", f"{duration:.6f}", "-vn", "-ac", "1", "-ar", "16000", str(output_path)], text=True, encoding="utf-8", errors="replace", stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=max(300, int(duration * 20)), shell=False)
        if result.returncode != 0:
            raise TalkingPortraitProviderError(LivePortraitProvider.name, f"Audio chunk extraction failed: {result.stderr}", "Could not prepare a long-form audio chunk for Wav2Lip.", stage="extract_audio_chunk", stdout=result.stdout, stderr=result.stderr, technical_details={"command": result.args})

    @classmethod
    def _trim_video_chunk(cls, ffmpeg: str, input_path: Path, output_path: Path, start: float, duration: float) -> None:
        result = subprocess.run([ffmpeg, "-y", "-ss", f"{start:.6f}", "-i", str(input_path), "-t", f"{duration:.6f}", "-c:v", "libx264", "-pix_fmt", "yuv420p", "-an", str(output_path)], text=True, encoding="utf-8", errors="replace", stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=max(300, int(duration * 30)), shell=False)
        if result.returncode != 0:
            raise TalkingPortraitProviderError(LivePortraitProvider.name, f"Video chunk trim failed: {result.stderr}", "Could not trim a long-form Wav2Lip chunk.", stage="trim_video_chunk", stdout=result.stdout, stderr=result.stderr, technical_details={"command": result.args})

    @classmethod
    def _concat_videos(cls, ffmpeg: str, inputs: list[Path], output_path: Path) -> None:
        concat_file = output_path.with_suffix(".txt")
        concat_file.write_text("\n".join(f"file '{item.resolve().as_posix()}'" for item in inputs) + "\n", encoding="utf-8")
        result = subprocess.run([ffmpeg, "-y", "-f", "concat", "-safe", "0", "-i", str(concat_file), "-c", "copy", str(output_path)], text=True, encoding="utf-8", errors="replace", stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=max(600, len(inputs) * 60), shell=False)
        if result.returncode != 0:
            raise TalkingPortraitProviderError(LivePortraitProvider.name, f"Chunk concat failed: {result.stderr}", "Could not merge long-form Wav2Lip chunks.", stage="concat_chunks", stdout=result.stdout, stderr=result.stderr, technical_details={"command": result.args})

    @classmethod
    def _merge_audio(cls, ffmpeg: str, video_path: Path, audio_path: Path, output_path: Path) -> None:
        audio_duration = cls._probe_duration(ffmpeg, audio_path)
        video_duration = cls._probe_duration(ffmpeg, video_path)
        mux_video = video_path
        pad_result = None
        if video_duration < audio_duration - 0.02:
            padded_video = output_path.with_name(f"{output_path.stem}_video_padded.mp4")
            pad_seconds = max(0.0, audio_duration - video_duration)
            pad_result = subprocess.run([ffmpeg, "-y", "-i", str(video_path), "-vf", f"tpad=stop_mode=clone:stop_duration={pad_seconds:.6f},fps=25", "-t", f"{audio_duration:.6f}", "-c:v", "libx264", "-pix_fmt", "yuv420p", "-an", str(padded_video)], text=True, encoding="utf-8", errors="replace", stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=1800, shell=False)
            if pad_result.returncode != 0:
                raise TalkingPortraitProviderError(LivePortraitProvider.name, f"Final long-form video padding failed: {pad_result.stderr}", "The final long-form video stream could not be extended to the complete uploaded audio duration.", stage="pad_longform_video", stdout=pad_result.stdout, stderr=pad_result.stderr, technical_details={"command": pad_result.args, "video_duration_seconds": video_duration, "audio_duration_seconds": audio_duration})
            mux_video = padded_video
        result = subprocess.run([ffmpeg, "-y", "-i", str(mux_video), "-i", str(audio_path), "-map", "0:v:0", "-map", "1:a:0", "-t", f"{audio_duration:.6f}", "-c:v", "copy", "-c:a", "aac", "-af", "aresample=async=1:first_pts=0", str(output_path)], text=True, encoding="utf-8", errors="replace", stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=1800, shell=False)
        if result.returncode != 0:
            raise TalkingPortraitProviderError(LivePortraitProvider.name, f"Final long-form audio merge failed: {result.stderr}", "The final long-form MP4 could not be muxed with the complete uploaded audio.", stage="merge_longform_audio", stdout=result.stdout, stderr=result.stderr, technical_details={"command": result.args, "video_duration_seconds": video_duration, "audio_duration_seconds": audio_duration, "pad_command": getattr(pad_result, "args", None)})

    @classmethod
    def _probe_duration(cls, ffmpeg: str, path: Path) -> float:
        ffprobe = str(Path(ffmpeg).with_name("ffprobe.exe" if os.name == "nt" else "ffprobe"))
        result = subprocess.run([ffprobe, "-v", "error", "-show_entries", "format=duration", "-of", "default=noprint_wrappers=1:nokey=1", str(path)], text=True, encoding="utf-8", errors="replace", stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=60, shell=False)
        if result.returncode != 0:
            raise TalkingPortraitProviderError(LivePortraitProvider.name, f"Duration probe failed: {result.stderr}", stage="probe_chunk_duration", stdout=result.stdout, stderr=result.stderr, technical_details={"command": result.args})
        return float(result.stdout.strip().splitlines()[-1])

    @classmethod
    def _musetalk_command(cls, base_video: Path, audio_path: Path, output_path: Path) -> tuple[list[str], Path]:
        root = cls.musetalk_root()
        python = cls._python_for(root)
        candidates = [root / "scripts" / "inference.py", root / "inference.py", root / "app.py"]
        entry = next((item for item in candidates if item.exists()), candidates[0])
        command = os.environ.get("MUSETALK_COMMAND")
        if command:
            return ([part.format(video=str(base_video), audio=str(audio_path), output=str(output_path)) for part in shlex.split(command)], root)
        return ([python, str(entry), "--video", str(base_video), "--audio", str(audio_path), "--result_dir", str(output_path.parent), "--output_path", str(output_path)], root)

    @classmethod
    def _wav2lip_command(cls, base_video: Path, audio_path: Path, output_path: Path, *, fps: int | None = None) -> tuple[list[str], Path]:
        root = cls.wav2lip_root()
        python = cls._python_for(root)
        checkpoint = Path(os.environ.get("WAV2LIP_CHECKPOINT", root / "checkpoints" / "wav2lip_gan.pth"))
        if not checkpoint.exists():
            checkpoint = root / "checkpoints" / "wav2lip.pth"
        command = [python, "inference.py", "--checkpoint_path", str(checkpoint), "--face", str(base_video), "--audio", str(audio_path), "--outfile", str(output_path)]
        if fps:
            command += ["--fps", str(fps)]
        return (command, root)

    @classmethod
    def _collect_output(cls, output_path: Path, cwd: Path, base_video: Path) -> Path:
        if output_path.exists() and output_path.stat().st_size > 0:
            return output_path
        candidates = sorted([item for root in {output_path.parent, cwd / "results", cwd / "result"} if root.exists() for item in root.glob("*.mp4") if item.resolve() != base_video.resolve()], key=lambda item: item.stat().st_mtime, reverse=True)
        if candidates:
            return candidates[0]
        raise TalkingPortraitProviderError(LivePortraitProvider.name, "Lip-sync engine produced no MP4", "The local lip-sync engine finished but did not produce a final MP4.", stage="collect_lip_sync_output", technical_details={"output_path": str(output_path), "cwd": str(cwd)})


def _runtime_log_path() -> Path:
    path = Path(__file__).resolve().parents[2] / "runtime" / "logs" / "talking_portrait.log"
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def _utc_now() -> str:
    return datetime.datetime.now(datetime.timezone.utc).isoformat().replace("+00:00", "Z")


def _log_event(stage: str, message: str, **details) -> None:
    record = {"timestamp": _utc_now(), "stage": stage, "message": message, **details}
    with _runtime_log_path().open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, ensure_ascii=False, default=str) + "\n")


def latest_log_lines(limit: int = 80) -> list[str]:
    path = _runtime_log_path()
    if not path.exists():
        return []
    return path.read_text(encoding="utf-8", errors="replace").splitlines()[-max(1, min(limit, 500)):]


def _relevant_env(env: dict[str, str]) -> dict[str, str]:
    prefixes = ("PYTHON", "CUDA", "CUDNN", "TORCH", "FFMPEG", "PATH", "LIVEPORTRAIT")
    return {key: value for key, value in env.items() if key.upper().startswith(prefixes)}


async def _stream_pipe(pipe: asyncio.StreamReader | None, stream_name: str, lines: deque[str], stage_ref: dict[str, str]) -> None:
    if pipe is None:
        return
    while True:
        chunk = await pipe.readline()
        if not chunk:
            break
        text = chunk.decode("utf-8", errors="replace").rstrip("\r\n")
        lines.append(text)
        _log_event(stage_ref.get("stage", "subprocess"), f"subprocess {stream_name}", stream=stream_name, line=text)


def _terminate_process_tree(pid: int | None) -> None:
    if not pid:
        return
    if os.name == "nt":
        subprocess.run(["taskkill", "/PID", str(pid), "/T", "/F"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, shell=False)
        return
    with contextlib.suppress(ProcessLookupError):
        os.killpg(pid, signal.SIGTERM)
    time.sleep(2)
    with contextlib.suppress(ProcessLookupError):
        os.killpg(pid, signal.SIGKILL)


def _raise_if_cancelled(should_cancel, provider: str, pid: int | None = None) -> None:
    if should_cancel and should_cancel():
        if pid:
            _terminate_process_tree(pid)
        raise TalkingPortraitCancelledError(provider)


class LivePortraitProvider(TalkingPortraitProvider):
    name = "liveportrait"
    display_name = "LivePortrait"
    repository_url = "https://github.com/KwaiVGI/LivePortrait.git"
    capabilities = TalkingPortraitCapabilities()

    @classmethod
    def install_root(cls) -> Path:
        return Path(os.environ.get("LIVEPORTRAIT_HOME", Path(__file__).resolve().parents[2] / "local_models" / "LivePortrait"))

    @classmethod
    def venv_python(cls) -> Path:
        root = cls.install_root()
        return root / ".venv" / ("Scripts/python.exe" if os.name == "nt" else "bin/python")

    @classmethod
    def checkpoint_root(cls) -> Path:
        return Path(os.environ.get("LIVEPORTRAIT_CHECKPOINTS", cls.install_root() / "pretrained_weights"))

    @classmethod
    def is_installed(cls) -> bool:
        diagnostics = cls.diagnostics(quick=True)
        return bool(diagnostics.get("installed"))

    @classmethod
    def diagnostics(cls, quick: bool = False) -> dict:
        root = cls.install_root()
        python = cls.venv_python()
        checkpoints = cls.checkpoint_root()
        repository_ready = root.exists() and (root / "inference.py").exists()
        environment_ready = python.exists()
        checkpoints_ready = cls._checkpoints_ready(checkpoints)
        ffmpeg_path = cls._find_ffmpeg()
        ffmpeg_ready = bool(ffmpeg_path)
        compute_mode = "cpu"
        gpu_name = None
        torch_version = None
        imports_ready = False
        inference_ready = False
        last_error = None
        if environment_ready and not quick:
            try:
                code = "import json, torch; import cv2, numpy, imageio; print(json.dumps({'torch_version': torch.__version__, 'cuda': bool(torch.cuda.is_available()), 'gpu': torch.cuda.get_device_name(0) if torch.cuda.is_available() else None}))"
                result = subprocess.run([str(python), "-c", code], cwd=str(root), text=True, encoding="utf-8", errors="replace", stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=30, shell=False)
                if result.returncode == 0:
                    imports_ready = True
                    data = json.loads(result.stdout.strip().splitlines()[-1])
                    torch_version = data.get("torch_version")
                    compute_mode = "cuda" if data.get("cuda") else "cpu"
                    gpu_name = data.get("gpu")
                else:
                    last_error = (result.stderr or result.stdout)[-1200:]
            except Exception as exc:
                last_error = str(exc)[-1200:]
        elif environment_ready and quick:
            imports_ready = True
        inference_ready = repository_ready and environment_ready and imports_ready and checkpoints_ready and ffmpeg_ready
        return {
            "installed": inference_ready,
            "healthy": inference_ready,
            "installation_state": "installed" if inference_ready else "missing_or_incomplete",
            "provider_version": cls._provider_version(root),
            "install_root": str(root),
            "repository_path": str(root),
            "environment_path": str(root / ".venv"),
            "python": str(python),
            "checkpoints": str(checkpoints),
            "checkpoints_present": checkpoints_ready,
            "checkpoints_ready": checkpoints_ready,
            "ffmpeg_ready": ffmpeg_ready,
            "ffmpeg_path": ffmpeg_path,
            "inference_ready": inference_ready,
            "compute_mode": compute_mode,
            "gpu": compute_mode == "cuda",
            "gpu_name": gpu_name,
            "torch_version": torch_version,
            "cpu_fallback": compute_mode == "cpu",
            "last_install_error": last_error,
            "last_verified_at": None if quick else __import__("datetime").datetime.now(__import__("datetime").timezone.utc).isoformat().replace("+00:00", "Z"),
            "windows": os.name == "nt",
            "checkpoint_inventory": cls.checkpoint_inventory(),
            "lip_sync": _LocalLipSyncEngine.diagnostics(),
            "lip_sync_engine": _LocalLipSyncEngine.available_engine(),
            "running_inference": dict(_RUNNING_INFERENCE),
            "latest_log_lines": latest_log_lines(80),
        }

    @classmethod
    def generation_readiness(cls, diagnostics: dict | None = None) -> dict:
        diagnostics = diagnostics or cls.diagnostics(quick=True)
        inference_ready = bool(diagnostics.get("inference_ready"))
        lip_sync_engine = diagnostics.get("lip_sync_engine")
        operational = inference_ready and bool(lip_sync_engine)
        if operational:
            reason = "LivePortrait and local lip-sync engine are ready."
        elif not inference_ready:
            reason = "LivePortrait inference environment is not ready."
        else:
            reason = "A local lip-sync engine is required. Install MuseTalk or Wav2Lip before generating Talking Portrait output."
        return {"operational": operational, "reason": reason, "inference_ready": inference_ready, "lip_sync_engine": lip_sync_engine}

    @classmethod
    def checkpoint_inventory(cls) -> list[dict]:
        checkpoints = cls.checkpoint_root()
        inventory = []
        for label, relative in (("liveportrait", "liveportrait"), ("insightface", "insightface")):
            path = checkpoints / relative
            files = [str(item) for item in path.rglob("*") if item.is_file()] if path.exists() else []
            inventory.append({"name": label, "path": str(path), "exists": path.exists(), "file_count": len(files), "sample_files": files[:20]})
        return inventory

    @classmethod
    def _find_ffmpeg(cls) -> str | None:
        repo = Path(__file__).resolve().parents[2]
        for item in list((repo / "tools" / "ffmpeg").glob("**/bin/ffmpeg.exe")) + list((repo / "tools" / "ffmpeg").glob("**/ffmpeg.exe")):
            if item.exists():
                return str(item)
        return shutil.which("ffmpeg")

    @classmethod
    def _checkpoints_ready(cls, checkpoints: Path) -> bool:
        if not checkpoints.exists():
            return False
        files = [item for item in checkpoints.rglob("*") if item.is_file() and item.name != ".lumina_checkpoint_inventory.json"]
        if not files:
            return False
        has_liveportrait = any("liveportrait" in str(item).lower() for item in files)
        has_insightface = any("insightface" in str(item).lower() for item in files)
        return has_liveportrait and has_insightface

    @classmethod
    def _provider_version(cls, root: Path) -> str | None:
        git = shutil.which("git")
        if git and (root / ".git").exists():
            try:
                result = subprocess.run([git, "rev-parse", "--short", "HEAD"], cwd=str(root), text=True, encoding="utf-8", errors="replace", stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, timeout=10, shell=False)
                if result.returncode == 0:
                    return result.stdout.strip()
            except Exception:
                return None
        return None

    async def generate(self, spec: TalkingPortraitInput, progress=None) -> GeneratedTalkingPortrait:
        _raise_if_cancelled(spec.should_cancel, self.name)
        _log_event("request_received", "LivePortrait generation request received", portrait_path=str(spec.portrait_path), audio_path=str(spec.audio_path), output_path=str(spec.output_path))
        if not self.is_installed():
            _log_event("provider_selected", "LivePortrait provider failed validation", diagnostics=self.diagnostics())
            raise TalkingPortraitProviderError(self.name, "LivePortrait is not installed", "Install LivePortrait before generating talking portraits. LivePortrait is not installed or failed validation.", stage="preflight", technical_details=self.diagnostics())
        root = self.install_root()
        python = self.venv_python()
        ffmpeg = self._find_ffmpeg()
        if not ffmpeg:
            raise TalkingPortraitProviderError(self.name, "FFmpeg is required for Talking Portrait duration and A/V validation", "FFmpeg is required to generate and validate the final talking portrait MP4.", stage="preflight")
        _log_event("input_files_validated", "Input paths before provider execution", portrait_exists=spec.portrait_path.exists(), portrait_size=spec.portrait_path.stat().st_size if spec.portrait_path.exists() else None, audio_exists=spec.audio_path.exists(), audio_size=spec.audio_path.stat().st_size if spec.audio_path.exists() else None)
        _log_event("provider_selected", "LivePortrait provider selected", install_root=str(root), python=str(python), ffmpeg=ffmpeg)
        _log_event("checkpoint_validation", "Checkpoint validation started", checkpoint_root=str(self.checkpoint_root()))
        diagnostics = self.diagnostics()
        _log_event("checkpoint_validation", "Checkpoint validation completed", checkpoints_ready=diagnostics.get("checkpoints_ready"), checkpoint_inventory=diagnostics.get("checkpoint_inventory"))
        audio_duration = self._media_duration_seconds(spec.audio_path, ffmpeg)
        if audio_duration <= 0:
            raise TalkingPortraitProviderError(self.name, "Uploaded audio duration could not be measured", "The uploaded audio could not be decoded for duration validation.", stage="input_validation", technical_details={"audio_path": str(spec.audio_path)})
        lip_sync_engine = _LocalLipSyncEngine.available_engine()
        if not lip_sync_engine:
            raise TalkingPortraitProviderError(self.name, "No local audio-driven lip-sync engine is installed", "A real local lip-sync engine is required. Install MuseTalk locally (preferred) or Wav2Lip before generating Talking Portrait output.", stage="lip_sync_preflight", technical_details={"lip_sync": _LocalLipSyncEngine.diagnostics()})
        if progress:
            await progress(38, f"Validated full audio duration: {audio_duration:.2f}s; lip-sync engine: {lip_sync_engine}")
        _raise_if_cancelled(spec.should_cancel, self.name)
        if lip_sync_engine == "wav2lip":
            _log_event("wav2lip_direct_selected", "Using Wav2Lip directly because LivePortrait CPU output truncated real driving frames", portrait_path=str(spec.portrait_path), audio_path=str(spec.audio_path), audio_duration_seconds=audio_duration)
            if progress:
                await progress(45, "Wav2Lip direct full-audio lip-sync started")
            _raise_if_cancelled(spec.should_cancel, self.name)
            started = time.time()
            lip_sync_details = await _LocalLipSyncEngine.run_wav2lip_longform(spec.portrait_path, spec.audio_path, spec.output_path, ffmpeg=ffmpeg, audio_duration=audio_duration, progress=progress, fps=spec.fps, should_cancel=spec.should_cancel)
            _raise_if_cancelled(spec.should_cancel, self.name)
            output_duration = self._media_duration_seconds(spec.output_path, ffmpeg)
            _raise_if_cancelled(spec.should_cancel, self.name)
            self._validate_final_output(spec.output_path, audio_duration, output_duration)
            diagnostics = self.diagnostics()
            _log_event("final_mp4_validated", "Final Wav2Lip-direct MP4 validated against full uploaded audio duration", output_path=str(spec.output_path), size_bytes=spec.output_path.stat().st_size, audio_duration_seconds=audio_duration, output_duration_seconds=output_duration, lip_sync_engine=lip_sync_details.get("engine"))
            if progress:
                await progress(92, "Wav2Lip direct talking portrait render complete")
            _raise_if_cancelled(spec.should_cancel, self.name)
            return GeneratedTalkingPortrait(spec.output_path.read_bytes(), "video/mp4", duration_seconds=output_duration, metadata={"engine": "Wav2Lip", "base_motion_engine": None, "lip_sync_engine": lip_sync_details.get("engine"), "provider": self.name, "gpu": diagnostics.get("gpu", False), "compute_mode": diagnostics.get("compute_mode", "cpu"), "audio_duration_seconds": audio_duration, "output_duration_seconds": output_duration, "duration_delta_seconds": abs(output_duration - audio_duration), "duration_seconds_wallclock": round(time.time() - started, 3), "real_inference": True, "mock": False, "lip_sync": lip_sync_details, "long_form": True})
        _log_event("model_loading_started", "LivePortrait model loading will occur in upstream inference process", audio_duration_seconds=audio_duration, lip_sync_engine=lip_sync_engine)
        _raise_if_cancelled(spec.should_cancel, self.name)
        driving_path = self._prepare_audio_driving_video(spec, ffmpeg)
        liveportrait_output = spec.output_path.with_name("lumina_liveportrait_base_motion.mp4")
        final_lipsync_output = spec.output_path
        env = os.environ.copy()
        env["PYTHONIOENCODING"] = "utf-8"
        env["PYTHONUTF8"] = "1"
        env["PYTHONLEGACYWINDOWSSTDIO"] = "0"
        env.setdefault("TERM", "xterm-256color")
        if ffmpeg:
            env["PATH"] = str(Path(ffmpeg).parent) + os.pathsep + env.get("PATH", "")
        command = [
            str(python), "inference.py",
            "-s", str(spec.portrait_path),
            "-d", str(driving_path),
            "-o", str(spec.output_path.parent),
            "--source-max-dim", "512",
            "--no-flag-use-half-precision",
        ]
        if spec.seed is not None and self._inference_supports_option(root, python, "--seed"):
            command += ["--seed", str(spec.seed)]
        if not diagnostics.get("gpu"):
            command += ["--flag-force-cpu", "--no-flag-pasteback", "--no-flag-stitching"]
        _log_event("liveportrait_command_built", "LivePortrait command built", command=command, command_line=subprocess.list2cmdline(command), cwd=str(root))
        _log_event("environment", "LivePortrait execution environment", python_executable=str(python), cwd=str(root), env=_relevant_env(env), selected_device=diagnostics.get("compute_mode"), torch_version=diagnostics.get("torch_version"))
        if progress:
            await progress(45, "LivePortrait base facial animation started")
        _raise_if_cancelled(spec.should_cancel, self.name)
        started = time.time()
        timeout_seconds = int(os.environ.get("LIVEPORTRAIT_TIMEOUT_SECONDS", "600"))
        stdout_lines: deque[str] = deque(maxlen=400)
        stderr_lines: deque[str] = deque(maxlen=400)
        stage_ref = {"stage": "inference_started"}
        process = None
        heartbeat_task = None
        async def inference_heartbeat() -> None:
            if not progress:
                return
            while True:
                await asyncio.sleep(5)
                elapsed = time.time() - started
                computed = min(90, max(46, 45 + int((elapsed / max(timeout_seconds, 1)) * 45)))
                await progress(min(70, computed), f"LivePortrait base facial animation running: {stage_ref.get('stage') or 'inference'}")
        try:
            creationflags = subprocess.CREATE_NEW_PROCESS_GROUP if os.name == "nt" else 0
            preexec_fn = None if os.name == "nt" else os.setsid
            _log_event("subprocess_started", "Starting LivePortrait subprocess", command=command, timeout_seconds=timeout_seconds)
            process = await asyncio.create_subprocess_exec(*command, cwd=str(root), env=env, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE, creationflags=creationflags, preexec_fn=preexec_fn)
            _RUNNING_INFERENCE.update({"pid": process.pid, "command": command, "started_at": _utc_now(), "stage": "inference_started"})
            _log_event("subprocess_pid", "LivePortrait subprocess PID captured", pid=process.pid)
            _log_event("model_loading_completed", "Upstream process started; model load completion depends on subprocess output", pid=process.pid)
            _log_event("inference_started", "LivePortrait inference started", pid=process.pid, elapsed_seconds=0)
            stdout_task = asyncio.create_task(_stream_pipe(process.stdout, "stdout", stdout_lines, stage_ref))
            stderr_task = asyncio.create_task(_stream_pipe(process.stderr, "stderr", stderr_lines, stage_ref))
            heartbeat_task = asyncio.create_task(inference_heartbeat())
            try:
                wait_task = asyncio.create_task(process.wait())
                while not wait_task.done():
                    _raise_if_cancelled(spec.should_cancel, self.name, process.pid)
                    await asyncio.sleep(1)
                await asyncio.wait_for(wait_task, timeout=timeout_seconds)
            except asyncio.TimeoutError as exc:
                elapsed = round(time.time() - started, 3)
                last_stdout = list(stdout_lines)[-40:]
                last_stderr = list(stderr_lines)[-40:]
                _log_event("inference_timeout", "LivePortrait inference hard timeout reached", pid=process.pid, elapsed_seconds=elapsed, timeout_seconds=timeout_seconds, last_completed_stage=stage_ref.get("stage"), last_stdout=last_stdout, last_stderr=last_stderr)
                _terminate_process_tree(process.pid)
                with contextlib.suppress(Exception):
                    await asyncio.wait_for(process.wait(), timeout=10)
                raise TalkingPortraitProviderError(self.name, "LivePortrait timed out", "LivePortrait timed out after 10 minutes during real inference. The child process tree was terminated.", retryable=True, stage=stage_ref.get("stage", "inference"), stdout="\n".join(last_stdout), stderr="\n".join(last_stderr), technical_details={"command": command, "command_line": subprocess.list2cmdline(command), "cwd": str(root), "pid": process.pid, "elapsed_seconds": elapsed, "timeout_seconds": timeout_seconds, "last_completed_stage": stage_ref.get("stage"), "last_stdout_lines": last_stdout, "last_stderr_lines": last_stderr}) from exc
            finally:
                if heartbeat_task:
                    heartbeat_task.cancel()
                    with contextlib.suppress(asyncio.CancelledError):
                        await heartbeat_task
                await asyncio.gather(stdout_task, stderr_task, return_exceptions=True)
            stdout = "\n".join(stdout_lines)
            stderr = "\n".join(stderr_lines)
            _log_event("subprocess_exit", "LivePortrait subprocess exited", pid=process.pid, exit_code=process.returncode, elapsed_seconds=round(time.time() - started, 3), stdout_tail=list(stdout_lines)[-40:], stderr_tail=list(stderr_lines)[-40:])
        except asyncio.TimeoutError as exc:
            raise TalkingPortraitProviderError(self.name, "LivePortrait timed out", "LivePortrait timed out during real inference.", retryable=True, stage="inference", technical_details={"command": command}) from exc
        finally:
            _RUNNING_INFERENCE.update({"pid": None, "command": None, "started_at": None, "stage": None})
        if process.returncode != 0:
            out_text = stdout
            err_text = stderr
            raise TalkingPortraitProviderError(self.name, f"LivePortrait failed at inference with exit code {process.returncode}\nSTDOUT:\n{out_text}\nSTDERR:\n{err_text}", f"LivePortrait failed at inference with exit code {process.returncode}\nSTDOUT:\n{out_text[-4000:]}\nSTDERR:\n{err_text[-4000:]}", retryable=True, stage="inference", stdout=out_text[-8000:], stderr=err_text[-8000:], technical_details={"command": command, "cwd": str(root), "exit_code": process.returncode})
        _raise_if_cancelled(spec.should_cancel, self.name)
        _log_event("inference_completed", "LivePortrait inference completed", pid=process.pid, elapsed_seconds=round(time.time() - started, 3), exit_code=process.returncode)
        candidates = sorted([item for item in spec.output_path.parent.glob("*.mp4") if item.resolve() != driving_path.resolve()], key=lambda item: item.stat().st_mtime, reverse=True)
        if candidates and candidates[0] != liveportrait_output:
            shutil.copyfile(candidates[0], liveportrait_output)
        if not liveportrait_output.exists():
            raise TalkingPortraitProviderError(self.name, "LivePortrait produced no MP4", "LivePortrait completed but produced no MP4 output.", stage="collect_output", stdout=stdout[-8000:], stderr=stderr[-8000:], technical_details={"command": command, "output_dir": str(spec.output_path.parent)})
        _log_event("video_file_created", "LivePortrait base facial animation MP4 located", output_path=str(liveportrait_output), size_bytes=liveportrait_output.stat().st_size)
        if liveportrait_output.stat().st_size < 64 * 1024:
            raise TalkingPortraitProviderError(self.name, f"LivePortrait produced an invalid MP4: {liveportrait_output.stat().st_size} bytes", "LivePortrait produced an invalid MP4 file.", stage="validate_output", technical_details={"output_path": str(liveportrait_output), "size_bytes": liveportrait_output.stat().st_size})
        _raise_if_cancelled(spec.should_cancel, self.name)
        lip_sync_details = await _LocalLipSyncEngine.run(liveportrait_output, spec.audio_path, final_lipsync_output, ffmpeg=ffmpeg, progress=progress, should_cancel=spec.should_cancel)
        if progress:
            await progress(88, "Merging original full audio and validating A/V duration")
        muxed_output = spec.output_path.with_name("lumina_talking_portrait_full_audio.mp4")
        _raise_if_cancelled(spec.should_cancel, self.name)
        self._merge_original_audio(final_lipsync_output, spec.audio_path, muxed_output, ffmpeg)
        _raise_if_cancelled(spec.should_cancel, self.name)
        shutil.copyfile(muxed_output, spec.output_path)
        output_duration = self._media_duration_seconds(spec.output_path, ffmpeg)
        _raise_if_cancelled(spec.should_cancel, self.name)
        self._validate_final_output(spec.output_path, audio_duration, output_duration)
        _log_event("final_mp4_validated", "Final MP4 validated against full uploaded audio duration", output_path=str(spec.output_path), size_bytes=spec.output_path.stat().st_size, audio_duration_seconds=audio_duration, output_duration_seconds=output_duration, lip_sync_engine=lip_sync_details.get("engine"))
        if progress:
            await progress(92, "Audio-driven talking portrait render complete")
        _raise_if_cancelled(spec.should_cancel, self.name)
        diagnostics = self.diagnostics()
        return GeneratedTalkingPortrait(spec.output_path.read_bytes(), "video/mp4", duration_seconds=output_duration, metadata={"engine": "LivePortrait+local-lip-sync", "base_motion_engine": "LivePortrait", "lip_sync_engine": lip_sync_details.get("engine"), "provider": self.name, "gpu": diagnostics.get("gpu", False), "compute_mode": diagnostics.get("compute_mode", "cpu"), "audio_duration_seconds": audio_duration, "output_duration_seconds": output_duration, "duration_delta_seconds": abs(output_duration - audio_duration), "duration_seconds_wallclock": round(time.time() - started, 3), "real_inference": True, "mock": False, "lip_sync": lip_sync_details})

    @classmethod
    def _prepare_audio_driving_video(cls, spec: TalkingPortraitInput, ffmpeg: str | None) -> Path:
        suffix = spec.audio_path.suffix.lower()
        if suffix in {".mp4", ".mov", ".mkv", ".avi", ".webm"}:
            return spec.audio_path
        if not ffmpeg:
            raise TalkingPortraitProviderError(cls.name, "FFmpeg is required to build an audio-synchronized LivePortrait driving video", stage="prepare_driving_video", technical_details={"audio_path": str(spec.audio_path)})
        repo_python = cls.venv_python()
        driving_video = spec.output_path.parent / "lumina_liveportrait_audio_driver.mp4"
        temp_wav = spec.output_path.parent / "lumina_liveportrait_audio_driver.wav"
        temp_silent = spec.output_path.parent / "lumina_liveportrait_audio_driver_silent.mp4"
        driver_fps = max(6, min(int(os.environ.get("LIVEPORTRAIT_CPU_DRIVER_FPS", "8")), int(spec.fps or 25)))
        _log_event("audio_mux_started", "Preparing audio-reactive LivePortrait driving video", ffmpeg=ffmpeg, audio_path=str(spec.audio_path), driving_video=str(driving_video), driver_fps=driver_fps)
        convert = subprocess.run([ffmpeg, "-y", "-i", str(spec.audio_path), "-ac", "1", "-ar", "16000", str(temp_wav)], text=True, encoding="utf-8", errors="replace", stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=300, shell=False)
        if convert.returncode != 0:
            raise TalkingPortraitProviderError(cls.name, f"Audio decode failed while preparing LivePortrait driving video: {convert.stderr}", stage="prepare_driving_video", stdout=convert.stdout, stderr=convert.stderr, technical_details={"command": convert.args})
        script = """
from pathlib import Path
from talking_portrait_providers.liveportrait_provider import LivePortraitProvider
from talking_portrait_providers.base import TalkingPortraitInput
LivePortraitProvider._write_audio_reactive_driver_frames(Path(__import__('sys').argv[1]), Path(__import__('sys').argv[2]), Path(__import__('sys').argv[3]), TalkingPortraitInput(portrait_path=Path(__import__('sys').argv[1]), portrait_mime='image/jpeg', audio_path=Path(__import__('sys').argv[2]), audio_mime='audio/wav', output_path=Path(__import__('sys').argv[3]), fps=int(__import__('sys').argv[4]), head_motion=float(__import__('sys').argv[5]), natural_blinking=__import__('sys').argv[6].lower() == 'true'))
""".strip()
        env = os.environ.copy()
        env["PYTHONPATH"] = str(Path(__file__).resolve().parents[1]) + os.pathsep + env.get("PYTHONPATH", "")
        render = subprocess.run([str(repo_python), "-c", script, str(spec.portrait_path), str(temp_wav), str(temp_silent), str(driver_fps), str(spec.head_motion), str(spec.natural_blinking)], text=True, encoding="utf-8", errors="replace", stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=600, shell=False, env=env)
        if render.returncode != 0:
            raise TalkingPortraitProviderError(cls.name, f"Driving video render failed: {render.stderr}", stage="prepare_driving_video", stdout=render.stdout, stderr=render.stderr, technical_details={"command": render.args})
        merge = subprocess.run([ffmpeg, "-y", "-i", str(temp_silent), "-i", str(spec.audio_path), "-map", "0:v:0", "-map", "1:a:0", "-c:v", "copy", "-c:a", "aac", str(driving_video)], text=True, encoding="utf-8", errors="replace", stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=300, shell=False)
        if merge.returncode != 0:
            raise TalkingPortraitProviderError(cls.name, f"Audio merge failed while preparing LivePortrait driving video: {merge.stderr}", stage="prepare_driving_video", stdout=merge.stdout, stderr=merge.stderr, technical_details={"command": merge.args})
        _log_event("audio_mux_completed", "Audio-reactive driving video prepared", driving_video=str(driving_video), size_bytes=driving_video.stat().st_size if driving_video.exists() else None)
        return driving_video

    @classmethod
    def _write_audio_reactive_driver_frames(cls, portrait_path: Path, wav_path: Path, silent_video_path: Path, spec: TalkingPortraitInput) -> None:
        import cv2
        import numpy as np
        image = cv2.imread(str(portrait_path), cv2.IMREAD_COLOR)
        if image is None:
            raise TalkingPortraitProviderError(cls.name, "Reference portrait could not be decoded for LivePortrait driving video preparation", stage="prepare_driving_video", technical_details={"portrait_path": str(portrait_path)})
        with wave.open(str(wav_path), "rb") as audio:
            rate = audio.getframerate()
            frames = audio.getnframes()
            samples = np.frombuffer(audio.readframes(frames), dtype=np.int16).astype(np.float32)
        duration = max(frames / float(rate), 0.25)
        fps = max(6, min(int(spec.fps or 25), 30))
        frame_count = max(2, int(duration * fps))
        h, w = image.shape[:2]
        scale = min(512 / max(h, w), 1.0)
        if scale != 1.0:
            image = cv2.resize(image, (int(w * scale), int(h * scale)), interpolation=cv2.INTER_AREA)
            h, w = image.shape[:2]
        fourcc = cv2.VideoWriter_fourcc(*"mp4v")
        writer = cv2.VideoWriter(str(silent_video_path), fourcc, fps, (w, h))
        if not writer.isOpened():
            raise TalkingPortraitProviderError(cls.name, "OpenCV could not create the LivePortrait driving video", stage="prepare_driving_video", technical_details={"video_path": str(silent_video_path), "fps": fps, "size": [w, h]})
        samples_per_frame = max(1, int(rate / fps))
        max_amp = max(float(np.max(np.abs(samples))) if samples.size else 0.0, 1.0)
        cx, cy = w // 2, int(h * 0.66)
        for idx in range(frame_count):
            start = idx * samples_per_frame
            chunk = samples[start:start + samples_per_frame]
            amp = float(np.sqrt(np.mean(chunk * chunk)) / max_amp) if chunk.size else 0.0
            amp = min(1.0, amp * 3.2)
            frame = image.copy()
            shift_x = int(np.sin(idx / max(fps, 1) * 2.2) * spec.head_motion * 5)
            shift_y = int(np.sin(idx / max(fps, 1) * 1.4) * spec.head_motion * 3)
            matrix = np.float32([[1, 0, shift_x], [0, 1, shift_y]])
            frame = cv2.warpAffine(frame, matrix, (w, h), borderMode=cv2.BORDER_REFLECT)
            mouth_w = max(18, int(w * 0.13))
            mouth_h = max(4, int(h * (0.012 + 0.045 * amp)))
            overlay = frame.copy()
            cv2.ellipse(overlay, (cx, cy), (mouth_w, mouth_h), 0, 0, 360, (20, 8, 8), -1)
            frame = cv2.addWeighted(overlay, 0.28 + 0.22 * amp, frame, 0.72 - 0.22 * amp, 0)
            if spec.natural_blinking and idx % max(1, int(fps * 3.1)) in {0, 1}:
                eye_y = int(h * 0.40)
                cv2.line(frame, (int(w * 0.33), eye_y), (int(w * 0.43), eye_y), (25, 25, 25), 2)
                cv2.line(frame, (int(w * 0.57), eye_y), (int(w * 0.67), eye_y), (25, 25, 25), 2)
            writer.write(frame)
        writer.release()

    @classmethod
    def _media_duration_seconds(cls, path: Path, ffmpeg: str) -> float:
        ffprobe = str(Path(ffmpeg).with_name("ffprobe.exe" if os.name == "nt" else "ffprobe"))
        if not Path(ffprobe).exists():
            ffprobe = shutil.which("ffprobe") or ffprobe
        result = subprocess.run([ffprobe, "-v", "error", "-show_entries", "format=duration", "-of", "default=noprint_wrappers=1:nokey=1", str(path)], text=True, encoding="utf-8", errors="replace", stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=60, shell=False)
        if result.returncode != 0:
            raise TalkingPortraitProviderError(cls.name, f"Could not measure media duration: {result.stderr}", "LUMINA could not validate media duration for the talking portrait pipeline.", stage="duration_probe", stdout=result.stdout, stderr=result.stderr, technical_details={"path": str(path), "command": result.args})
        try:
            return float((result.stdout or "0").strip().splitlines()[-1])
        except Exception as exc:
            raise TalkingPortraitProviderError(cls.name, f"Invalid media duration probe output: {result.stdout}", "LUMINA could not validate media duration for the talking portrait pipeline.", stage="duration_probe", stdout=result.stdout, stderr=result.stderr, technical_details={"path": str(path)}) from exc

    @classmethod
    def _merge_original_audio(cls, video_path: Path, audio_path: Path, output_path: Path, ffmpeg: str) -> None:
        result = subprocess.run([ffmpeg, "-y", "-i", str(video_path), "-i", str(audio_path), "-map", "0:v:0", "-map", "1:a:0", "-c:v", "copy", "-c:a", "aac", "-af", "aresample=async=1:first_pts=0", str(output_path)], text=True, encoding="utf-8", errors="replace", stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=600, shell=False)
        if result.returncode != 0:
            raise TalkingPortraitProviderError(cls.name, f"Final audio merge failed: {result.stderr}", "The final MP4 could not be muxed with the complete uploaded audio.", stage="merge_original_audio", stdout=result.stdout, stderr=result.stderr, technical_details={"command": result.args})

    @classmethod
    def _validate_final_output(cls, output_path: Path, audio_duration: float, output_duration: float) -> None:
        if not output_path.exists():
            raise TalkingPortraitProviderError(cls.name, "Final talking portrait MP4 is missing", "The final talking portrait MP4 was not created.", stage="validate_output", technical_details={"output_path": str(output_path)})
        if output_path.stat().st_size < 64 * 1024:
            raise TalkingPortraitProviderError(cls.name, f"Final talking portrait MP4 is invalid: {output_path.stat().st_size} bytes", "The final talking portrait MP4 is invalid.", stage="validate_output", technical_details={"output_path": str(output_path), "size_bytes": output_path.stat().st_size})
        tolerance = max(0.35, min(1.0, audio_duration * 0.03))
        if abs(output_duration - audio_duration) > tolerance:
            raise TalkingPortraitProviderError(cls.name, f"Final MP4 duration {output_duration:.3f}s does not match uploaded audio duration {audio_duration:.3f}s", "The final talking portrait duration did not match the complete uploaded audio, so the output was rejected.", stage="validate_av_sync", technical_details={"output_path": str(output_path), "audio_duration_seconds": audio_duration, "output_duration_seconds": output_duration, "tolerance_seconds": tolerance})

    @classmethod
    def _inference_supports_option(cls, root: Path, python: Path, option: str) -> bool:
        try:
            result = subprocess.run([str(python), "inference.py", "--help"], cwd=str(root), text=True, encoding="utf-8", errors="replace", stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=60, shell=False)
            return option in (result.stdout or "") or option in (result.stderr or "")
        except Exception:
            return False


def build_install_commands(root: Path | None = None) -> list[list[str]]:
    target = root or LivePortraitProvider.install_root()
    python = sys.executable
    commands: list[list[str]] = []
    if not target.exists():
        commands.append(["git", "clone", LivePortraitProvider.repository_url, str(target)])
    commands.extend([
        [python, "-m", "venv", str(target / ".venv")],
        [str(target / ".venv" / ("Scripts/python.exe" if os.name == "nt" else "bin/python")), "-m", "pip", "install", "--upgrade", "pip", "setuptools", "wheel"],
        [str(target / ".venv" / ("Scripts/python.exe" if os.name == "nt" else "bin/python")), "-m", "pip", "install", "-r", "requirements.txt"],
    ])
    return commands
