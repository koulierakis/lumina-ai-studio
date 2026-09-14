import requests


BASE_URL = "http://127.0.0.1:8000/api"


def _headers():
    response = requests.post(
        f"{BASE_URL}/auth/login",
        json={"email": "owner@lumina.local", "password": "password123"},
        timeout=10,
    )
    response.raise_for_status()
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


def test_personal_voice_sample_is_saved_and_reused_by_the_model():
    headers = _headers()
    saved = requests.post(
        f"{BASE_URL}/voice/personal-model/sample",
        headers=headers,
        data={"name": "Voice Giannis"},
        files={"audio": ("voice.webm", b"voice" * 128, "audio/webm;codecs=opus")},
        timeout=10,
    )
    assert saved.status_code == 200, saved.text
    payload = saved.json()
    assert payload["name"] == "Voice Giannis"
    assert payload["reference_media_id"]

    loaded = requests.get(f"{BASE_URL}/voice/personal-model", headers=headers, timeout=10)
    assert loaded.status_code == 200
    assert loaded.json()["reference_media_id"] == payload["reference_media_id"]
