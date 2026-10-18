"""Modbus framing for reading the BMS's holding registers.

Free of Home Assistant on purpose, so the tests run without it. Only what
this integration needs is here: function 3 (read holding registers), in the
two framings a Pylontech Force BMS is reached through. Modbus RTU is what the
BMS itself speaks on its RS485 port and what the Solarman logger in its Wi-Fi
or LAN module passes on inside a Solarman V5 frame; Modbus TCP is what a
gateway or a logger with Modbus TCP switched on answers on port 502.

The BMS is only ever read. No function that writes is built here, so nothing
in the integration can change a setting on the battery.
"""

from __future__ import annotations

import struct

READ_HOLDING_REGISTERS = 0x03

#: The largest read one request may ask for. Modbus allows 125 registers; the
#: Solarman loggers in front of a Force BMS have been seen answering 64 at
#: once, and 32 is what the published pollers use, so 32 it is: a few more
#: requests per poll in exchange for never meeting a logger's own limit.
MAX_READ = 32

#: Modbus exception codes, by number, for the messages in the log.
EXCEPTION_NAMES = {
    1: "illegal function",
    2: "illegal data address",
    3: "illegal data value",
    4: "server device failure",
    5: "acknowledge",
    6: "server device busy",
    10: "gateway path unavailable",
    11: "gateway target device failed to respond",
}


class FrameError(Exception):
    """A frame that is cut short, garbled or not the answer to the request."""


class ModbusError(Exception):
    """The device answered the request with a Modbus exception."""

    def __init__(self, code: int) -> None:
        self.code = code
        name = EXCEPTION_NAMES.get(code, "unknown exception")
        super().__init__(f"Modbus exception {code} ({name})")


class IllegalDataAddress(ModbusError):
    """Exception 2: the register block does not exist on this device."""

    def __init__(self, code: int = 2) -> None:
        super().__init__(code)


def exception_for(code: int) -> ModbusError:
    """The exception class that matches a Modbus exception code."""
    if code == 2:
        return IllegalDataAddress()
    return ModbusError(code)


def crc16(data: bytes) -> bytes:
    """Modbus RTU CRC-16 (polynomial 0xA001), low byte first as on the wire."""
    crc = 0xFFFF
    for byte in data:
        crc ^= byte
        for _ in range(8):
            if crc & 1:
                crc = (crc >> 1) ^ 0xA001
            else:
                crc >>= 1
    return struct.pack("<H", crc)


def _check_read(address: int, count: int) -> None:
    if not 0 <= address <= 0xFFFF:
        raise ValueError(f"register address {address} outside 0-65535")
    if not 1 <= count <= 125:
        raise ValueError(f"register count {count} outside 1-125")


def rtu_read_request(slave: int, address: int, count: int) -> bytes:
    """A Modbus RTU request for ``count`` holding registers from ``address``."""
    _check_read(address, count)
    body = struct.pack(">BBHH", slave, READ_HOLDING_REGISTERS, address, count)
    return body + crc16(body)


def rtu_response_length(count: int) -> int:
    """The length of a complete RTU answer to a read of ``count`` registers."""
    return 5 + 2 * count


def parse_rtu_response(frame: bytes, slave: int, count: int) -> list[int]:
    """The registers in an RTU answer to a read of ``count`` registers.

    Raises ModbusError when the device answered with an exception, and
    FrameError when the frame is not a valid answer. A frame with two extra
    zero bytes after a correct CRC, which some Solarman logger firmwares
    send, is accepted.
    """
    if len(frame) >= 5 and frame[1] == READ_HOLDING_REGISTERS | 0x80:
        if crc16(frame[:3]) != frame[3:5]:
            raise FrameError("exception response with a bad CRC")
        raise exception_for(frame[2])
    expected = rtu_response_length(count)
    if len(frame) == expected + 2 and frame[-2:] == b"\x00\x00":
        frame = frame[:-2]
    if len(frame) != expected:
        raise FrameError(f"answer of {len(frame)} bytes, expected {expected}")
    if crc16(frame[:-2]) != frame[-2:]:
        raise FrameError("bad CRC")
    if frame[0] != slave:
        raise FrameError(f"answer from slave {frame[0]}, asked {slave}")
    if frame[1] != READ_HOLDING_REGISTERS:
        raise FrameError(f"answer to function {frame[1]}, asked {READ_HOLDING_REGISTERS}")
    if frame[2] != 2 * count:
        raise FrameError(f"byte count {frame[2]}, expected {2 * count}")
    return list(struct.unpack(f">{count}H", frame[3:-2]))


def tcp_read_request(transaction: int, unit: int, address: int, count: int) -> bytes:
    """A Modbus TCP request (MBAP header and PDU)."""
    _check_read(address, count)
    pdu = struct.pack(">BHH", READ_HOLDING_REGISTERS, address, count)
    return struct.pack(">HHHB", transaction & 0xFFFF, 0, len(pdu) + 1, unit) + pdu


def tcp_frame_length(header: bytes) -> int:
    """The whole length of a Modbus TCP frame, from its first six bytes."""
    if len(header) < 6:
        raise FrameError("MBAP header cut short")
    (length,) = struct.unpack(">H", header[4:6])
    return 6 + length


def parse_tcp_response(frame: bytes, transaction: int, unit: int, count: int) -> list[int]:
    """The registers in a Modbus TCP answer."""
    if len(frame) < 9:
        raise FrameError(f"answer of {len(frame)} bytes is too short")
    tid, protocol, length, answered_unit = struct.unpack(">HHHB", frame[:7])
    if tid != transaction & 0xFFFF:
        raise FrameError(f"answer to transaction {tid}, asked {transaction & 0xFFFF}")
    if protocol != 0:
        raise FrameError(f"protocol id {protocol} is not Modbus")
    if len(frame) != 6 + length:
        raise FrameError("frame length does not match its header")
    if answered_unit != unit:
        raise FrameError(f"answer from unit {answered_unit}, asked {unit}")
    function = frame[7]
    if function == READ_HOLDING_REGISTERS | 0x80:
        raise exception_for(frame[8])
    if function != READ_HOLDING_REGISTERS:
        raise FrameError(f"answer to function {function}")
    if frame[8] != 2 * count or len(frame) != 9 + 2 * count:
        raise FrameError(f"byte count {frame[8]}, expected {2 * count}")
    return list(struct.unpack(f">{count}H", frame[9:]))


def chunks(address: int, count: int, size: int = MAX_READ) -> list[tuple[int, int]]:
    """Split a read of ``count`` registers into requests of at most ``size``."""
    out = []
    end = address + count
    while address < end:
        step = min(size, end - address)
        out.append((address, step))
        address += step
    return out
