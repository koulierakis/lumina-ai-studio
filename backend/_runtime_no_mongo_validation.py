import base64
import os
import sys
import time
from pathlib import Path

from fastapi.testclient import TestClient

os.environ["OWNER_EMAIL"] = "owner@lumina.local"
os.environ["OWNER_PASSWORD"] = "password"
os.environ["JWT_SECRET"] = "runtime-validation-secret-32-bytes-minimum"
os.environ["IMAGE_PROVIDER"] = "mock"
os.environ["VIDEO_PROVIDER"] = "mock"
os.environ["VOICE_PROVIDER"] = "mock"
os.environ["TALKING_PORTRAIT_PROVIDER"] = "mock"
os.environ.pop("MONGO_URL", None)
os.environ.pop("DB_NAME", None)

sys.path.insert(0, str(Path(__file__).resolve().parent))
from server import app  # noqa: E402

client = TestClient(app, base_url="http://localhost")
login = client.post("/api/auth/login", json={"email": "owner@lumina.local", "password": "password"})
assert login.status_code == 200, login.text
token = login.json()["access_token"]
headers = {"Authorization": f"Bearer {token}"}


def ok(method: str, path: str, **kwargs):
    response = client.request(method, path, headers=headers, **kwargs)
    print(method, path, response.status_code, response.text[:240])
    assert 200 <= response.status_code < 300, response.text
    return response


ok("GET", "/api/talking-portrait/jobs")
ok("GET", "/api/gallery")
pack = ok("POST", "/api/identity-packs", json={"name": "Runtime Pack", "description": "sqlite proof"}).json()
png = base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+/p9sAAAAASUVORK5CYII=")
ok("POST", f"/api/identity-packs/{pack['id']}/photos", files={"files": ("photo.png", png, "image/png")})
wav = (
    b"RIFF" + (36).to_bytes(4, "little") + b"WAVEfmt " + (16).to_bytes(4, "little")
    + (1).to_bytes(2, "little") + (1).to_bytes(2, "little") + (8000).to_bytes(4, "little")
    + (8000).to_bytes(4, "little") + (1).to_bytes(2, "little") + (8).to_bytes(2, "little")
    + b"data" + (0).to_bytes(4, "little")
)
job = ok(
    "POST",
    "/api/talking-portrait/generate",
    data={"provider": "mock", "title": "Runtime proof"},
    files={"photo": ("portrait.png", png, "image/png"), "audio": ("voice.wav", wav, "audio/wav")},
).json()
for _ in range(20):
    response = ok("GET", f"/api/talking-portrait/jobs/{job['id']}")
    status = response.json()["status"]
    if status in {"completed", "failed"}:
        assert status == "completed", response.text
        break
    time.sleep(0.1)
else:
    raise AssertionError("Talking portrait job did not complete")
ok("GET", "/api/talking-portrait/jobs")
ok("GET", "/api/gallery")
print("RUNTIME_VALIDATION_OK")
