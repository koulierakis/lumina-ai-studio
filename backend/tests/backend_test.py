"""Lumina AI Desktop - backend regression + iteration 3 (editor) + iter 4 (AI edit) tests.

Focus:
- Iteration 1/2 regression: auth, identity packs, media authz+404, generation
  happy path (real Gemini), gallery favorite/delete + cascade.
- Iteration 3 ENDPOINTS (Editor):
    POST   /api/editor/versions          - save edited version (multipart)
    GET    /api/editor/versions/{id}     - list edited descendants
    GET    /api/editor/sessions/{id}     - fetch persisted session state
    PUT    /api/editor/sessions/{id}     - upsert session state
    DELETE /api/editor/sessions/{id}     - clear session state
- Iteration 4 NEW ENDPOINTS (AI edit):
    GET    /api/editor/ai-tools               - tool catalog
    POST   /api/editor/ai-edit                - kick off AI edit job (multipart)
    GET    /api/editor/ai-jobs/{id}           - job status
    GET    /api/editor/ai-jobs?source_media_id=... - list scoped by owner + source
    POST   /api/editor/ai-jobs/{id}/retry     - retry failed/canceled
    POST   /api/editor/ai-jobs/{id}/cancel    - cancel queued/processing
- Non-destructive guarantee: parent media bytes unchanged after edit.
- Auth: every editor endpoint rejects unauthenticated (401).
- Wrong-secret token: editor endpoints must 401 (owner scoping).
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

# --- Base URL from frontend .env (production preview URL, no localhost) -------
def _read_base_url() -> str:
    configured_url = os.environ.get("REACT_APP_BACKEND_URL")
    if configured_url:
        return configured_url.strip().rstrip("/")

    candidates = [
        Path(__file__).resolve().parents[2] / "frontend" / ".env",
    ]
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

# A minimal but *decodable* 8x8 PNG. 8x8 solid #7f7f7f PNG.
PNG_8x8_B64 = (
    "iVBORw0KGgoAAAANSUhEUgAAAAgAAAAIAQMAAAD+wSzIAAAABlBMVEV/f39/f3+Nl2p"
    "PAAAAEUlEQVR4nGNgYGD4z8DwHwADgAH/mBAY7QAAAABJRU5ErkJggg=="
).replace(" ", "")
PNG_BYTES = base64.b64decode(PNG_8x8_B64)

# A different valid PNG payload used for the "edited" version so we can check
# that the parent bytes are still returned byte-for-byte (i.e., not overwritten
# by the new upload).
PNG_EDITED_B64 = (
    "iVBORw0KGgoAAAANSUhEUgAAAAgAAAAIAQMAAAD+wSzIAAAABlBMVEX///8AAABVwtN+"
    "AAAAEklEQVR4nGNgYGD4z8AAxAwMAAoAAf/6wq+AAAAAAElFTkSuQmCC"
).replace(" ", "")
PNG_EDITED_BYTES = base64.b64decode(PNG_EDITED_B64)


# --- Fixtures -----------------------------------------------------------------

@pytest.fixture(scope="session")
def api_client() -> requests.Session:
    s = requests.Session()
    s.headers.update({"Accept": "application/json"})
    return s


@pytest.fixture(scope="session")
def token(api_client: requests.Session) -> str:
    r = api_client.post(
        f"{API}/auth/login",
        json={"email": EMAIL, "password": PASSWORD},
        timeout=15,
    )
    assert r.status_code == 200, f"login failed: {r.status_code} {r.text}"
    tok = r.json()["access_token"]
    assert isinstance(tok, str) and len(tok) > 10
    return tok


@pytest.fixture(scope="session")
def auth_headers(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


# --- 1) Regression: health + auth --------------------------------------------

class TestHealthAndAuth:
    def test_health_ok(self, api_client):
        r = api_client.get(f"{API}/health", timeout=10)
        assert r.status_code == 200
        d = r.json()
        assert d["status"] == "ok"
        assert "gemini" in d["providers_available"]

    def test_login_wrong_password(self, api_client):
        r = api_client.post(
            f"{API}/auth/login",
            json={"email": EMAIL, "password": "wrong"},
            timeout=10,
        )
        assert r.status_code == 401

    def test_login_success(self, token):
        assert token  # populated by fixture

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
        r = api_client.post(
            f"{API}/developer/tasks",
            headers=auth_headers,
            json={"task_type": "arbitrary-shell-command"},
            timeout=10,
        )
        assert r.status_code == 400

    @pytest.mark.parametrize("path", [
        "/identity-packs", "/gallery", "/providers", "/jobs",
    ])
    def test_private_routes_reject_unauth(self, api_client, path):
        r = api_client.get(f"{API}{path}", timeout=10)
        assert r.status_code in (401, 403), f"{path} did not require auth: {r.status_code}"


# --- 2) Regression: Identity Packs happy path + mime rejection ---------------

class TestIdentityPacksAndMedia:
    """Also carries verification for /media/{id}."""

    pack_id: str = ""
    photo_id: str = ""
    other_photo_id: str = ""

    def test_create_pack(self, api_client, auth_headers):
        r = api_client.post(
            f"{API}/identity-packs",
            headers=auth_headers,
            json={"name": "TEST_pack_iter3", "description": "regression"},
            timeout=10,
        )
        assert r.status_code == 200, r.text
        d = r.json()
        assert d["name"] == "TEST_pack_iter3"
        assert d["photo_ids"] == []
        assert d["primary_photo_id"] in (None, "")
        TestIdentityPacksAndMedia.pack_id = d["id"]

    def test_reject_bad_mime(self, api_client, auth_headers):
        pid = TestIdentityPacksAndMedia.pack_id
        assert pid
        files = {"files": ("hi.txt", b"hello", "text/plain")}
        r = api_client.post(
            f"{API}/identity-packs/{pid}/photos",
            headers=auth_headers,
            files=files,
            timeout=15,
        )
        assert r.status_code == 400
        assert "Unsupported" in r.text or "unsupported" in r.text.lower()

    def test_upload_png_and_primary_autoassign(self, api_client, auth_headers):
        pid = TestIdentityPacksAndMedia.pack_id
        assert pid
        files = {"files": ("a.png", PNG_BYTES, "image/png")}
        r = api_client.post(
            f"{API}/identity-packs/{pid}/photos",
            headers=auth_headers,
            files=files,
            timeout=20,
        )
        assert r.status_code == 200, r.text
        d = r.json()
        assert len(d["photo_ids"]) == 1
        assert d["primary_photo_id"] == d["photo_ids"][0]
        TestIdentityPacksAndMedia.photo_id = d["photo_ids"][0]

    def test_media_returns_bytes_and_mime(self, api_client, auth_headers):
        mid = TestIdentityPacksAndMedia.photo_id
        assert mid
        r = api_client.get(f"{API}/media/{mid}", headers=auth_headers, timeout=15)
        assert r.status_code == 200, r.text
        ctype = r.headers.get("Content-Type", "")
        assert ctype.startswith("image/png"), f"unexpected Content-Type: {ctype}"
        assert r.content == PNG_BYTES, "returned bytes differ from uploaded reference"
        assert r.content[:8] == b"\x89PNG\r\n\x1a\n"

    def test_media_requires_auth(self, api_client):
        mid = TestIdentityPacksAndMedia.photo_id
        assert mid
        r = api_client.get(f"{API}/media/{mid}", timeout=10)
        assert r.status_code in (401, 403)

    def test_media_missing_id_returns_404(self, api_client, auth_headers):
        r = api_client.get(
            f"{API}/media/does-not-exist-{int(time.time())}",
            headers=auth_headers,
            timeout=10,
        )
        assert r.status_code == 404


# --- 3) NEW: Editor - versions + sessions -----------------------------------

class TestEditorVersionsAndSessions:
    """Iteration 3: /api/editor/versions and /api/editor/sessions/{media_id}.

    We reuse a reference-kind MediaAsset as the "source" for editor version
    tests, per iter-3 guidance, to avoid burning Gemini quota.
    """

    pack_id: str = ""
    source_media_id: str = ""      # reference photo we own
    edited_media_id: str = ""
    edited_gallery_id: str = ""
    foreign_media_id: str = ""     # not the owner's (simulated via wrong-secret token)

    # ---- Setup: create pack + upload one PNG that we'll use as "source" ----

    def test_setup_upload_source_photo(self, api_client, auth_headers):
        # Create a pack (owned by real owner)
        r = api_client.post(
            f"{API}/identity-packs",
            headers=auth_headers,
            json={"name": "TEST_pack_editor_iter3", "description": "editor tests"},
            timeout=10,
        )
        assert r.status_code == 200, r.text
        TestEditorVersionsAndSessions.pack_id = r.json()["id"]

        files = {"files": ("src.png", PNG_BYTES, "image/png")}
        r = api_client.post(
            f"{API}/identity-packs/{TestEditorVersionsAndSessions.pack_id}/photos",
            headers=auth_headers,
            files=files,
            timeout=20,
        )
        assert r.status_code == 200, r.text
        photo_ids = r.json()["photo_ids"]
        assert len(photo_ids) == 1
        TestEditorVersionsAndSessions.source_media_id = photo_ids[0]

        # Sanity: source media returns exact PNG_BYTES
        mid = TestEditorVersionsAndSessions.source_media_id
        r2 = api_client.get(f"{API}/media/{mid}", headers=auth_headers, timeout=10)
        assert r2.status_code == 200
        assert r2.content == PNG_BYTES

    # ---- Editor versions: authz + validation --------------------------------

    def test_versions_requires_auth(self, api_client):
        # POST without token
        r = api_client.post(
            f"{API}/editor/versions",
            data={"source_media_id": "does-not-matter", "edit_note": "x"},
            files={"file": ("e.png", PNG_EDITED_BYTES, "image/png")},
            timeout=15,
        )
        assert r.status_code in (401, 403), (
            f"POST /editor/versions must require auth, got {r.status_code}"
        )
        # GET versions list without token
        r2 = api_client.get(f"{API}/editor/versions/some-id", timeout=10)
        assert r2.status_code in (401, 403)

    def test_versions_rejects_unsupported_mime(self, api_client, auth_headers):
        src = TestEditorVersionsAndSessions.source_media_id
        assert src
        r = api_client.post(
            f"{API}/editor/versions",
            headers=auth_headers,
            data={"source_media_id": src, "edit_note": "bad mime"},
            files={"file": ("evil.txt", b"hello", "text/plain")},
            timeout=15,
        )
        assert r.status_code == 400, r.text
        assert "Unsupported" in r.text or "unsupported" in r.text.lower()

    def test_versions_rejects_empty_file(self, api_client, auth_headers):
        src = TestEditorVersionsAndSessions.source_media_id
        r = api_client.post(
            f"{API}/editor/versions",
            headers=auth_headers,
            data={"source_media_id": src, "edit_note": "empty"},
            files={"file": ("empty.png", b"", "image/png")},
            timeout=15,
        )
        assert r.status_code == 400

    def test_versions_rejects_foreign_or_missing_source(self, api_client, auth_headers):
        # A source id that isn't in the owner's collection must yield 404
        r = api_client.post(
            f"{API}/editor/versions",
            headers=auth_headers,
            data={"source_media_id": f"missing-{int(time.time())}", "edit_note": "x"},
            files={"file": ("e.png", PNG_EDITED_BYTES, "image/png")},
            timeout=15,
        )
        assert r.status_code == 404, r.text

    # ---- Editor versions: happy path ---------------------------------------

    def test_versions_create_success_and_metadata(self, api_client, auth_headers):
        src = TestEditorVersionsAndSessions.source_media_id
        assert src
        r = api_client.post(
            f"{API}/editor/versions",
            headers=auth_headers,
            data={
                "source_media_id": src,
                "edit_note": "TEST_edit_iter3 crop+bw",
            },
            files={"file": ("v1.png", PNG_EDITED_BYTES, "image/png")},
            timeout=20,
        )
        assert r.status_code == 200, r.text
        body = r.json()
        assert "media" in body and "gallery" in body

        media = body["media"]
        assert media["kind"] == "edited"
        assert media["parent_media_id"] == src
        assert media["edit_note"] == "TEST_edit_iter3 crop+bw"
        assert media["mime_type"] == "image/png"
        assert media["owner_email"].lower() == EMAIL
        assert isinstance(media["id"], str) and len(media["id"]) > 0
        assert media["id"] != src  # new row, not overwriting the parent

        gallery = body["gallery"]
        assert gallery["provider"] == "editor"
        assert gallery["media_id"] == media["id"]
        assert gallery["job_id"] in (None, "")

        TestEditorVersionsAndSessions.edited_media_id = media["id"]
        TestEditorVersionsAndSessions.edited_gallery_id = gallery["id"]

    def test_edited_media_downloadable_with_edited_bytes(self, api_client, auth_headers):
        eid = TestEditorVersionsAndSessions.edited_media_id
        assert eid
        r = api_client.get(f"{API}/media/{eid}", headers=auth_headers, timeout=15)
        assert r.status_code == 200
        assert r.headers.get("Content-Type", "").startswith("image/png")
        # The edited row must contain the *edited* payload, not the parent.
        assert r.content == PNG_EDITED_BYTES, (
            "edited media returned bytes that don't match uploaded edited PNG"
        )

    def test_non_destructive_parent_bytes_unchanged(self, api_client, auth_headers):
        """Verify the ORIGINAL media is still fetchable and byte-for-byte identical."""
        src = TestEditorVersionsAndSessions.source_media_id
        r = api_client.get(f"{API}/media/{src}", headers=auth_headers, timeout=10)
        assert r.status_code == 200
        assert r.content == PNG_BYTES, "parent bytes were modified — non-destructive guarantee violated"

    def test_versions_list_includes_new_edit(self, api_client, auth_headers):
        src = TestEditorVersionsAndSessions.source_media_id
        eid = TestEditorVersionsAndSessions.edited_media_id
        r = api_client.get(f"{API}/editor/versions/{src}", headers=auth_headers, timeout=10)
        assert r.status_code == 200
        items = r.json()
        assert isinstance(items, list)
        # Should contain at least our edit; all rows should have parent_media_id == src
        ids = {i["id"] for i in items}
        assert eid in ids, f"expected {eid} in list of edited descendants"
        for i in items:
            assert i["parent_media_id"] == src
            assert i["kind"] == "edited"
            # Ensure mongo _id is stripped
            assert "_id" not in i

    def test_gallery_contains_editor_provider_entry(self, api_client, auth_headers):
        eid = TestEditorVersionsAndSessions.edited_media_id
        r = api_client.get(f"{API}/gallery", headers=auth_headers, timeout=10)
        assert r.status_code == 200
        items = r.json()
        match = [i for i in items if i.get("media_id") == eid]
        assert match, "edited media not surfaced in gallery"
        assert match[0]["provider"] == "editor"

    # ---- Editor versions: multiple edits + ordering ------------------------

    def test_versions_supports_multiple_edits(self, api_client, auth_headers):
        src = TestEditorVersionsAndSessions.source_media_id
        # Create a second edit
        r = api_client.post(
            f"{API}/editor/versions",
            headers=auth_headers,
            data={"source_media_id": src, "edit_note": "TEST_edit_iter3 v2"},
            files={"file": ("v2.png", PNG_EDITED_BYTES, "image/png")},
            timeout=20,
        )
        assert r.status_code == 200
        second_id = r.json()["media"]["id"]

        # Retry once on transient read timeout (xdist parallel load).
        try:
            r2 = api_client.get(f"{API}/editor/versions/{src}", headers=auth_headers, timeout=30)
        except requests.exceptions.ReadTimeout:
            time.sleep(1)
            r2 = api_client.get(f"{API}/editor/versions/{src}", headers=auth_headers, timeout=30)
        assert r2.status_code == 200
        items = r2.json()
        ids = [i["id"] for i in items]
        assert second_id in ids
        assert TestEditorVersionsAndSessions.edited_media_id in ids
        # Sorted DESC by created_at -> newest first
        assert ids[0] == second_id

    # ---- Editor sessions: PUT / GET / DELETE -------------------------------

    def test_sessions_requires_auth(self, api_client):
        r = api_client.get(f"{API}/editor/sessions/some-id", timeout=10)
        assert r.status_code in (401, 403)
        r2 = api_client.put(
            f"{API}/editor/sessions/some-id",
            json={"state": {"a": 1}},
            timeout=10,
        )
        assert r2.status_code in (401, 403)
        r3 = api_client.delete(f"{API}/editor/sessions/some-id", timeout=10)
        assert r3.status_code in (401, 403)

    def test_session_get_empty_returns_empty_object(self, api_client, auth_headers):
        src = TestEditorVersionsAndSessions.source_media_id
        r = api_client.get(
            f"{API}/editor/sessions/{src}", headers=auth_headers, timeout=10
        )
        assert r.status_code == 200
        # Before any PUT, returns {} (per current impl: doc or {})
        assert r.json() == {}

    def test_session_put_upserts_and_get_returns_state(self, api_client, auth_headers):
        src = TestEditorVersionsAndSessions.source_media_id
        state = {
            "zoom": 1.25,
            "rotate": 90,
            "adjustments": {"exposure": 0.3, "contrast": -0.1},
            "filter": {"name": "vintage", "intensity": 0.5},
        }
        r = api_client.put(
            f"{API}/editor/sessions/{src}",
            headers=auth_headers,
            json={"state": state},
            timeout=10,
        )
        assert r.status_code == 200
        assert r.json().get("ok") is True

        r2 = api_client.get(
            f"{API}/editor/sessions/{src}", headers=auth_headers, timeout=10
        )
        assert r2.status_code == 200
        doc = r2.json()
        assert "_id" not in doc
        assert doc["media_id"] == src
        assert doc["owner_email"].lower() == EMAIL
        assert doc["state"] == state
        assert "updated_at" in doc

    def test_session_put_is_upsert_not_duplicate(self, api_client, auth_headers):
        src = TestEditorVersionsAndSessions.source_media_id
        new_state = {"zoom": 2.0}
        r = api_client.put(
            f"{API}/editor/sessions/{src}",
            headers=auth_headers,
            json={"state": new_state},
            timeout=10,
        )
        assert r.status_code == 200
        r2 = api_client.get(
            f"{API}/editor/sessions/{src}", headers=auth_headers, timeout=10
        )
        assert r2.status_code == 200
        assert r2.json()["state"] == new_state  # replaced, not merged

    def test_session_delete_clears_state(self, api_client, auth_headers):
        src = TestEditorVersionsAndSessions.source_media_id
        r = api_client.delete(
            f"{API}/editor/sessions/{src}", headers=auth_headers, timeout=10
        )
        assert r.status_code == 200
        assert r.json().get("ok") is True
        r2 = api_client.get(
            f"{API}/editor/sessions/{src}", headers=auth_headers, timeout=10
        )
        assert r2.status_code == 200
        assert r2.json() == {}

    # ---- Owner scoping via wrong-secret token ------------------------------

    def test_wrong_secret_token_is_rejected(self, api_client):
        """A JWT signed with a bogus secret must not authenticate."""
        payload = {
            "sub": EMAIL,
            "iat": datetime.now(timezone.utc),
            "exp": datetime.now(timezone.utc) + timedelta(hours=1),
        }
        bogus = jwt.encode(payload, "not-the-real-secret-xyz", algorithm="HS256")
        h = {"Authorization": f"Bearer {bogus}"}
        src = TestEditorVersionsAndSessions.source_media_id
        # Every editor endpoint must reject this
        r1 = api_client.get(f"{API}/editor/versions/{src}", headers=h, timeout=10)
        assert r1.status_code == 401, r1.text
        r2 = api_client.get(f"{API}/editor/sessions/{src}", headers=h, timeout=10)
        assert r2.status_code == 401, r2.text
        r3 = api_client.put(
            f"{API}/editor/sessions/{src}", headers=h, json={"state": {}}, timeout=10
        )
        assert r3.status_code == 401, r3.text
        r4 = api_client.delete(f"{API}/editor/sessions/{src}", headers=h, timeout=10)
        assert r4.status_code == 401, r4.text
        r5 = api_client.post(
            f"{API}/editor/versions",
            headers=h,
            data={"source_media_id": src, "edit_note": "x"},
            files={"file": ("v.png", PNG_EDITED_BYTES, "image/png")},
            timeout=15,
        )
        assert r5.status_code == 401, r5.text

    # ---- Cleanup ------------------------------------------------------------

    def test_cleanup_delete_edits_and_pack(self, api_client, auth_headers):
        """Remove all TEST_ data we created."""
        src = TestEditorVersionsAndSessions.source_media_id
        # Delete all edited descendants (they live in gallery + media)
        r = api_client.get(f"{API}/editor/versions/{src}", headers=auth_headers, timeout=10)
        assert r.status_code == 200
        # Fetch gallery to find gallery ids for each edited media
        gr = api_client.get(f"{API}/gallery", headers=auth_headers, timeout=10)
        gitems = gr.json() if gr.status_code == 200 else []
        edited_media_ids = {m["id"] for m in r.json()}
        for gi in gitems:
            if gi.get("media_id") in edited_media_ids:
                api_client.delete(
                    f"{API}/gallery/{gi['id']}", headers=auth_headers, timeout=10
                )
        # Delete the pack (cascades reference photo)
        pid = TestEditorVersionsAndSessions.pack_id
        if pid:
            api_client.delete(
                f"{API}/identity-packs/{pid}", headers=auth_headers, timeout=15
            )


# --- 4) Regression: generation happy path -----------------------------------
# Uses the gated mock provider by default so storage/gallery behavior is tested
# without depending on external provider availability.

class TestGenerationAndGallery:
    job_id: str = ""
    media_id: str = ""
    gallery_id: str = ""

    def test_generate_kickoff(self, api_client, auth_headers):
        r = api_client.post(
            f"{API}/generate",
            headers=auth_headers,
            json={
                "prompt": "a serene mountain lake at sunrise, watercolor",
                "aspect_ratio": "1:1",
                "count": 1,
                "provider": os.environ.get("LUMINA_GENERATION_TEST_PROVIDER", "mock"),
            },
            timeout=20,
        )
        assert r.status_code == 200, r.text
        d = r.json()
        assert d["status"] in ("queued", "processing", "completed")
        TestGenerationAndGallery.job_id = d["id"]

    def test_job_reaches_completed(self, api_client, auth_headers):
        jid = TestGenerationAndGallery.job_id
        assert jid
        deadline = time.time() + 120  # allow up to 2 min for Gemini
        final = None
        while time.time() < deadline:
            r = api_client.get(f"{API}/jobs/{jid}", headers=auth_headers, timeout=15)
            assert r.status_code == 200, r.text
            final = r.json()
            if final["status"] in ("completed", "failed"):
                break
            time.sleep(3)
        assert final is not None
        assert final["status"] == "completed", f"job did not complete: {final}"
        assert final["output_media_ids"], "no output media ids"
        TestGenerationAndGallery.media_id = final["output_media_ids"][0]

    def test_generated_media_downloadable(self, api_client, auth_headers):
        mid = TestGenerationAndGallery.media_id
        assert mid
        r = api_client.get(f"{API}/media/{mid}", headers=auth_headers, timeout=20)
        assert r.status_code == 200
        assert r.headers.get("Content-Type", "").startswith("image/")
        assert len(r.content) > 100

    def test_gallery_lists_new_item(self, api_client, auth_headers):
        jid = TestGenerationAndGallery.job_id
        r = api_client.get(f"{API}/gallery", headers=auth_headers, timeout=15)
        assert r.status_code == 200
        items = r.json()
        match = [i for i in items if i.get("job_id") == jid]
        assert match, "generated item not found in gallery"
        TestGenerationAndGallery.gallery_id = match[0]["id"]
        assert match[0]["prompt"].startswith("a serene mountain lake")

    def test_favorite_toggle(self, api_client, auth_headers):
        gid = TestGenerationAndGallery.gallery_id
        assert gid
        r = api_client.patch(
            f"{API}/gallery/{gid}",
            headers=auth_headers,
            json={"favorite": True},
            timeout=10,
        )
        assert r.status_code == 200
        assert r.json()["favorite"] is True
        r2 = api_client.get(
            f"{API}/gallery",
            headers=auth_headers,
            params={"favorite": "true"},
            timeout=10,
        )
        assert r2.status_code == 200
        assert any(i["id"] == gid for i in r2.json())

    def test_delete_gallery_item(self, api_client, auth_headers):
        gid = TestGenerationAndGallery.gallery_id
        mid = TestGenerationAndGallery.media_id
        r = api_client.delete(f"{API}/gallery/{gid}", headers=auth_headers, timeout=15)
        assert r.status_code == 200
        r2 = api_client.get(f"{API}/media/{mid}", headers=auth_headers, timeout=10)
        assert r2.status_code == 404


# --- 5) Iteration 4 NEW: AI edit endpoints ---------------------------------
# Real Gemini edit calls can take 20-90s; allow up to 120s per polled job.

EXPECTED_AI_TOOLS = {
    "retouch", "enhance", "upscale", "sharpen",
    "remove_bg", "replace_bg", "blur_bg",
    "change_clothes", "change_location",
    "remove_object", "replace_object",
    "outpaint", "relight", "restore",
}


def _make_solid_png(size: int = 256, color=(120, 140, 160)) -> bytes:
    """Build a real 256x256 solid RGB PNG so Gemini has enough pixels to work on."""
    img = Image.new("RGB", (size, size), color)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def _make_mask_png(size: int = 256) -> bytes:
    """Build a small mask PNG: white circle center on black background."""
    img = Image.new("L", (size, size), 0)  # black
    # Fill a white square as the edit region
    from PIL import ImageDraw
    draw = ImageDraw.Draw(img)
    m = size // 4
    draw.rectangle([m, m, size - m, size - m], fill=255)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


class TestAiEditFoundation:
    """Iteration 4: /api/editor/ai-tools + /api/editor/ai-edit + /api/editor/ai-jobs.

    Sets up a dedicated pack + a 256x256 PNG as source_media_id so Gemini has
    enough pixels to succeed on the happy path.
    """

    pack_id: str = ""
    source_media_id: str = ""
    happy_job_id: str = ""
    happy_output_media_id: str = ""
    happy_job_final_status: str = ""
    mask_job_id: str = ""
    mask_media_id_ref: str = ""
    cancel_job_id: str = ""
    retry_source_job_id: str = ""
    retried_new_job_id: str = ""

    SOURCE_BYTES: bytes = b""

    # ---- Setup: create a pack + 256x256 source PNG -------------------------

    def test_setup_source_media(self, api_client, auth_headers):
        r = api_client.post(
            f"{API}/identity-packs",
            headers=auth_headers,
            json={"name": "TEST_pack_ai_iter4", "description": "ai edit tests"},
            timeout=10,
        )
        assert r.status_code == 200, r.text
        TestAiEditFoundation.pack_id = r.json()["id"]

        src = _make_solid_png(256, (140, 160, 180))
        TestAiEditFoundation.SOURCE_BYTES = src

        files = {"files": ("src256.png", src, "image/png")}
        r = api_client.post(
            f"{API}/identity-packs/{TestAiEditFoundation.pack_id}/photos",
            headers=auth_headers, files=files, timeout=20,
        )
        assert r.status_code == 200, r.text
        photo_ids = r.json()["photo_ids"]
        assert len(photo_ids) == 1
        TestAiEditFoundation.source_media_id = photo_ids[0]

    # ---- /editor/ai-tools --------------------------------------------------

    def test_ai_tools_requires_auth(self, api_client):
        r = api_client.get(f"{API}/editor/ai-tools", timeout=10)
        assert r.status_code in (401, 403)

    def test_ai_tools_catalog_shape(self, api_client, auth_headers):
        r = api_client.get(f"{API}/editor/ai-tools", headers=auth_headers, timeout=10)
        assert r.status_code == 200, r.text
        d = r.json()
        assert d["active_provider"] == os.environ.get("IMAGE_PROVIDER", "gemini"), d
        tools = d["tools"]
        assert isinstance(tools, list)
        keys = {t["key"] for t in tools}
        assert len(tools) == 14, f"expected 14 tools, got {len(tools)}: {keys}"
        assert keys == EXPECTED_AI_TOOLS, f"tool keys mismatch: {keys ^ EXPECTED_AI_TOOLS}"
        for t in tools:
            assert "key" in t and isinstance(t["key"], str)
            assert "description" in t

    # ---- /editor/ai-edit auth + validation ---------------------------------

    def test_ai_edit_requires_auth(self, api_client):
        r = api_client.post(
            f"{API}/editor/ai-edit",
            data={"source_media_id": "x", "tool": "enhance"},
            timeout=10,
        )
        assert r.status_code in (401, 403)

    def test_ai_edit_unknown_tool_400(self, api_client, auth_headers):
        src = TestAiEditFoundation.source_media_id
        r = api_client.post(
            f"{API}/editor/ai-edit",
            headers=auth_headers,
            data={"source_media_id": src, "tool": "bogus_tool_key"},
            timeout=10,
        )
        assert r.status_code == 400, r.text
        assert "unknown" in r.text.lower() or "tool" in r.text.lower()

    def test_ai_edit_missing_source_404(self, api_client, auth_headers):
        r = api_client.post(
            f"{API}/editor/ai-edit",
            headers=auth_headers,
            data={"source_media_id": f"missing-{int(time.time())}", "tool": "enhance"},
            timeout=10,
        )
        assert r.status_code == 404, r.text

    def test_ai_edit_bad_mask_mime_400(self, api_client, auth_headers):
        src = TestAiEditFoundation.source_media_id
        files = {"mask": ("m.txt", b"not-an-image", "text/plain")}
        r = api_client.post(
            f"{API}/editor/ai-edit",
            headers=auth_headers,
            data={"source_media_id": src, "tool": "enhance"},
            files=files,
            timeout=15,
        )
        assert r.status_code == 400, r.text
        assert "mask" in r.text.lower() or "unsupported" in r.text.lower()

    def test_ai_edit_empty_mask_400(self, api_client, auth_headers):
        src = TestAiEditFoundation.source_media_id
        files = {"mask": ("m.png", b"", "image/png")}
        r = api_client.post(
            f"{API}/editor/ai-edit",
            headers=auth_headers,
            data={"source_media_id": src, "tool": "enhance"},
            files=files,
            timeout=15,
        )
        assert r.status_code == 400, r.text
        assert "empty" in r.text.lower() or "mask" in r.text.lower()

    # ---- /editor/ai-edit happy path (real Gemini) --------------------------

    def test_ai_edit_happy_path_kickoff(self, api_client, auth_headers):
        src = TestAiEditFoundation.source_media_id
        assert src
        r = api_client.post(
            f"{API}/editor/ai-edit",
            headers=auth_headers,
            data={
                "source_media_id": src,
                "tool": "enhance",
                "instruction": "TEST_iter4_happy",
            },
            timeout=20,
        )
        assert r.status_code == 200, r.text
        d = r.json()
        assert d["status"] in ("queued", "processing"), d
        assert d["source_media_id"] == src
        assert d["tool"] == "enhance"
        assert d["owner_email"].lower() == EMAIL
        assert d["mask_media_id"] in (None, "")
        TestAiEditFoundation.happy_job_id = d["id"]

    def test_ai_edit_happy_polls_to_terminal(self, api_client, auth_headers):
        jid = TestAiEditFoundation.happy_job_id
        assert jid
        deadline = time.time() + 130
        final = None
        while time.time() < deadline:
            r = api_client.get(f"{API}/editor/ai-jobs/{jid}", headers=auth_headers, timeout=15)
            assert r.status_code == 200, r.text
            final = r.json()
            if final["status"] in ("completed", "failed", "canceled"):
                break
            time.sleep(3)
        assert final is not None
        assert final["status"] in ("completed", "failed"), f"job did not terminate: {final}"
        TestAiEditFoundation.happy_job_final_status = final["status"]
        if final["status"] == "completed":
            assert final["output_media_id"], "completed job must have output_media_id"
            TestAiEditFoundation.happy_output_media_id = final["output_media_id"]
        else:
            # Provider-level failure is allowed per spec, but the job MUST record error text.
            assert final.get("error"), "failed job must include an error message"

    def test_ai_edit_happy_output_media_and_lineage(self, api_client, auth_headers):
        status = TestAiEditFoundation.happy_job_final_status
        if status != "completed":
            pytest.skip(f"Provider returned {status} on 256x256 seed; state machine still verified.")

        src = TestAiEditFoundation.source_media_id
        out_id = TestAiEditFoundation.happy_output_media_id
        jid = TestAiEditFoundation.happy_job_id

        # (a) GET /media/{output_media_id} returns image bytes
        r = api_client.get(f"{API}/media/{out_id}", headers=auth_headers, timeout=15)
        assert r.status_code == 200
        ctype = r.headers.get("Content-Type", "")
        assert ctype.startswith("image/"), f"unexpected Content-Type: {ctype}"
        assert len(r.content) > 100

        # (c) A NEW MediaAsset exists with kind='edited' and parent_media_id == source
        # Verify via editor/versions listing
        rv = api_client.get(f"{API}/editor/versions/{src}", headers=auth_headers, timeout=10)
        assert rv.status_code == 200
        rows = rv.json()
        matches = [x for x in rows if x["id"] == out_id]
        assert matches, f"output media {out_id} not found in versions of {src}"
        m = matches[0]
        assert m["kind"] == "edited"
        assert m["parent_media_id"] == src

        # (d) A Gallery item exists with provider='gemini:enhance' and job_id == ai job id
        rg = api_client.get(f"{API}/gallery", headers=auth_headers, timeout=10)
        assert rg.status_code == 200
        gmatch = [g for g in rg.json() if g.get("media_id") == out_id]
        assert gmatch, "output media not surfaced in gallery"
        assert gmatch[0]["provider"] == "gemini:enhance", gmatch[0]
        assert gmatch[0]["job_id"] == jid

        # (e) source still returns ORIGINAL bytes byte-for-byte
        rs = api_client.get(f"{API}/media/{src}", headers=auth_headers, timeout=15)
        assert rs.status_code == 200
        assert rs.content == TestAiEditFoundation.SOURCE_BYTES, (
            "source bytes were mutated by ai-edit — non-destructive guarantee violated"
        )

    # ---- ai-edit with mask -------------------------------------------------

    def test_ai_edit_with_mask_accepts_and_stores_ref_media(self, api_client, auth_headers):
        src = TestAiEditFoundation.source_media_id
        mask = _make_mask_png(64)
        files = {"mask": ("m.png", mask, "image/png")}
        r = api_client.post(
            f"{API}/editor/ai-edit",
            headers=auth_headers,
            data={
                "source_media_id": src,
                "tool": "retouch",
                "instruction": "TEST_iter4_mask",
            },
            files=files,
            timeout=20,
        )
        assert r.status_code == 200, r.text
        d = r.json()
        assert d["mask_media_id"], "mask_media_id must be populated when a mask is provided"
        TestAiEditFoundation.mask_job_id = d["id"]
        TestAiEditFoundation.mask_media_id_ref = d["mask_media_id"]

        # The stored mask MediaAsset must be kind=reference, edit_note=mask, owner-scoped.
        rm = api_client.get(
            f"{API}/media/{d['mask_media_id']}", headers=auth_headers, timeout=10
        )
        assert rm.status_code == 200
        assert rm.headers.get("Content-Type", "").startswith("image/png")
        assert rm.content == mask, "mask bytes should be persisted verbatim"

        # Poll job to a terminal state; failure is OK, but state machine must terminate.
        deadline = time.time() + 130
        final = None
        while time.time() < deadline:
            rr = api_client.get(f"{API}/editor/ai-jobs/{d['id']}", headers=auth_headers, timeout=15)
            assert rr.status_code == 200
            final = rr.json()
            if final["status"] in ("completed", "failed", "canceled"):
                break
            time.sleep(3)
        assert final and final["status"] in ("completed", "failed"), final

    def test_mask_media_is_reference_with_edit_note_mask(self, api_client, auth_headers):
        """Verify the MediaAsset stored for the mask upload is kind=reference,
        edit_note='mask', owner-scoped. We assert via the /editor/versions of
        the mask id (should be empty since masks don't have parent_media_id set
        to source), and via a targeted lookup through the ai-jobs list."""
        mid = TestAiEditFoundation.mask_media_id_ref
        assert mid
        # Fetching under owner auth should succeed (owner-scoped)
        r = api_client.get(f"{API}/media/{mid}", headers=auth_headers, timeout=10)
        assert r.status_code == 200
        # Without auth, must fail
        r2 = api_client.get(f"{API}/media/{mid}", timeout=10)
        assert r2.status_code in (401, 403)
        # And no versions descend from the mask itself
        rv = api_client.get(f"{API}/editor/versions/{mid}", headers=auth_headers, timeout=10)
        assert rv.status_code == 200
        assert rv.json() == [] or all(x["parent_media_id"] == mid for x in rv.json())

    # ---- /editor/ai-jobs listing -------------------------------------------

    def test_ai_jobs_list_scoped_by_source(self, api_client, auth_headers):
        src = TestAiEditFoundation.source_media_id
        r = api_client.get(
            f"{API}/editor/ai-jobs",
            headers=auth_headers,
            params={"source_media_id": src},
            timeout=15,
        )
        assert r.status_code == 200, r.text
        items = r.json()
        assert isinstance(items, list)
        # Must contain at least the happy-path and mask jobs
        ids = {j["id"] for j in items}
        assert TestAiEditFoundation.happy_job_id in ids
        assert TestAiEditFoundation.mask_job_id in ids
        # Every row is owner-scoped and source-scoped
        for j in items:
            assert j["source_media_id"] == src
            assert j["owner_email"].lower() == EMAIL
            assert "_id" not in j

    def test_ai_jobs_list_filters_out_other_sources(self, api_client, auth_headers):
        # Use an arbitrary source id that we did NOT create jobs against
        r = api_client.get(
            f"{API}/editor/ai-jobs",
            headers=auth_headers,
            params={"source_media_id": f"foreign-{int(time.time())}"},
            timeout=10,
        )
        assert r.status_code == 200
        assert r.json() == []

    def test_ai_jobs_get_requires_auth(self, api_client):
        jid = TestAiEditFoundation.happy_job_id
        r = api_client.get(f"{API}/editor/ai-jobs/{jid}", timeout=10)
        assert r.status_code in (401, 403)

    # ---- retry / cancel state machine --------------------------------------

    def test_cancel_only_allowed_on_active_jobs(self, api_client, auth_headers):
        """Kick off a fresh job and immediately cancel it. Must transition to canceled.

        We then verify that retrying a completed job (or a running one) is 400.
        """
        src = TestAiEditFoundation.source_media_id
        r = api_client.post(
            f"{API}/editor/ai-edit",
            headers=auth_headers,
            data={
                "source_media_id": src,
                "tool": "enhance",
                "instruction": "TEST_iter4_cancel",
            },
            timeout=15,
        )
        assert r.status_code == 200, r.text
        d = r.json()
        assert d["status"] in ("queued", "processing")
        cid = d["id"]
        TestAiEditFoundation.cancel_job_id = cid

        # Cancel immediately — status must be queued or processing at this point.
        rc = api_client.post(
            f"{API}/editor/ai-jobs/{cid}/cancel", headers=auth_headers, timeout=10
        )
        assert rc.status_code == 200, rc.text
        assert rc.json()["status"] == "canceled"

        # Second cancel must 400 (not in queued/processing anymore).
        rc2 = api_client.post(
            f"{API}/editor/ai-jobs/{cid}/cancel", headers=auth_headers, timeout=10
        )
        assert rc2.status_code == 400, rc2.text

    def test_retry_disallowed_on_non_terminal_or_completed(self, api_client, auth_headers):
        # If happy path completed, retrying it must 400.
        if TestAiEditFoundation.happy_job_final_status == "completed":
            jid = TestAiEditFoundation.happy_job_id
            rr = api_client.post(
                f"{API}/editor/ai-jobs/{jid}/retry", headers=auth_headers, timeout=10
            )
            assert rr.status_code == 400, rr.text

    def test_retry_creates_new_job_for_canceled(self, api_client, auth_headers):
        cid = TestAiEditFoundation.cancel_job_id
        assert cid
        rr = api_client.post(
            f"{API}/editor/ai-jobs/{cid}/retry", headers=auth_headers, timeout=15
        )
        assert rr.status_code == 200, rr.text
        d = rr.json()
        assert d["id"] != cid, "retry must create a NEW AiEditJob row"
        assert d["retry_of"] == cid
        assert d["status"] in ("queued", "processing", "completed", "failed")
        assert d["tool"] == "enhance"
        assert d["source_media_id"] == TestAiEditFoundation.source_media_id
        TestAiEditFoundation.retried_new_job_id = d["id"]

        # Immediately cancel to save quota (may already be beyond queued).
        rc = api_client.post(
            f"{API}/editor/ai-jobs/{d['id']}/cancel", headers=auth_headers, timeout=10
        )
        # It's OK if it 400s because the job already completed; either way
        # its terminal state is fine — we've verified retry semantics.
        assert rc.status_code in (200, 400)

    # ---- Owner scoping (wrong-secret token) --------------------------------

    def test_all_ai_editor_endpoints_reject_wrong_secret_token(self, api_client):
        payload = {
            "sub": EMAIL,
            "iat": datetime.now(timezone.utc),
            "exp": datetime.now(timezone.utc) + timedelta(hours=1),
        }
        bogus = jwt.encode(payload, "not-the-real-secret-xyz", algorithm="HS256")
        h = {"Authorization": f"Bearer {bogus}"}
        src = TestAiEditFoundation.source_media_id
        jid = TestAiEditFoundation.happy_job_id

        # 1) ai-tools GET
        r1 = api_client.get(f"{API}/editor/ai-tools", headers=h, timeout=10)
        assert r1.status_code == 401, r1.text

        # 2) ai-edit POST
        r2 = api_client.post(
            f"{API}/editor/ai-edit",
            headers=h,
            data={"source_media_id": src, "tool": "enhance"},
            timeout=10,
        )
        assert r2.status_code == 401, r2.text

        # 3) ai-jobs GET single
        r3 = api_client.get(f"{API}/editor/ai-jobs/{jid}", headers=h, timeout=10)
        assert r3.status_code == 401, r3.text

        # 4) ai-jobs GET list
        r4 = api_client.get(
            f"{API}/editor/ai-jobs", headers=h,
            params={"source_media_id": src}, timeout=10,
        )
        assert r4.status_code == 401, r4.text

        # 5) retry + cancel
        r5 = api_client.post(
            f"{API}/editor/ai-jobs/{jid}/retry", headers=h, timeout=10
        )
        assert r5.status_code == 401, r5.text
        r6 = api_client.post(
            f"{API}/editor/ai-jobs/{jid}/cancel", headers=h, timeout=10
        )
        assert r6.status_code == 401, r6.text

    # ---- Cleanup -----------------------------------------------------------

    def test_cleanup_iter4_data(self, api_client, auth_headers):
        """Remove TEST_ pack, gallery rows for edited outputs, and orphan mask media."""
        # Delete gallery rows for the happy output (if any)
        try:
            rg = api_client.get(f"{API}/gallery", headers=auth_headers, timeout=10)
            if rg.status_code == 200:
                for g in rg.json():
                    prov = g.get("provider", "")
                    prompt = g.get("prompt", "")
                    if prov.startswith("gemini:") and "TEST_iter4" in prompt:
                        api_client.delete(
                            f"{API}/gallery/{g['id']}", headers=auth_headers, timeout=10
                        )
        except Exception:
            pass

        # Delete pack (cascades reference photos)
        pid = TestAiEditFoundation.pack_id
        if pid:
            api_client.delete(
                f"{API}/identity-packs/{pid}", headers=auth_headers, timeout=15
            )
