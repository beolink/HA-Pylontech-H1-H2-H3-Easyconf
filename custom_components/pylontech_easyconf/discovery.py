"""Finding Solarman loggers on the local network.

A Solarman logger answers a UDP datagram on port 48899 with its address, its
MAC address and its serial number, comma-separated. The set-up sends the two
greetings the loggers are known to answer to every broadcast address of the
networks Home Assistant is on, and then asks each logger that answered
whether a Pylontech BMS is behind it (reader.probe), so the owner picks a
battery rather than typing an address and a serial number.

Free of Home Assistant on purpose: the set-up hands in the broadcast
addresses it got from Home Assistant's network integration.
"""

from __future__ import annotations

import asyncio
from collections.abc import Iterable
from dataclasses import dataclass
import ipaddress
import logging
import socket

_LOGGER = logging.getLogger(__name__)

DISCOVERY_PORT = 48899
GREETINGS = (b"WIFIKIT-214028-READ", b"HF-A11ASSISTHREAD")
DEFAULT_TIMEOUT = 2.0


@dataclass(frozen=True)
class FoundLogger:
    ip: str
    mac: str
    serial: int


def parse_reply(data: bytes) -> FoundLogger | None:
    """A logger's answer, or None for anything else on the port."""
    parts = data.decode("ascii", errors="ignore").strip().split(",")
    if len(parts) != 3:
        return None
    ip, mac, serial = (p.strip() for p in parts)
    if not serial.isdigit():
        return None
    try:
        ipaddress.IPv4Address(ip)
    except ValueError:
        return None
    mac = mac.upper()
    if len(mac) == 12:
        mac = ":".join(mac[i:i + 2] for i in range(0, 12, 2))
    return FoundLogger(ip, mac, int(serial))


class _Listener(asyncio.DatagramProtocol):
    def __init__(self) -> None:
        self.found: dict[int, FoundLogger] = {}

    def datagram_received(self, data: bytes, addr) -> None:
        if (logger := parse_reply(data)) is not None:
            self.found.setdefault(logger.serial, logger)

    def error_received(self, exc: Exception) -> None:
        _LOGGER.debug("Logger discovery: %r", exc)


async def scan(targets: Iterable[str], timeout: float = DEFAULT_TIMEOUT,
               port: int = DISCOVERY_PORT) -> list[FoundLogger]:
    """Every logger that answers within ``timeout`` seconds."""
    loop = asyncio.get_running_loop()
    listener = _Listener()
    transport, _ = await loop.create_datagram_endpoint(
        lambda: listener, local_addr=("0.0.0.0", 0), family=socket.AF_INET,
        allow_broadcast=True,
    )
    try:
        for _ in range(2):  # a datagram can get lost; loggers answer twice gladly
            for target in targets:
                for greeting in GREETINGS:
                    try:
                        transport.sendto(greeting, (target, port))
                    except OSError as err:
                        _LOGGER.debug("Logger discovery to %s: %r", target, err)
            await asyncio.sleep(timeout / 2)
    finally:
        transport.close()
    return sorted(listener.found.values(), key=lambda f: ipaddress.IPv4Address(f.ip))


def broadcast_addresses(networks: Iterable[tuple[str, int]]) -> list[str]:
    """The broadcast address of each private IPv4 network (address, prefix)."""
    out: list[str] = []
    for address, prefix in networks:
        try:
            net = ipaddress.IPv4Network(f"{address}/{prefix}", strict=False)
        except ValueError:
            continue
        if net.is_loopback or net.is_link_local or not net.is_private or net.prefixlen >= 31:
            continue
        if (b := str(net.broadcast_address)) not in out:
            out.append(b)
    return out or ["255.255.255.255"]
