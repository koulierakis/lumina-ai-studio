"""Focused Identity Pack reference-photo capacity tests."""
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
os.environ.setdefault("OWNER_EMAIL", "owner@lumina.local")
os.environ.setdefault("JWT_SECRET", "test-secret-for-local-validation-only-32b")
os.environ.setdefault("LUMINA_DATABASE_PROVIDER", "sqlite")
os.environ.setdefault("DB_NAME", "lumina_test_identity_packs")

from auth import issue_token
from server import app


def _client() -> TestClient:
    return TestClient(app, base_url="http://localhost")


def _headers() -> dict[str, str]:
    return {"Authorization": f"Bearer {issue_token('owner@lumina.local')}"}


def _png() -> bytes:
    out = io.BytesIO()
    Image.new("RGB", (48, 32), (120, 80, 40)).save(out, format="PNG")
    return out.getvalue()


def _create(client: TestClient) -> dict:
    response = client.post(
        "/api/identity-packs",
        headers=_headers(),
        json={"name": "Identity capacity verification"},
    )
    assert response.status_code == 200, response.text
    return response.json()


def test_identity_pack_supports_fifteen_references_and_rejects_the_sixteenth():
    client = _client()
    pack = _create(client)
    files = [("files", (f"face-{index}.png", _png(), "image/png")) for index in range(15)]
    uploaded = client.post(
        f"/api/identity-packs/{pack['id']}/photos",
        headers=_headers(),
        files=files,
    )
    assert uploaded.status_code == 200, uploaded.text
    body = uploaded.json()
    assert len(body["photo_ids"]) == 15
    assert body["primary_photo_id"] == body["photo_ids"][0]

    rejected = client.post(
        f"/api/identity-packs/{pack['id']}/photos",
        headers=_headers(),
        files={"files": ("face-16.png", _png(), "image/png")},
    )
    assert rejected.status_code == 400
    assert "15" in rejected.text
    assert len(client.get(f"/api/identity-packs/{pack['id']}", headers=_headers()).json()["photo_ids"]) == 15


def test_identity_pack_rejects_a_batch_that_exceeds_remaining_capacity():
    client = _client()
    pack = _create(client)
    initial = [("files", (f"face-{index}.png", _png(), "image/png")) for index in range(12)]
    uploaded = client.post(
        f"/api/identity-packs/{pack['id']}/photos",
        headers=_headers(),
        files=initial,
    )
    assert uploaded.status_code == 200, uploaded.text

    extra = [("files", (f"extra-{index}.png", _png(), "image/png")) for index in range(4)]
    rejected = client.post(
        f"/api/identity-packs/{pack['id']}/photos",
        headers=_headers(),
        files=extra,
    )
    assert rejected.status_code == 400
    assert "3 more" in rejected.text
    assert len(client.get(f"/api/identity-packs/{pack['id']}", headers=_headers()).json()["photo_ids"]) == 12


def test_existing_identity_packs_with_fewer_than_fifteen_references_remain_compatible():
    client = _client()
    pack = _create(client)
    uploaded = client.post(
        f"/api/identity-packs/{pack['id']}/photos",
        headers=_headers(),
        files={"files": ("legacy-face.png", _png(), "image/png")},
    )
    assert uploaded.status_code == 200
    retrieved = client.get(f"/api/identity-packs/{pack['id']}", headers=_headers())
    assert retrieved.status_code == 200
    assert len(retrieved.json()["photo_ids"]) == 1
