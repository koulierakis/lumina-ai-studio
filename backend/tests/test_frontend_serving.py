from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import server


def client() -> TestClient:
    return TestClient(server.app, base_url="http://localhost")


@pytest.fixture
def frontend_build(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    build_dir = tmp_path / "build"
    build_dir.mkdir()
    (build_dir / "index.html").write_text("<main>LUMINA</main>", encoding="utf-8")
    (build_dir / "asset.js").write_text("window.LUMINA = true;", encoding="utf-8")
    monkeypatch.setattr(server, "FRONTEND_BUILD_DIR", build_dir)
    monkeypatch.setattr(server, "FRONTEND_INDEX", build_dir / "index.html")
    return build_dir


def test_root_serves_frontend(frontend_build: Path) -> None:
    response = client().get("/")
    assert response.status_code == 200
    assert "LUMINA" in response.text


def test_browser_route_falls_back_to_frontend(frontend_build: Path) -> None:
    response = client().get("/studio/voice")
    assert response.status_code == 200
    assert "LUMINA" in response.text


def test_frontend_asset_is_served(frontend_build: Path) -> None:
    response = client().get("/asset.js")
    assert response.status_code == 200
    assert response.text == "window.LUMINA = true;"


def test_unknown_api_route_remains_not_found(frontend_build: Path) -> None:
    response = client().get("/api/does-not-exist")
    assert response.status_code == 404
    assert response.json()["detail"]["message"] == "Not Found"
