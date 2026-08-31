from __future__ import annotations

import io
import os
import sys
from pathlib import Path

from fastapi.testclient import TestClient
from PIL import Image

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

os.environ["OWNER_EMAIL"] = "owner@lumina.local"
os.environ["OWNER_PASSWORD"] = "password123"
os.environ["JWT_SECRET"] = "test-secret-for-local-validation-only-32b"
os.environ["MONGO_URL"] = "mongomock://localhost"
os.environ.setdefault("LUMINA_DATABASE_PROVIDER", "sqlite")
os.environ["DB_NAME"] = "lumina_test_editor_upload_pipeline"

from auth import issue_token  # noqa: E402
from server import app  # noqa: E402

API = "/api"


def _client() -> TestClient:
    return TestClient(app, base_url="http://localhost")


def _headers() -> dict:
    return {"Authorization": f"Bearer {issue_token('owner@lumina.local')}"}


def _image_bytes(fmt: str, size: tuple[int, int] = (32, 32)) -> bytes:
    out = io.BytesIO()
    image = Image.new("RGB", size, (128, 96, 64))
    image.save(out, format=fmt)
    return out.getvalue()


def _create_pack(api_client: TestClient, auth_headers: dict) -> str:
    response = api_client.post(
        f"{API}/identity-packs",
        headers=auth_headers,
        json={"name": "TEST_editor_upload_pipeline"},
        timeout=10,
    )
    assert response.status_code == 200, response.text
    return response.json()["id"]


def test_editor_upload_pipeline_accepts_jpeg_png_webp_and_returns_frontend_contract():
    api_client = _client()
    auth_headers = _headers()
    pack_id = _create_pack(api_client, auth_headers)
    cases = [
        ("photo.jpg", _image_bytes("JPEG"), "image/jpeg"),
        ("photo.png", _image_bytes("PNG"), "image/png"),
        ("photo.webp", _image_bytes("WEBP"), "image/webp"),
    ]

    media_ids: list[str] = []
    for name, data, mime in cases:
        response = api_client.post(
            f"{API}/identity-packs/{pack_id}/photos",
            headers=auth_headers,
            files={"files": (name, data, mime)},
            timeout=30,
        )
        assert response.status_code == 200, response.text
        assert response.headers["x-lumina-route-matched"] == "/api/identity-packs/{pack_id}/photos"
        body = response.json()
        assert body["id"] == pack_id
        assert isinstance(body["photo_ids"], list) and body["photo_ids"], body
        media_id = body["photo_ids"][-1]
        media_ids.append(media_id)

        media_response = api_client.get(f"{API}/media/{media_id}", headers=auth_headers, timeout=20)
        assert media_response.status_code == 200, media_response.text
        assert media_response.headers.get("Content-Type", "").startswith(mime)
        assert media_response.content == data

    assert len(set(media_ids)) == 3


def test_identity_pack_creation_uses_sqlite_when_mongodb_is_unavailable():
    api_client = _client()
    auth_headers = {**_headers(), "Origin": "http://localhost:3000"}
    pack_id = _create_pack(api_client, auth_headers)

    get_response = api_client.get(f"{API}/identity-packs/{pack_id}", headers=auth_headers, timeout=10)
    assert get_response.status_code == 200, get_response.text
    body = get_response.json()
    assert body["id"] == pack_id
    assert body["owner_email"] == "owner@lumina.local"

    patch_response = api_client.patch(
        f"{API}/identity-packs/{pack_id}",
        headers=auth_headers,
        json={"description": "temporary editor pack", "photo_ids": []},
        timeout=10,
    )
    assert patch_response.status_code == 200, patch_response.text
    assert patch_response.json()["description"] == "temporary editor pack"


