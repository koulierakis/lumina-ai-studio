"""Network address discovery for the local LUMINA runtime."""
from __future__ import annotations

import ipaddress
import socket


def active_private_lan_ip() -> str | None:
    """Return this machine's reachable private IPv4 address, or ``None``.

    Uses a UDP socket "connect" (no packets are sent) so the OS picks the
    interface it would route through. Only private, non-loopback IPv4
    addresses are returned, so a public address is never advertised.
    """
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
            sock.connect(("8.8.8.8", 80))
            candidate = sock.getsockname()[0]
        ip = ipaddress.ip_address(candidate)
        if ip.version == 4 and ip.is_private and not ip.is_loopback:
            return candidate
    except OSError:
        return None
    return None
