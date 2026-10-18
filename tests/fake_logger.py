"""A stand-in for the battery's Solarman logger, a Modbus TCP gateway or an
RS485 converter, on a real loopback socket.

It answers holding-register reads from a bank of words the way the real
devices do, including the habits the transports must cope with: a V5 logger
that answers a request with the wrong serial with its own and nothing else,
that sends a heartbeat of its own in the middle of a conversation, that
passes on no answer when the battery behind it is off, and a BMS that answers
illegal data address for a block it does not have.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from pathlib import Path
import struct
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from custom_components.pylontech_easyconf import modbus, solarman_v5


@dataclass
class FakeBattery:
    bank: dict[int, int]
    serial: int = 2712345678
    slave: int = 1
    #: "solarman_v5", "modbus_tcp" or "rtu_over_tcp".
    kind: str = "solarman_v5"
    #: Send a heartbeat frame before the answer to every n-th request.
    heartbeat_every: int = 0
    #: The logger passes on nothing, as when the battery behind it is off.
    battery_off: bool = False
    #: Blocks the BMS does not have: (start, end) inclusive.
    missing: list[tuple[int, int]] = field(default_factory=list)
    #: Never answer at all.
    silent: bool = False
    #: Pass over these requests (1-based, counted over the whole run), as a
    #: logger does when another client asked at the same moment.
    drop: set[int] = field(default_factory=set)
    seen: int = 0
    requests: list[tuple[int, int]] = field(default_factory=list)
    wrong_serial_answers: int = 0

    def registers(self, address: int, count: int) -> list[int] | int:
        """The words asked for, or a Modbus exception code."""
        for start, end in self.missing:
            if address <= end and address + count - 1 >= start:
                return 2
        if any(a not in self.bank for a in range(address, address + count)):
            return 2
        return [self.bank[a] for a in range(address, address + count)]

    # The RTU answer the BMS itself would give.
    def rtu_answer(self, request: bytes) -> bytes:
        slave, function, address, count = struct.unpack(">BBHH", request[:6])
        self.requests.append((address, count))
        result = self.registers(address, count)
        if isinstance(result, int):
            body = bytes([slave, function | 0x80, result])
        else:
            body = bytes([slave, function, 2 * count]) + struct.pack(f">{count}H", *result)
        return body + modbus.crc16(body)


class FakeServer:
    def __init__(self, battery: FakeBattery) -> None:
        self.battery = battery
        self.server: asyncio.base_events.Server | None = None
        self.port = 0
        self.connections = 0
        self._writers: set[asyncio.StreamWriter] = set()

    async def __aenter__(self) -> FakeServer:
        self.server = await asyncio.start_server(self._client, "127.0.0.1", 0)
        self.port = self.server.sockets[0].getsockname()[1]
        return self

    async def __aexit__(self, *exc) -> None:
        await self.close()

    async def close(self) -> None:
        """Stop listening and drop every client, as a logger that reboots does.

        Since Python 3.12 a server waits for its connections to close, and a
        client that keeps its connection open would keep it waiting.
        """
        assert self.server is not None
        self.server.close()
        for writer in list(self._writers):
            writer.close()
        await self.server.wait_closed()

    async def _client(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        self.connections += 1
        self._writers.add(writer)
        handler = {
            "solarman_v5": self._v5,
            "modbus_tcp": self._tcp,
            "rtu_over_tcp": self._rtu,
        }[self.battery.kind]
        try:
            await handler(reader, writer)
        except (asyncio.IncompleteReadError, ConnectionError):
            pass
        finally:
            self._writers.discard(writer)
            writer.close()

    async def _v5(self, reader, writer) -> None:
        battery = self.battery
        buffer = bytearray()
        handled = 0
        while True:
            data = await reader.read(1024)
            if not data:
                return
            buffer.extend(data)
            for frame in solarman_v5.split_frames(buffer):
                if frame.control != solarman_v5.REQUEST:
                    continue  # the client's answer to our heartbeat
                if battery.silent:
                    continue
                battery.seen += 1
                if battery.seen in battery.drop:
                    continue
                handled += 1
                if battery.heartbeat_every and handled % battery.heartbeat_every == 0:
                    writer.write(_heartbeat(battery.serial))
                if frame.serial != battery.serial:
                    battery.wrong_serial_answers += 1
                    writer.write(_v5_answer(battery.serial, frame.raw[5], b""))
                    continue
                request = frame.payload[solarman_v5.REQUEST_PREFIX:]
                answer = b"" if battery.battery_off else battery.rtu_answer(request)
                writer.write(_v5_answer(battery.serial, frame.raw[5], answer))
            await writer.drain()

    async def _tcp(self, reader, writer) -> None:
        battery = self.battery
        while True:
            header = await reader.readexactly(7)
            tid, _proto, length, unit = struct.unpack(">HHHB", header)
            pdu = await reader.readexactly(length - 1)
            if battery.silent:
                continue
            rtu = battery.rtu_answer(bytes([unit]) + pdu + b"\x00\x00")
            body = rtu[1:-2]
            writer.write(struct.pack(">HHHB", tid, 0, len(body) + 1, unit) + body)
            await writer.drain()

    async def _rtu(self, reader, writer) -> None:
        battery = self.battery
        while True:
            request = await reader.readexactly(8)
            if battery.silent:
                continue
            writer.write(battery.rtu_answer(request))
            await writer.drain()


def _v5_answer(serial: int, sequence: int, modbus_frame: bytes) -> bytes:
    payload = b"\x02\x01" + b"\x00" * 12 + modbus_frame
    header = (
        bytes([solarman_v5.START])
        + struct.pack("<HH", len(payload), solarman_v5.RESPONSE)
        + bytes([sequence, 0x7F])
        + struct.pack("<I", serial)
    )
    frame = header + payload
    return frame + bytes([solarman_v5.checksum(frame[1:]), solarman_v5.END])


def _heartbeat(serial: int) -> bytes:
    payload = b"\x00"
    header = (
        bytes([solarman_v5.START])
        + struct.pack("<HH", len(payload), 0x4710)
        + bytes([0x33, 0x00])
        + struct.pack("<I", serial)
    )
    frame = header + payload
    return frame + bytes([solarman_v5.checksum(frame[1:]), solarman_v5.END])
