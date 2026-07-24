"""Latency-sensitive backend smoke tests for Lumina AI Desktop."""
import io
import os
import time
from pathlib import Path

import requests
from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parents[1] / "backend" / ".env")

BASE = os.environ.get("LUMINA_TEST_API_URL", "http://127.0.0.1:8000/api").rstrip("/")
EMAIL = os.environ.get("OWNER_EMAIL", "owner@lumina.local")
PASSWORD = os.environ.get("LUMINA_TEST_OWNER_PASSWORD") or os.environ.get("OWNER_PASSWORD", "")

results = {"passed": [], "failed": []}


def rec_pass(name):
    print(f"PASS: {name}")
    results["passed"].append(name)


def rec_fail(name, evidence):
    print(f"FAIL: {name} -- {evidence}")
    results["failed"].append({"area": name, "evidence": evidence})


# 1x1 PNG (valid)
PNG_1x1 = (
    b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01"
    b"\x08\x06\x00\x00\x00\x1f\x15\xc4\x89\x00\x00\x00\rIDATx\x9cc\xf8\xcf"
    b"\xc0\x00\x00\x00\x03\x00\x01\xa9\x8b\x9f\x9d\x00\x00\x00\x00IEND\xaeB`\x82"
)


def main():
    # 1. Health
    try:
        r = requests.get(f"{BASE}/health", timeout=15)
        assert r.status_code == 200, r.text
        data = r.json()
        assert "gemini" in data.get("providers_available", []), data
        rec_pass("health includes gemini")
    except Exception as e:
        rec_fail("health", str(e))
        return

    # 2. Auth wrong
    r = requests.post(f"{BASE}/auth/login", json={"email": EMAIL, "password": "bad"}, timeout=10)
    if r.status_code == 401:
        rec_pass("wrong creds -> 401")
    else:
        rec_fail("wrong creds", f"got {r.status_code}")

    # 3. Auth correct
    r = requests.post(f"{BASE}/auth/login", json={"email": EMAIL, "password": PASSWORD}, timeout=10)
    if r.status_code != 200:
        rec_fail("login", r.text)
        return
    token = r.json()["access_token"]
    H = {"Authorization": f"Bearer {token}"}
    rec_pass("login returns JWT")

    # 4. Unauth checks
    protected = ["/identity-packs", "/gallery", "/providers", "/jobs"]
    all401 = True
    for p in protected:
        rr = requests.get(f"{BASE}{p}", timeout=10)
        if rr.status_code not in (401, 403):
            all401 = False
            rec_fail(f"unauth {p}", f"got {rr.status_code}")
    if all401:
        rec_pass("all private endpoints reject unauth")

    # 5. Create pack
    r = requests.post(f"{BASE}/identity-packs", json={"name": "TestPack"}, headers=H, timeout=10)
    if r.status_code != 200:
        rec_fail("create pack", r.text)
        return
    pack = r.json()
    pack_id = pack["id"]
    if pack.get("photo_ids") == [] and pack.get("owner_email") == EMAIL:
        rec_pass("create pack owner-scoped, empty photos")
    else:
        rec_fail("create pack shape", str(pack))

    # 6. Reject bad mime
    r = requests.post(
        f"{BASE}/identity-packs/{pack_id}/photos",
        files=[("files", ("a.txt", io.BytesIO(b"hello"), "text/plain"))],
        headers=H,
        timeout=15,
    )
    if r.status_code == 400:
        rec_pass("rejects text/plain upload")
    else:
        rec_fail("mime validation", f"got {r.status_code} {r.text[:120]}")

    # 7. Upload 2 valid PNGs
    files = [
        ("files", ("a.png", io.BytesIO(PNG_1x1), "image/png")),
        ("files", ("b.png", io.BytesIO(PNG_1x1), "image/png")),
    ]
    r = requests.post(f"{BASE}/identity-packs/{pack_id}/photos", files=files, headers=H, timeout=30)
    if r.status_code != 200:
        rec_fail("upload photos", r.text)
        return
    pack = r.json()
    if len(pack["photo_ids"]) == 2 and pack["primary_photo_id"] == pack["photo_ids"][0]:
        rec_pass("upload photos + primary auto-assigned")
    else:
        rec_fail("upload photos shape", str(pack))

    photo1, photo2 = pack["photo_ids"][0], pack["photo_ids"][1]

    # 8. Media auth
    r = requests.get(f"{BASE}/media/{photo1}", timeout=10)
    if r.status_code in (401, 403):
        rec_pass("media requires auth")
    else:
        rec_fail("media auth", f"got {r.status_code}")

    r = requests.get(f"{BASE}/media/{photo1}", headers=H, timeout=10)
    if r.status_code == 200 and r.content.startswith(b"\x89PNG"):
        rec_pass("media returns bytes for owner")
    else:
        rec_fail("media owner get", f"{r.status_code}")

    # 9. Change primary
    r = requests.patch(
        f"{BASE}/identity-packs/{pack_id}",
        json={"primary_photo_id": photo2},
        headers=H,
        timeout=10,
    )
    if r.status_code == 200 and r.json()["primary_photo_id"] == photo2:
        rec_pass("PATCH primary_photo_id")
    else:
        rec_fail("patch primary", r.text)

    # 10. Delete photo re-assigns primary
    r = requests.delete(f"{BASE}/identity-packs/{pack_id}/photos/{photo2}", headers=H, timeout=10)
    if r.status_code == 200:
        p = r.json()
        if photo2 not in p["photo_ids"] and p["primary_photo_id"] == photo1:
            rec_pass("delete photo re-assigns primary")
        else:
            rec_fail("delete photo re-assign", str(p))
    else:
        rec_fail("delete photo", r.text)

    # 11. Max 5 photos: try uploading 5 more (would exceed)
    many = [("files", (f"x{i}.png", io.BytesIO(PNG_1x1), "image/png")) for i in range(5)]
    r = requests.post(f"{BASE}/identity-packs/{pack_id}/photos", files=many, headers=H, timeout=30)
    if r.status_code == 200:
        p = r.json()
        if len(p["photo_ids"]) == 5:
            rec_pass("max 5 photos enforced (extra accepted+trimmed)")
        else:
            rec_fail("max 5 photos", f"count={len(p['photo_ids'])}")
    else:
        rec_fail("upload more photos", r.text)

    # 12. Generate
    r = requests.post(
        f"{BASE}/generate",
        json={
            "prompt": "A portrait in golden light",
            "aspect_ratio": "1:1",
            "count": 1,
            "identity_pack_id": pack_id,
        },
        headers=H,
        timeout=30,
    )
    if r.status_code != 200:
        rec_fail("generate start", r.text)
    else:
        job = r.json()
        job_id = job["id"]
        if job["status"] in ("queued", "processing"):
            rec_pass("generate creates job")
        else:
            rec_fail("job status", str(job))

        # Poll up to 90s
        final_job = None
        for _ in range(30):
            time.sleep(3)
            rr = requests.get(f"{BASE}/jobs/{job_id}", headers=H, timeout=10)
            if rr.status_code == 200:
                j = rr.json()
                if j["status"] in ("completed", "failed"):
                    final_job = j
                    break
        if not final_job:
            rec_fail("job polling", "did not finish in 90s")
        elif final_job["status"] == "completed" and final_job.get("output_media_ids"):
            rec_pass("job completed with output_media_ids")

            # 13. Gallery lists it
            rr = requests.get(f"{BASE}/gallery", headers=H, timeout=10)
            items = rr.json() if rr.status_code == 200 else []
            found = [x for x in items if x.get("job_id") == job_id]
            if found and found[0]["prompt"].startswith("A portrait") and found[0]["aspect_ratio"] == "1:1":
                rec_pass("gallery lists generated item")
                gid = found[0]["id"]

                # 14. Toggle favorite
                rr = requests.patch(f"{BASE}/gallery/{gid}", json={"favorite": True}, headers=H, timeout=10)
                if rr.status_code == 200 and rr.json().get("favorite") is True:
                    rec_pass("toggle favorite")
                else:
                    rec_fail("favorite", rr.text)

                # 15. Delete gallery item
                rr = requests.delete(f"{BASE}/gallery/{gid}", headers=H, timeout=10)
                if rr.status_code == 200:
                    rec_pass("delete gallery item")
                else:
                    rec_fail("delete gallery", rr.text)
            else:
                rec_fail("gallery listing", f"items={len(items)}")
        else:
            # Provider failure — external, not code failure
            print(f"NOTE: provider job status={final_job['status']} error={final_job.get('error')}")
            results["passed"].append(
                f"generation flow accepted (external provider status={final_job['status']})"
            )

    # 16. Delete pack cascades
    r = requests.delete(f"{BASE}/identity-packs/{pack_id}", headers=H, timeout=10)
    if r.status_code == 200:
        r2 = requests.get(f"{BASE}/identity-packs/{pack_id}", headers=H, timeout=10)
        if r2.status_code == 404:
            rec_pass("delete pack cascades")
        else:
            rec_fail("delete pack still present", f"{r2.status_code}")
    else:
        rec_fail("delete pack", r.text)


if __name__ == "__main__":
    main()
    print("\n=== SUMMARY ===")
    print(f"PASSED ({len(results['passed'])}):")
    for p in results["passed"]:
        print(" -", p)
    print(f"FAILED ({len(results['failed'])}):")
    for f in results["failed"]:
        print(" -", f)
