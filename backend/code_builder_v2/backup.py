from __future__ import annotations

import json
import shutil
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from .security import resolve_inside


@dataclass(slots=True)
class BackupManifest:
    id: str
    files: list[str]


@dataclass(slots=True)
class BackupService:
    repository_root: Path
    backup_root: Path

    def __post_init__(self) -> None:
        self.repository_root = self.repository_root.resolve()
        self.backup_root = self.backup_root.resolve()
        self.backup_root.mkdir(parents=True, exist_ok=True)

    def create(self, paths: list[str]) -> BackupManifest:
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        backup_id = f"{stamp}-{uuid4().hex[:8]}"
        folder = self.backup_root / backup_id
        folder.mkdir(parents=True, exist_ok=False)

        captured: list[str] = []
        for relative in sorted(set(paths)):
            source = resolve_inside(self.repository_root, relative)
            if source.is_file():
                target = folder / "files" / relative
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(source, target)
                captured.append(relative)

        manifest = {"id": backup_id, "files": captured, "requested_paths": sorted(set(paths))}
        (folder / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
        return BackupManifest(id=backup_id, files=captured)

    def restore(self, backup_id: str) -> None:
        folder = (self.backup_root / backup_id).resolve()
        if self.backup_root not in folder.parents:
            raise ValueError("Invalid backup id")
        manifest_path = folder / "manifest.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        requested = manifest.get("requested_paths", [])
        captured = set(manifest.get("files", []))

        for relative in requested:
            target = resolve_inside(self.repository_root, relative)
            backup_file = folder / "files" / relative
            if relative in captured:
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(backup_file, target)
            elif target.is_file():
                target.unlink()
