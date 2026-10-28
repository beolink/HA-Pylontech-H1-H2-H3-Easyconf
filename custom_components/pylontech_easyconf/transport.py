"""The connections to the BMS: Solarman V5, Modbus TCP and RTU over TCP.

Each transport reads holding registers and nothing else. They share the
handling that matters on a battery that also talks to an inverter and a
cloud: one request at a time, a timeout on everything, and a connection that
is dropped and opened again after anything goes wrong, so a logger that
rebooted or a gateway that lost its Wi-Fi is picked up again on the next poll
without leaving half an answer in the stream.

- ``solarman_v5``: the Wi-Fi module of a Force H2 or the Wi-Fi and LAN ports of
  a Force H3, TCP port 8899 (solarman_v5.py).
- ``modbus_tcp``: a logger or a gateway that speaks Modbus TCP, port 502.
- ``rtu_over_tcp``: an RS485-to-Ethernet or RS485-to-Wi-Fi converter in
  transparent mode on the BMS's RS485 port (Elfin EW11, Waveshare and the
  like), which passes Modbus RTU through unchanged.

Free of Home Assistant on purpose, so the tests run without it.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
import logging
import random

from . import modbus, solarman_v5
from .modbus import FrameError

_LOGGER = logging.getLogger(__name__)

SOLARMAN_V5 = "solarman_v5"
MODBUS_TCP = "modbus_tcp"
RTU_OVER_TCP = "rtu_over_tcp"
KINDS = (SOLARMAN_V5, MODBUS_TCP, RTU_OVER_TCP)

DEFAULT_PORTS = {SOLARMAN_V5: 8899, MODBUS_TCP: 502, RTU_OVER_TCP: 8899}

DEFAULT_TIMEOUT = 6.0
CONNECT_TIMEOUT = 6.0

#: How many times a chunk is asked for before the read fails, and the pause
#: before each new attempt, in seconds, grown by the attempt's number and
#: drawn at random so as to step out of another client's run of requests.
ATTEMPTS = 3
RETRY_PAUSE = (0.3, 1.0)


class TransportError(Exception):
    """The battery could not be reached or did not answer in time.

    ``connected`` tells the two apart: False when the address did not take
    the connection at all, True when it did and then gave no usable answer
    (a logger whose battery is off, or a device that speaks something else).
    """

    def __init__(self, message: str, connected: bool = False) -> None:
        super().__init__(message)
        self.connected = connected


class Transport:
    """What every transport offers: a register read and a close."""

    kind = ""

    def __init__(self, host: str, port: int, slave: int = 1,
                 timeout: float = DEFAULT_TIMEOUT, attempts: int = ATTEMPTS) -> None:
        self.host = host
        self.port = port
        self.slave = slave
        self.timeout = timeout
        #: Tries per chunk: ATTEMPTS while polling, 1 when probing an address,
        #: where a device that speaks something else should cost one wait.
        self.attempts = attempts
        self._reader: asyncio.StreamReader | None = None
        self._writer: asyncio.StreamWriter | None = None
        self._lock = asyncio.Lock()
        #: Counters for the diagnostics and the anonymous report.
        self.requests = 0
        self.failures = 0
        self.retries = 0
        self.reconnects = 0
        self.last_error: str | None = None

    @property
    def connected(self) -> bool:
        return self._writer is not None and not self._writer.is_closing()

    async def _connect(self) -> None:
        try:
            async with asyncio.timeout(CONNECT_TIMEOUT):
                self._reader, self._writer = await asyncio.open_connection(self.host, self.port)
        except (OSError, TimeoutError) as err:
            raise TransportError(f"cannot connect to {self.host}:{self.port}: {err!r}") from err
        self.reconnects += 1

    async def close(self) -> None:
        """Close the connection; the next read opens a new one."""
        writer, self._reader, self._writer = self._writer, None, None
        if writer is None:
            return
        try:
            writer.close()
            async with asyncio.timeout(2):
                await writer.wait_closed()
        except (OSError, TimeoutError):
            pass

    async def read_registers(self, address: int, count: int) -> list[int]:
        """Read ``count`` holding registers from ``address``, in chunks.

        A chunk that gets no usable answer is asked for again on a new
        connection, up to ATTEMPTS times, after a short pause, before the read
        fails. A Solarman logger passes one request at a time to the battery,
        and when another client (ha-solarman, the logger's own upload) asks at
        the same moment it drops one of them, or hands one client the other's
        answer. On two houses where ha-solarman polls the same logger every
        five seconds, 2 and 6 % of requests went that way, and an attempt
        straight after a miss failed more often than chance, since the other
        client's run of requests was still going. Any failure closes the
        connection first, so the next attempt starts on a clean stream. Modbus
        exceptions, which the battery sent on purpose, leave it open and are
        not asked again.
        """
        values: list[int] = []
        async with self._lock:
            for start, size in modbus.chunks(address, count):
                values.extend(await self._read_chunk(start, size))
        return values

    async def _read_chunk(self, start: int, size: int) -> list[int]:
        for attempt in range(1, self.attempts + 1):
            if attempt > 1:
                await asyncio.sleep(random.uniform(*RETRY_PAUSE) * (attempt - 1))
            self.requests += 1
            try:
                if not self.connected:
                    await self._connect()
                async with asyncio.timeout(self.timeout):
                    return await self._read(start, size)
            except modbus.ModbusError as err:
                self.last_error = f"{start:#06x}: {err}"
                raise
            except TransportError as err:
                # Nothing took the connection: asking again would only wait
                # out the connect timeout a second time.
                self.failures += 1
                self.last_error = f"{start:#06x}: {err}"
                await self.close()
                raise
            except (OSError, TimeoutError, EOFError, FrameError) as err:
                self.failures += 1
                self.last_error = f"{start:#06x}: {err!r}"
                await self.close()
                if attempt < self.attempts:
                    self.retries += 1
                    continue
                raise TransportError(
                    f"reading {size} registers at {start:#06x} from "
                    f"{self.host}:{self.port}: {err!r}",
                    connected=True,
                ) from err
        raise AssertionError("unreachable")

    async def _read(self, address: int, count: int) -> list[int]:
        raise NotImplementedError

    def _send(self, data: bytes) -> None:
        assert self._writer is not None
        self._writer.write(data)

    async def _drain(self) -> None:
        assert self._writer is not None
        await self._writer.drain()

    async def _recv(self, size: int) -> bytes:
        assert self._reader is not None
        return await self._reader.readexactly(size)

    def describe(self) -> dict:
        """What the diagnostics show about the connection."""
        return {
            "kind": self.kind,
            "slave": self.slave,
            "requests": self.requests,
            "failures": self.failures,
            "retries": self.retries,
            "connections": self.reconnects,
            "last_error": self.last_error,
        }


class SolarmanV5Transport(Transport):
    """Modbus RTU inside Solarman V5 frames, to a Solarman logger."""

    kind = SOLARMAN_V5

    def __init__(self, host: str, port: int = solarman_v5.DEFAULT_PORT, slave: int = 1,
                 serial: int = 0, timeout: float = DEFAULT_TIMEOUT,
                 on_serial: Callable[[int], None] | None = None,
                 attempts: int = ATTEMPTS) -> None:
        super().__init__(host, port, slave, timeout, attempts)
        #: The logger's serial number, 0 until it is known.
        self.serial = serial
        self._on_serial = on_serial
        self._sequence = random.randrange(1, 255)
        self._buffer = bytearray()
        self.unsolicited = 0

    async def _connect(self) -> None:
        self._buffer.clear()
        await super()._connect()

    def _next_sequence(self) -> int:
        self._sequence = (self._sequence + 1) & 0xFF
        return self._sequence

    async def _frame(self) -> solarman_v5.Frame:
        """The next whole frame off the connection."""
        assert self._reader is not None
        while True:
            frames = solarman_v5.split_frames(self._buffer)
            if frames:
                first, rest = frames[0], frames[1:]
                # Put back what came in the same read, in order.
                for frame in reversed(rest):
                    self._buffer[0:0] = frame.raw
                return first
            data = await self._reader.read(1024)
            if not data:
                raise EOFError("the logger closed the connection")
            self._buffer.extend(data)

    async def _exchange(self, request: bytes) -> bytes:
        """Send one Modbus request and return the Modbus answer."""
        for attempt in range(2):
            sequence = self._next_sequence()
            self._send(solarman_v5.build_request(self.serial, sequence, request))
            await self._drain()
            while True:
                frame = await self._frame()
                if frame.control in solarman_v5.UNSOLICITED:
                    self.unsolicited += 1
                    self._send(solarman_v5.build_unsolicited_answer(frame))
                    await self._drain()
                    continue
                if frame.control != solarman_v5.RESPONSE or frame.sequence != sequence:
                    # A late answer to a request that timed out, or noise.
                    continue
                break
            if frame.serial != self.serial and frame.serial:
                # The logger answers a request with the wrong serial with its
                # own, and passes nothing on to the battery. Learn it and ask
                # again, once.
                _LOGGER.debug("Logger at %s has serial %s", self.host, frame.serial)
                self.serial = frame.serial
                if self._on_serial is not None:
                    self._on_serial(frame.serial)
                if attempt == 0:
                    continue
            return solarman_v5.modbus_payload(frame)
        raise FrameError("the logger did not take its own serial number")

    async def _read(self, address: int, count: int) -> list[int]:
        request = modbus.rtu_read_request(self.slave, address, count)
        answer = await self._exchange(request)
        return modbus.parse_rtu_response(answer, self.slave, count)

    def describe(self) -> dict:
        return {**super().describe(), "unsolicited_frames": self.unsolicited}


class ModbusTcpTransport(Transport):
    """Plain Modbus TCP."""

    kind = MODBUS_TCP

    def __init__(self, host: str, port: int = 502, slave: int = 1,
                 timeout: float = DEFAULT_TIMEOUT, attempts: int = ATTEMPTS) -> None:
        super().__init__(host, port, slave, timeout, attempts)
        self._transaction = random.randrange(1, 0xFFFF)

    async def _read(self, address: int, count: int) -> list[int]:
        self._transaction = (self._transaction + 1) & 0xFFFF
        transaction = self._transaction
        self._send(modbus.tcp_read_request(transaction, self.slave, address, count))
        await self._drain()
        while True:
            header = await self._recv(6)
            frame = header + await self._recv(modbus.tcp_frame_length(header) - 6)
            if int.from_bytes(frame[:2], "big") != transaction:
                continue  # a late answer to an earlier request
            return modbus.parse_tcp_response(frame, transaction, self.slave, count)


class RtuOverTcpTransport(Transport):
    """Modbus RTU through a transparent serial-to-network converter."""

    kind = RTU_OVER_TCP

    async def _read(self, address: int, count: int) -> list[int]:
        self._send(modbus.rtu_read_request(self.slave, address, count))
        await self._drain()
        head = await self._recv(3)
        if head[1] & 0x80:
            frame = head + await self._recv(2)
        else:
            frame = head + await self._recv(head[2] + 2)
        return modbus.parse_rtu_response(frame, self.slave, count)


def make_transport(kind: str, host: str, port: int | None = None, slave: int = 1,
                   serial: int = 0, timeout: float = DEFAULT_TIMEOUT,
                   on_serial: Callable[[int], None] | None = None,
                   attempts: int = ATTEMPTS) -> Transport:
    """The transport of the given kind."""
    port = port or DEFAULT_PORTS[kind]
    if kind == SOLARMAN_V5:
        return SolarmanV5Transport(host, port, slave, serial, timeout, on_serial, attempts)
    if kind == MODBUS_TCP:
        return ModbusTcpTransport(host, port, slave, timeout, attempts)
    if kind == RTU_OVER_TCP:
        return RtuOverTcpTransport(host, port, slave, timeout, attempts)
    raise ValueError(f"unknown transport {kind!r}")
