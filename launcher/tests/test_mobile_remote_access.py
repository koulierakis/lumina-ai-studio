from launcher.lumina.config import validate_config
from launcher.lumina.services import _probe_host


def test_remote_access_is_off_by_default():
    cfg = validate_config({})
    assert cfg["remote_access"] is False
    assert cfg["backend_host"] == "127.0.0.1"
    assert cfg["frontend_host"] == "localhost"


def test_remote_access_binds_web_services_for_private_network_use():
    cfg = validate_config({"remote_access": True})
    assert cfg["remote_access"] is True
    assert cfg["backend_host"] == "0.0.0.0"
    assert cfg["frontend_host"] == "0.0.0.0"


def test_zero_bind_address_uses_loopback_for_local_health_checks():
    assert _probe_host("0.0.0.0") == "127.0.0.1"
    assert _probe_host("localhost") == "127.0.0.1"
    assert _probe_host("100.64.0.10") == "100.64.0.10"
