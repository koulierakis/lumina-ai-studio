from code_builder import engine_http_routes


class FakeRegistry:
    def public_status(self):
        return {
            "default": "native",
            "engines": [
                {"name": "native", "available": True, "experimental": False, "safe_mode": True},
                {"name": "openhands", "available": False, "experimental": True, "safe_mode": True},
            ],
            "native_preserved": True,
            "approval_required_for_openhands": True,
            "openhands_runtime_validated": False,
            "openhands_ready": False,
        }


def test_engine_status_is_native_default_and_never_claims_openhands_apply_ready(monkeypatch):
    monkeypatch.setattr(engine_http_routes, "CodingEngineRegistry", FakeRegistry)
    payload = engine_http_routes.get_code_builder_engines()
    assert payload["default"] == "native"
    assert payload["native_preserved"] is True
    assert payload["approval_required_for_openhands"] is True
    assert payload["openhands_runtime_validated"] is False
    assert payload["openhands_ready"] is False
    assert payload["openhands_apply_enabled"] is False
