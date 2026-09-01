from __future__ import annotations

from pathlib import Path

PATH = Path("backend/code_builder/models.py")


def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count == 0:
        if new in text:
            print(f"{label}: already applied")
            return text
        raise RuntimeError(f"{label}: expected anchor was not found")
    if count != 1:
        raise RuntimeError(f"{label}: expected exactly one anchor, found {count}")
    print(f"{label}: applying")
    return text.replace(old, new, 1)


def main() -> None:
    text = PATH.read_text(encoding="utf-8")

    class_anchor = '''class ProposedFileChange(StrictModel):\n    """One file change proposed by the Code Builder."""\n\n    change_id: UUID = Field(default_factory=uuid4)\n'''
    class_replacement = '''class ProposedFileChange(StrictModel):\n    """One file change proposed by the Code Builder.\n\n    File contents are byte-significant text.  Unlike normal labels and paths,\n    ``old_content`` and ``new_content`` must never be globally stripped because\n    trailing newlines and indentation are part of the proposed patch.\n    """\n\n    model_config = ConfigDict(\n        extra="forbid",\n        validate_assignment=True,\n        str_strip_whitespace=False,\n        use_enum_values=False,\n        populate_by_name=True,\n    )\n\n    change_id: UUID = Field(default_factory=uuid4)\n'''
    text = replace_once(text, class_anchor, class_replacement, "model config")

    validator_anchor = '''    protection_reason: str | None = None\n\n    @model_validator(mode="after")\n    def validate_change_payload(self) -> "ProposedFileChange":\n'''
    validator_replacement = '''    protection_reason: str | None = None\n\n    @field_validator("relative_path", "previous_path")\n    @classmethod\n    def normalize_change_paths(cls, value: str | None) -> str | None:\n        if value is None:\n            return None\n        normalized = value.replace("\\\\", "/").strip()\n        if not normalized:\n            raise ValueError("Change path cannot be empty.")\n        candidate = Path(normalized)\n        if candidate.is_absolute() or any(part == ".." for part in candidate.parts):\n            raise ValueError("Change path must stay inside the repository.")\n        return Path(*candidate.parts).as_posix()\n\n    @field_validator("summary", "reason")\n    @classmethod\n    def normalize_required_labels(cls, value: str) -> str:\n        normalized = value.strip()\n        if not normalized:\n            raise ValueError("Proposal summary and reason cannot be empty.")\n        return normalized\n\n    @field_validator("protection_reason")\n    @classmethod\n    def normalize_optional_label(cls, value: str | None) -> str | None:\n        if value is None:\n            return None\n        normalized = value.strip()\n        return normalized or None\n\n    @field_validator("dependencies")\n    @classmethod\n    def normalize_dependencies(cls, value: list[str]) -> list[str]:\n        return [item.strip() for item in value if item.strip()]\n\n    @model_validator(mode="after")\n    def validate_change_payload(self) -> "ProposedFileChange":\n'''
    text = replace_once(text, validator_anchor, validator_replacement, "field validators")

    PATH.write_text(text, encoding="utf-8")
    print("ProposedFileChange content-preservation migration completed safely.")


if __name__ == "__main__":
    main()
