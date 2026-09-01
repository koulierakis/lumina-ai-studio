import pytest

from code_builder.engine_registry import CodingEngineRegistry
from code_builder.openhands_engine import OpenHandsEngine


class FakeAdapter:
    def __init__(self, available):
        self.available = available

    def is_available(self):
        return self.available


class FakeExecutionService:
    def __init__(self, available):
        self.adapter = FakeAdapter(available)


def registry(available):
    return CodingEngineRegistry(OpenHandsEngine(FakeExecutionService(available)))


def test_registry_always_keeps_native_engine():
    options = registry(False).options()
    assert options[0].name == "native"
    assert options[0].available is True


def test_registry_defaults_missing_selection_to_native():
    assert registry(False).validate_selection(None) == "native"


def test_registry_reports_openhands_availability():
    options = registry(True).options()
    assert options[1].name == "openhands"
    assert options[1].available is True
    assert options[1].experimental is True


def test_registry_public_status_is_ui_ready():
    payload = registry(True).public_status()
    assert payload["default"] == "native"
    assert payload["engines"][0] == {"name": "native", "available": True, "experimental": False}
    assert payload["engines"][1] == {"name": "openhands", "available": True, "experimental": True}


def test_registry_rejects_unavailable_openhands():
    with pytest.raises(RuntimeError):
        registry(False).validate_selection("openhands")