def test_complete_editor_temporary_pack_upload_and_media_open_flow():
    api_client = _client()
    auth_headers = {**_headers(), "Origin": "http://localhost:3000"}
    create_response = api_client.post(
        f"{API}/identity-packs",
        headers=auth_headers,
        json={"name": "AI Image Editor Uploads"},
        timeout=10,
    )
    assert create_response.status_code == 200, create_response.text
    pack_id = create_response.json()["id"]
    image = _image_bytes("PNG", (64, 64))

    upload_response = api_client.post(
        f"{API}/identity-packs/{pack_id}/photos",
        headers=auth_headers,
        files={"files": ("browser-origin.png", image, "image/png")},
        timeout=20,
    )
    assert upload_response.status_code == 200, upload_response.text
    photo_ids = upload_response.json()["photo_ids"]
    assert photo_ids
    media_id = photo_ids[-1]

    media_response = api_client.get(f"{API}/media/{media_id}", headers=auth_headers, timeout=20)
    assert media_response.status_code == 200, media_response.text
    assert media_response.headers.get("content-type", "").startswith("image/png")
    assert media_response.content == image
    assert f"/studio/editor/{media_id}".endswith(media_id)


def test_expired_token_returns_structured_401_json():
    import time

    import jwt

    token = jwt.encode({"sub": "owner@lumina.local", "iat": int(time.time()) - 100, "exp": int(time.time()) - 1}, os.environ["JWT_SECRET"], algorithm="HS256")
    response = _client().post(
        f"{API}/identity-packs",
        headers={"Authorization": f"Bearer {token}", "Origin": "http://localhost:3000"},
        json={"name": "Expired"},
        timeout=10,
    )
    assert response.status_code == 401, response.text
    body = response.json()
    assert body["detail"]["code"] == "http_401"
    assert body["detail"]["message"]


def test_editor_upload_pipeline_accepts_20mb_multipart_image():
    api_client = _client()
    auth_headers = _headers()
    pack_id = _create_pack(api_client, auth_headers)
    payload = b"\xff\xd8\xff\xe0" + (b"0" * (20 * 1024 * 1024 - 6)) + b"\xff\xd9"
    response = api_client.post(
        f"{API}/identity-packs/{pack_id}/photos",
        headers=auth_headers,
        files={"files": ("twenty-mb.jpg", payload, "image/jpeg")},
        timeout=60,
    )
    assert response.status_code == 200, response.text
    media_id = response.json()["photo_ids"][-1]
    media_response = api_client.get(f"{API}/media/{media_id}", headers=auth_headers, timeout=60)
    assert media_response.status_code == 200, media_response.text
    assert media_response.headers.get("Content-Type", "").startswith("image/jpeg")
    assert len(media_response.content) == len(payload)
    assert media_response.content[:4] == b"\xff\xd8\xff\xe0"


def test_editor_upload_pipeline_validation_error_is_not_empty_object():
    api_client = _client()
    auth_headers = _headers()
    pack_id = _create_pack(api_client, auth_headers)
    response = api_client.post(
        f"{API}/identity-packs/{pack_id}/photos",
        headers=auth_headers,
        files={"wrong_field": ("photo.png", _image_bytes("PNG"), "image/png")},
        timeout=20,
    )
    assert response.status_code == 422, response.text
    body = response.json()
    assert body != {}
    assert body["http_status"] == 422
    assert body["message"] == "Request validation failed"
    assert body["detail"]["message"] == "Request validation failed"
    assert body["detail"]["exception_type"] == "RequestValidationError"
    assert body["stack"]
    assert body["technical_details"]["path"] == f"/api/identity-packs/{pack_id}/photos"


def test_upload_transport_preflight_allows_local_browser_origin_and_headers():
    api_client = _client()
    pack_id = "pack-for-preflight"
    response = api_client.options(
        f"{API}/identity-packs/{pack_id}/photos",
        headers={
            "Origin": "http://localhost:3000",
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "authorization,content-type",
        },
        timeout=10,
    )
    assert response.status_code == 200, response.text
    assert response.headers["access-control-allow-origin"] == "http://localhost:3000"
    assert "POST" in response.headers["access-control-allow-methods"]
    assert "authorization" in response.headers["access-control-allow-headers"].lower()
    assert "content-type" in response.headers["access-control-allow-headers"].lower()
