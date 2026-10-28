"""Finding the battery's network module on the local network, two ways.

A Solarman logger, the Wi-Fi module of a Force H2 or H3, answers a UDP
datagram on port 48899 with its address, its MAC address and its serial
number, comma-separated. The set-up sends the two greetings the loggers are
known to answer to every broadcast address of the networks Home Assistant is
on.

A Modbus TCP gateway answers no such greeting: the High-Flying (Elfin) module
on a Force H3 seen in 2026-10 speaks plain Modbus TCP on port 8899 and kept
quiet on 48899. So the set-up also tries a connection to ports 8899 and 502
on every address of those networks (``tcp_scan``), a few seconds for a home
network, and only the addresses that take one are asked anything.

Every module found either way is then asked whether a Pylontech BMS is behind
it (reader.probe), so the owner picks a battery rather than typing an address.

Free of Home Assistant on purpose: the set-up hands in the networks it got
from Home Assistant's network integration.
"""

from __future__ import annotations

import asyncio
from collections.abc import Iterable, Sequence
from contextlib import suppress
from dataclasses import dataclass
import ipaddress
import logging
import socket

_LOGGER = logging.getLogger(__name__)

DISCOVERY_PORT = 48899
GREETINGS = (b"WIFIKIT-214028-READ", b"HF-A11ASSISTHREAD")
DEFAULT_TIMEOUT = 2.0

#: The ports a battery's module answers Modbus on: 8899 (a Solarman logger, or
#: an Elfin gateway's default), 502 (Modbus TCP's own).
SCAN_PORTS = (8899, 502)
#: The largest network that is scanned, in addresses: a /22.
MAX_SCAN_HOSTS = 1022
SCAN_TIMEOUT = 0.6
SCAN_CONCURRENCY = 128


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


def _scannable(address: str, prefix: int):
    try:
        net = ipaddress.IPv4Network(f"{address}/{prefix}", strict=False)
    except ValueError:
        return None
    if net.is_loopback or net.is_link_local or not net.is_private or net.prefixlen >= 31:
        return None
    return net


def scan_hosts(networks: Iterable[tuple[str, int]],
               max_hosts: int = MAX_SCAN_HOSTS) -> list[str]:
    """Every other address of the private networks (address, prefix) given.

    Home Assistant's own addresses are left out, and so is a network larger
    than ``max_hosts`` addresses, where a scan would take too long to be worth
    it and an address is the better way.
    """
    networks = list(networks)
    own = {address for address, _ in networks}
    hosts: list[str] = []
    seen: set[str] = set()
    for address, prefix in networks:
        net = _scannable(address, prefix)
        if net is None or net.num_addresses - 2 > max_hosts:
            continue
        for ip in net.hosts():
            text = str(ip)
            if text not in own and text not in seen:
                seen.add(text)
                hosts.append(text)
    return hosts


async def tcp_scan(hosts: Iterable[str], ports: Sequence[int] = SCAN_PORTS,
                   timeout: float = SCAN_TIMEOUT,
                   concurrency: int = SCAN_CONCURRENCY) -> list[tuple[str, int]]:
    """The (address, port) pairs that take a TCP connection.

    Nothing is sent: the connection is closed as soon as it is made.
    """
    gate = asyncio.Semaphore(concurrency)

    async def one(host: str, port: int) -> tuple[str, int] | None:
        async with gate:
            try:
                async with asyncio.timeout(timeout):
                    _, writer = await asyncio.open_connection(host, port)
            except (OSError, TimeoutError):
                return None
            writer.close()
            with suppress(OSError, TimeoutError):
                async with asyncio.timeout(1):
                    await writer.wait_closed()
            return host, port

    pairs = [(host, port) for host in hosts for port in ports]
    found = await asyncio.gather(*(one(host, port) for host, port in pairs))
    return [pair for pair in found if pair is not None]


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
