from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .security import resolve_inside


@dataclass(slots=True)
class Repository:
    root: Path

    def __post_init__(self) -> None:
        self.root = self.root.resolve()

    def read_text(self, relative_path: str) -> str:
        return resolve_inside(self.root, relative_path).read_text(encoding="utf-8")

    def write_text(self, relative_path: str, content: str) -> None:
        target = resolve_inside(self.root, relative_path)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")

    def delete(self, relative_path: str) -> None:
        target = resolve_inside(self.root, relative_path)
        if target.is_file():
            target.unlink()

    def exists(self, relative_path: str) -> bool:
        return resolve_inside(self.root, relative_path).exists()
