"""Solarman V5 framing, the protocol of the Wi-Fi and LAN module.

The Wi-Fi module of a Force H2 control module and the Wi-Fi and LAN ports of a
Force H3 controller are Solarman data loggers. Besides sending their data to
the Solarman cloud, they answer on TCP port 8899 locally: a Modbus RTU request
wrapped in a V5 frame is passed on to the BMS, and the BMS's answer comes back
wrapped the same way. This module builds and takes apart those frames; the
connection itself is in transport.py.

A frame, all numbers little-endian::

    A5 | length (2) | control (2) | sequence (2) | logger serial (4) | payload | checksum | 15

The payload of a request is a frame type (02), a sensor type (0000), three
times of four bytes (zero from a client) and the Modbus RTU request. The
payload of an answer is a frame type, a status byte, the same three times and
the Modbus RTU answer. The checksum is the low byte of the sum of every byte
between the start and the checksum.

A logger also sends frames of its own on the connection now and then (a
heartbeat, its data or its version), which are answered and otherwise passed
over. A logger answers a request that carries the wrong serial number with a
frame that carries the right one, which is how the integration learns the
serial on its own when nobody typed it in.

Free of Home Assistant on purpose, so the tests run without it.

Protocol described at https://pysolarmanv5.readthedocs.io/en/stable/solarmanv5_protocol.html
"""

from __future__ import annotations

from dataclasses import dataclass
import struct
import time

from .modbus import EXCEPTION_NAMES, FrameError, exception_for

START = 0xA5
END = 0x15
REQUEST = 0x4510
RESPONSE = 0x1510

#: Frames a logger sends on its own: handshake, data, info, heartbeat and
#: report. Each is answered with its own code less 0x30 in the high byte.
UNSOLICITED = {0x4110, 0x4210, 0x4310, 0x4710, 0x4810}

HEADER = 11
TRAILER = 2
#: Bytes of an answer's payload before the Modbus RTU frame starts.
ANSWER_PREFIX = 14
#: Bytes of a request's payload before the Modbus RTU frame starts.
REQUEST_PREFIX = 15

DEFAULT_PORT = 8899


def checksum(data: bytes) -> int:
    """The V5 checksum: the low byte of the sum of ``data``."""
    return sum(data) & 0xFF


def _pack_serial(serial: int) -> bytes:
    return struct.pack("<I", serial & 0xFFFFFFFF)


def build_request(serial: int, sequence: int, modbus_frame: bytes) -> bytes:
    """Wrap a Modbus RTU request in a V5 request frame."""
    payload = (
        b"\x02"  # frame type: request to the device on the logger's serial port
        + b"\x00\x00"  # sensor type
        + b"\x00" * 12  # total working time, power-on time, offset time
        + modbus_frame
    )
    header = (
        bytes([START])
        + struct.pack("<HH", len(payload), REQUEST)
        + bytes([sequence & 0xFF, 0])
        + _pack_serial(serial)
    )
    frame = header + payload
    return frame + bytes([checksum(frame[1:]), END])


@dataclass
class Frame:
    """One V5 frame as it came off the wire."""

    control: int
    sequence: int
    serial: int
    payload: bytes
    raw: bytes


def frame_length(buffer: bytes) -> int | None:
    """The full length of the frame at the start of ``buffer``, once known."""
    if len(buffer) < 3:
        return None
    (length,) = struct.unpack("<H", buffer[1:3])
    return HEADER + length + TRAILER


def split_frames(buffer: bytearray) -> list[Frame]:
    """Take every complete frame off the front of ``buffer``.

    Bytes before a start byte, and a frame whose end byte or checksum is
    wrong, are dropped so the reader finds its footing again; what is left
    is an incomplete frame waiting for more bytes.
    """
    frames: list[Frame] = []
    while buffer:
        if buffer[0] != START:
            start = buffer.find(bytes([START]))
            del buffer[: start if start >= 0 else len(buffer)]
            continue
        length = frame_length(bytes(buffer))
        if length is None or len(buffer) < length:
            break
        raw = bytes(buffer[:length])
        if raw[-1] != END or raw[-2] != checksum(raw[1:-2]):
            del buffer[0]
            continue
        del buffer[:length]
        control, = struct.unpack("<H", raw[3:5])
        serial, = struct.unpack("<I", raw[7:11])
        frames.append(Frame(control, raw[5], serial, raw[HEADER:-TRAILER], raw))
    return frames


def build_unsolicited_answer(frame: Frame, now: float | None = None) -> bytes:
    """The answer a logger expects to a frame it sent on its own."""
    control = frame.control - 0x3000
    payload = (
        b"\x00"  # frame type
        + b"\x01"  # status
        + struct.pack("<I", int(time.time() if now is None else now))
        + b"\x00\x00\x00\x00"
    )
    header = (
        bytes([START])
        + struct.pack("<HH", len(payload), control)
        + bytes([(frame.raw[5] + 1) & 0xFF, frame.raw[6]])
        + _pack_serial(frame.serial)
    )
    out = header + payload
    return out + bytes([checksum(out[1:]), END])


def modbus_payload(frame: Frame) -> bytes:
    """The Modbus RTU answer carried in a V5 answer.

    Raises a ModbusError when the logger passed on a Modbus exception in its
    short, undocumented form, and FrameError when it carried no Modbus answer
    at all, which is what a logger sends when the BMS behind it is off or
    does not answer.
    """
    if frame.control != RESPONSE:
        raise FrameError(f"control code {frame.control:#06x} is not an answer")
    body = frame.payload[ANSWER_PREFIX:]
    if len(body) < 5:
        if body and body[0] in EXCEPTION_NAMES:
            raise exception_for(body[0])
        raise FrameError("the logger passed on no answer from the battery")
    return body
