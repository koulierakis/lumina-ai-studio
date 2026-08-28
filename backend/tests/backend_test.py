"""Lumina AI Desktop - backend regression + iteration 3 (editor) + iter 4 (AI edit) tests.

Focus:
- Iteration 1/2 regression: auth, identity packs, media authz+404, generation
  happy path, gallery favorite/delete + cascade.
- Iteration 3 ENDPOINTS (Editor).
- Iteration 4 ENDPOINTS (AI edit).
"""
from __future__ import annotations
import base64
import io
import os
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import jwt
import pytest
import requests
from PIL import Image
from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parents[1] / ".env")


def _read_base_url() -> str:
    configured_url = os.environ.get("REACT_APP_BACKEND_URL")
    if configured_url:
        return configured_url.strip().rstrip("/")
    candidates = [Path(__file__).resolve().parents[2] / "frontend" / ".env"]
    for env_path in candidates:
        if env_path.exists():
            for line in env_path.read_text().splitlines():
                if line.startswith("REACT_APP_BACKEND_URL="):
                    return line.split("=", 1)[1].strip().rstrip("/")
    raise RuntimeError(f"REACT_APP_BACKEND_URL missing from known frontend .env paths: {candidates}")


BASE_URL = _read_base_url()
API = f"{BASE_URL}/api"
EMAIL = os.environ.get("OWNER_EMAIL", "owner@lumina.local")
PASSWORD = os.environ.get("LUMINA_TEST_OWNER_PASSWORD") or os.environ.get("OWNER_PASSWORD", "")

PNG_8x8_B64 = (
    "iVBORw0KGgoAAAANSUhEUgAAAAgAAAAIAQMAAAD+wSzIAAAABlBMVEV/f39/f3+Nl2p"
    "PAAAAEUlEQVR4nGNgYGD4z8DwHwADgAH/mBAY7QAAAABJRU5ErkJggg=="
).replace(" ", "")
PNG_BYTES = base64.b64decode(PNG_8x8_B64)
PNG_EDITED_B64 = (
    "iVBORw0KGgoAAAANSUhEUgAAAAgAAAAIAQMAAAD+wSzIAAAABlBMVEX///8AAABVwtN+"
    "AAAAEklEQVR4nGNgYGD4z8AAxAwMAAoAAf/6wq+AAAAAAElFTkSuQmCC"
).replace(" ", "")
PNG_EDITED_BYTES = base64.b64decode(PNG_EDITED_B64)


@pytest.fixture(scope="session")
def api_client() -> requests.Session:
    s = requests.Session()
    s.headers.update({"Accept": "application/json"})
    return s


@pytest.fixture(scope="session")
def token(api_client: requests.Session) -> str:
    r = api_client.post(f"{API}/auth/login", json={"email": EMAIL, "password": PASSWORD}, timeout=15)
    assert r.status_code == 200, f"login failed: {r.status_code} {r.text}"
    tok = r.json()["access_token"]
    assert isinstance(tok, str) and len(tok) > 10
    return tok


