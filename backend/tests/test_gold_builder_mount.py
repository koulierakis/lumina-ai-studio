"""Lumina mount of Gold Builder: auth guard, credential stripping and preview shim."""
import json

from gold_builder.api.routes import _inject_proxy_shim


def test_proxy_shim_is_injected_after_head_and_targets_job_proxy():
    out = _inject_proxy_shim(b"<html><head><title>x</title></head><body></body></html>", "/api/gb/jobs/abc/proxy").decode()
    assert out.index("<head>") < out.index("<script>") < out.index("<title>")
    assert json.dumps("/api/gb/jobs/abc/proxy") in out


def test_proxy_shim_without_head_is_prepended():
    out = _inject_proxy_shim(b"<div>hi</div>", "/api/gb/jobs/abc/proxy").decode()
    assert out.startswith("<script>") and out.endswith("<div>hi</div>")


def test_gold_builder_guard_rejects_forged_header_and_cookie_and_accepts_issued_cookie(monkeypatch):
    from fastapi import Depends, FastAPI
    from fastapi.testclient import TestClient

    from auth import issue_token
    from gold_builder_mount import PREVIEW_COOKIE, require_gold_builder_access

    monkeypatch.setenv("OWNER_EMAIL", "owner@lumina.local")
    monkeypatch.setenv("JWT_SECRET", "unit-test-secret-not-real")
    monkeypatch.setenv("LUMINA_LOCAL_PASSWORDLESS", "0")
    app = FastAPI()

    @app.get("/api/gb/health")
    async def health(owner: str = Depends(require_gold_builder_access)):
        return {"owner": owner}

    client = TestClient(app)
    assert client.get("/api/gb/health").status_code == 401
    assert client.get("/api/gb/health", headers={"Authorization": "Bearer forged"}).status_code == 401
    assert client.get("/api/gb/health", cookies={PREVIEW_COOKIE: "forged"}).status_code == 401
    good = issue_token("owner@lumina.local", hours=1)
    assert client.get("/api/gb/health", cookies={PREVIEW_COOKIE: good}).json() == {"owner": "owner@lumina.local"}
    assert client.get("/api/gb/health", headers={"Authorization": f"Bearer {good}"}).status_code == 200
