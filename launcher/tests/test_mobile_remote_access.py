from launcher.lumina import services
from launcher.lumina.config import validate_config
from launcher.lumina.networking import active_private_lan_ip
from launcher.lumina.services import _probe_host, browsable_url, remote_access_url


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


def test_turning_remote_access_off_restores_loopback_hosts():
    cfg = validate_config({"remote_access": False})
    assert cfg["remote_access"] is False
    assert cfg["backend_host"] == "127.0.0.1"
    assert cfg["frontend_host"] == "localhost"


def test_zero_bind_address_uses_loopback_for_local_health_checks():
    assert _probe_host("0.0.0.0") == "127.0.0.1"
    assert _probe_host("localhost") == "127.0.0.1"
    assert _probe_host("100.64.0.10") == "100.64.0.10"


def test_browsable_url_never_advertises_a_bind_address():
    # 0.0.0.0 is a bind address, not something a browser can open.
    assert browsable_url("0.0.0.0", 3000) == "http://127.0.0.1:3000/"
    assert browsable_url("localhost", 3000) == "http://127.0.0.1:3000/"
    assert browsable_url("192.168.1.20", 3000) == "http://192.168.1.20:3000/"


def test_remote_access_url_is_none_when_remote_access_is_off():
    cfg = validate_config({})
    assert remote_access_url(cfg) is None


def test_remote_access_url_uses_the_private_lan_address(monkeypatch):
    monkeypatch.setattr(services, "active_private_lan_ip", lambda: "192.168.1.20")
    cfg = validate_config({"remote_access": True})
    assert remote_access_url(cfg) == "http://192.168.1.20:3000/"


def test_remote_access_url_is_none_without_a_private_address(monkeypatch):
    monkeypatch.setattr(services, "active_private_lan_ip", lambda: None)
    cfg = validate_config({"remote_access": True})
    assert remote_access_url(cfg) is None


def test_active_private_lan_ip_returns_a_private_address_or_none():
    value = active_private_lan_ip()
    assert value is None or value.startswith(("10.", "192.168.", "172."))