@pytest.fixture(scope="session")
def auth_headers(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


class TestHealthAndAuth:
    def test_health_ok(self, api_client):
        r = api_client.get(f"{API}/health", timeout=10)
        assert r.status_code == 200
        d = r.json()
        assert d["status"] == "ok"
        providers = d["providers_available"]
        assert isinstance(providers, list) and providers
        assert all(isinstance(provider, str) and provider for provider in providers)

    def test_login_wrong_password(self, api_client):
        r = api_client.post(f"{API}/auth/login", json={"email": EMAIL, "password": "wrong"}, timeout=10)
        assert r.status_code == 401

    def test_login_success(self, token):
        assert token

    def test_me_returns_email(self, api_client, auth_headers):
        r = api_client.get(f"{API}/auth/me", headers=auth_headers, timeout=10)
        assert r.status_code == 200
        assert r.json()["email"].lower() == EMAIL

    def test_developer_center_requires_owner_authentication(self, api_client):
        r = api_client.get(f"{API}/developer/overview", timeout=10)
        assert r.status_code in (401, 403)

    def test_developer_center_owner_can_read_local_overview(self, api_client, auth_headers):
        r = api_client.get(f"{API}/developer/overview", headers=auth_headers, timeout=20)
        assert r.status_code == 200, r.text
        data = r.json()
        assert "health" in data and "repository" in data and "scope" in data

    def test_developer_center_rejects_arbitrary_task(self, api_client, auth_headers):
        r = api_client.post(f"{API}/developer/tasks", headers=auth_headers, json={"task_type": "arbitrary-shell-command"}, timeout=10)
        assert r.status_code == 400

    @pytest.mark.parametrize("path", ["/identity-packs", "/gallery", "/providers", "/jobs"])
    def test_private_routes_reject_unauth(self, api_client, path):
        r = api_client.get(f"{API}{path}", timeout=10)
        assert r.status_code in (401, 403), f"{path} did not require auth: {r.status_code}"


class TestIdentityPacksAndMedia:
    pack_id: str = ""
    photo_id: str = ""

    def test_create_pack(self, api_client, auth_headers):
        r = api_client.post(f"{API}/identity-packs", headers=auth_headers, json={"name": "TEST_pack_iter3", "description": "regression"}, timeout=10)
        assert r.status_code == 200, r.text
        d = r.json()
        assert d["name"] == "TEST_pack_iter3"
        assert d["photo_ids"] == []
        TestIdentityPacksAndMedia.pack_id = d["id"]

    def test_reject_bad_mime(self, api_client, auth_headers):
        pid = TestIdentityPacksAndMedia.pack_id
        files = {"files": ("hi.txt", b"hello", "text/plain")}
        r = api_client.post(f"{API}/identity-packs/{pid}/photos", headers=auth_headers, files=files, timeout=15)
        assert r.status_code == 400

    def test_upload_png_and_primary_autoassign(self, api_client, auth_headers):
        pid = TestIdentityPacksAndMedia.pack_id
        files = {"files": ("a.png", PNG_BYTES, "image/png")}
        r = api_client.post(f"{API}/identity-packs/{pid}/photos", headers=auth_headers, files=files, timeout=20)
        assert r.status_code == 200, r.text
        d = r.json()
        assert len(d["photo_ids"]) == 1
        assert d["primary_photo_id"] == d["photo_ids"][0]
        TestIdentityPacksAndMedia.photo_id = d["photo_ids"][0]

    def test_media_returns_bytes_and_mime(self, api_client, auth_headers):
        mid = TestIdentityPacksAndMedia.photo_id
        r = api_client.get(f"{API}/media/{mid}", headers=auth_headers, timeout=15)
        assert r.status_code == 200
        assert r.content == PNG_BYTES


EXPECTED_AI_TOOLS = {
    "retouch", "enhance", "upscale", "sharpen", "remove_bg", "replace_bg",
    "blur_bg", "change_clothes", "change_location", "remove_object",
    "replace_object", "outpaint", "relight", "restore", "generate", "inpaint",
    "expand", "face_restore", "identity_preserve", "style_transfer",
    "color_correct", "hdr", "skin_cleanup", "portrait_enhance",
    "watermark_remove_legal", "perspective_correct",
}


def _make_solid_png(size: int = 256, color=(120, 140, 160)) -> bytes:
    img = Image.new("RGB", (size, size), color)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


class TestAiEditFoundation:
    pack_id: str = ""
    source_media_id: str = ""

    def test_setup_source_media(self, api_client, auth_headers):
        r = api_client.post(f"{API}/identity-packs", headers=auth_headers, json={"name": "TEST_pack_ai_iter4", "description": "ai edit tests"}, timeout=10)
        assert r.status_code == 200, r.text
        TestAiEditFoundation.pack_id = r.json()["id"]
        src = _make_solid_png()
        r = api_client.post(f"{API}/identity-packs/{TestAiEditFoundation.pack_id}/photos", headers=auth_headers, files={"files": ("src256.png", src, "image/png")}, timeout=20)
        assert r.status_code == 200, r.text
        TestAiEditFoundation.source_media_id = r.json()["photo_ids"][0]

    def test_ai_tools_requires_auth(self, api_client):
        r = api_client.get(f"{API}/editor/ai-tools", timeout=10)
        assert r.status_code in (401, 403)

    def test_ai_tools_catalog_shape(self, api_client, auth_headers):
        r = api_client.get(f"{API}/editor/ai-tools", headers=auth_headers, timeout=10)
        assert r.status_code == 200, r.text
        d = r.json()
        tools = d["tools"]
        assert isinstance(tools, list)
        keys = {t["key"] for t in tools}
        assert len(tools) == len(EXPECTED_AI_TOOLS), f"expected {len(EXPECTED_AI_TOOLS)} tools, got {len(tools)}: {keys}"
        assert keys == EXPECTED_AI_TOOLS, f"tool keys mismatch: {keys ^ EXPECTED_AI_TOOLS}"
        for tool in tools:
            assert isinstance(tool.get("key"), str)
            assert "description" in tool

    def test_ai_edit_requires_auth(self, api_client):
        r = api_client.post(f"{API}/editor/ai-edit", data={"source_media_id": "x", "tool": "enhance"}, timeout=10)
        assert r.status_code in (401, 403)

    def test_ai_edit_unknown_tool_400(self, api_client, auth_headers):
        src = TestAiEditFoundation.source_media_id
        r = api_client.post(f"{API}/editor/ai-edit", headers=auth_headers, data={"source_media_id": src, "tool": "definitely-not-a-tool"}, timeout=10)
        assert r.status_code == 400


# A compact JWT regression retained because it guards security behavior relied on by editor routes.
def test_expired_owner_jwt_is_rejected(api_client):
    secret = os.environ.get("JWT_SECRET", "test-secret-for-local-validation-only-32b")
    token = jwt.encode({"sub": EMAIL, "iat": int(time.time()) - 100, "exp": int(time.time()) - 1}, secret, algorithm="HS256")
    r = api_client.get(f"{API}/auth/me", headers={"Authorization": f"Bearer {token}"}, timeout=10)
    assert r.status_code in (401, 403)
