from code_builder.openhands_engine import OpenHandsEngine


class FakeAdapter:
    def is_available(self): return True


class FakeExecutionService:
    adapter = FakeAdapter()


def test_openhands_engine_reports_available_safe_mode():
    status = OpenHandsEngine(FakeExecutionService()).status()
    assert status.name == "openhands" and status.available is True and status.safe_mode is True
    assert status.public_status() == {"name": "openhands", "available": True, "safe_mode": True}
