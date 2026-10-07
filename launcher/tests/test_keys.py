from pathlib import Path

from launcher.lumina.keys import KEY_CATALOG, apply_keys, env_path, parse_selection, set_keys_interactively


def _seed_example(root: Path) -> None:
    (root / "backend").mkdir(parents=True, exist_ok=True)
    (root / "backend" / ".env.example").write_text(
        "OWNER_EMAIL=owner@lumina.local\nGROQ_API_KEY=\nGEMINI_API_KEY=\n", encoding="utf-8"
    )


def test_env_path_is_under_backend():
    assert env_path(Path("/repo")) == Path("/repo/backend/.env")


def test_parse_selection_accepts_numbers_names_and_all():
    assert parse_selection("1,2") == ["GROQ_API_KEY", "GEMINI_API_KEY"]
    assert parse_selection("groq") == ["GROQ_API_KEY"]
    assert parse_selection("all") == [name for name, _ in KEY_CATALOG]
    assert parse_selection("1,1,2") == ["GROQ_API_KEY", "GEMINI_API_KEY"]
    assert parse_selection("99 nonsense") == []


def test_apply_keys_replaces_existing_and_appends_missing(tmp_path: Path):
    path = tmp_path / ".env"
    path.write_text("A=old\nB=\n# comment\n", encoding="utf-8")
    written = apply_keys(path, {"A": "new", "C": "added"})
    assert written == 2
    content = path.read_text(encoding="utf-8")
    assert "A=new" in content
    assert "C=added" in content
    assert "# comment" in content
    assert "A=old" not in content


def test_interactive_setup_writes_keys_without_printing_them(tmp_path: Path):
    _seed_example(tmp_path)
    printed: list[str] = []
    answers = iter(["1,2"])
    secrets = iter(["gsk_secret_value", "AIza_secret_value"])
    saved = set_keys_interactively(
        tmp_path,
        prompt=lambda _: next(answers),
        secret=lambda _: next(secrets),
        out=printed.append,
    )
    assert saved == {"GROQ_API_KEY": "gsk_secret_value", "GEMINI_API_KEY": "AIza_secret_value"}
    content = (tmp_path / "backend" / ".env").read_text(encoding="utf-8")
    assert "GROQ_API_KEY=gsk_secret_value" in content
    assert "GEMINI_API_KEY=AIza_secret_value" in content
    # The secret values themselves must never be echoed to the console.
    assert all("secret_value" not in line for line in printed)


def test_interactive_setup_cancels_cleanly_on_empty_selection(tmp_path: Path):
    _seed_example(tmp_path)
    printed: list[str] = []
    saved = set_keys_interactively(
        tmp_path, prompt=lambda _: "", secret=lambda _: "", out=printed.append
    )
    assert saved == {}
    # A template .env is created but stays identical to the example on cancel.
    example = (tmp_path / "backend" / ".env.example").read_text(encoding="utf-8")
    assert (tmp_path / "backend" / ".env").read_text(encoding="utf-8") == example
