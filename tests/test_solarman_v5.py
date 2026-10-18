"""Solarman V5 framing (solarman_v5.py)."""

import struct

import pytest

from custom_components.pylontech_easyconf import modbus, solarman_v5 as v5


def test_request_frame_layout():
    rtu = modbus.rtu_read_request(1, 0x1000, 16)
    frame = v5.build_request(2712345678, 0x42, rtu)
    assert frame[0] == 0xA5 and frame[-1] == 0x15
    assert struct.unpack("<H", frame[1:3])[0] == 15 + len(rtu) == len(frame) - 13
    assert frame[3:5] == bytes([0x10, 0x45])
    assert frame[5:7] == bytes([0x42, 0x00])
    assert struct.unpack("<I", frame[7:11])[0] == 2712345678
    assert frame[11] == 0x02
    assert frame[12:26] == b"\x00" * 14
    assert frame[26:-2] == rtu
    assert frame[-2] == sum(frame[1:-2]) & 0xFF


def _answer(sequence, serial, rtu):
    payload = b"\x02\x01" + b"\x00" * 12 + rtu
    head = b"\xa5" + struct.pack("<HH", len(payload), v5.RESPONSE) + bytes([sequence, 1])
    frame = head + struct.pack("<I", serial) + payload
    return frame + bytes([v5.checksum(frame[1:]), 0x15])


def test_frames_are_split_off_a_stream_with_noise_and_a_partial_frame():
    rtu = bytes([1, 3, 2, 0, 33])
    rtu += modbus.crc16(rtu)
    one, two = _answer(1, 7, rtu), _answer(2, 7, rtu)
    buffer = bytearray(b"\x00\xff" + one + two + two[:9])
    frames = v5.split_frames(buffer)
    assert [f.sequence for f in frames] == [1, 2]
    assert bytes(buffer) == two[:9]
    assert v5.modbus_payload(frames[0]) == rtu


def test_a_frame_with_a_bad_checksum_is_dropped():
    rtu = bytes([1, 3, 2, 0, 33])
    bad = bytearray(_answer(1, 7, rtu + modbus.crc16(rtu)))
    bad[-2] ^= 0xFF
    good = _answer(2, 7, rtu + modbus.crc16(rtu))
    buffer = bytearray(bytes(bad) + good)
    assert [f.sequence for f in v5.split_frames(buffer)] == [2]


def test_an_answer_without_modbus_means_the_battery_did_not_answer():
    frame = v5.split_frames(bytearray(_answer(1, 7, b"")))[0]
    with pytest.raises(modbus.FrameError):
        v5.modbus_payload(frame)


def test_the_short_exception_form_is_a_modbus_error():
    frame = v5.split_frames(bytearray(_answer(1, 7, b"\x02")))[0]
    with pytest.raises(modbus.IllegalDataAddress):
        v5.modbus_payload(frame)


def test_a_heartbeat_is_answered_with_its_code_less_0x30():
    payload = b"\x00"
    head = b"\xa5" + struct.pack("<HH", 1, 0x4710) + bytes([0x33, 0x00]) + struct.pack("<I", 9)
    raw = head + payload
    raw += bytes([v5.checksum(raw[1:]), 0x15])
    heartbeat = v5.split_frames(bytearray(raw))[0]
    assert heartbeat.control in v5.UNSOLICITED
    answer = v5.build_unsolicited_answer(heartbeat, now=1_700_000_000)
    parsed = v5.split_frames(bytearray(answer))[0]
    assert parsed.control == 0x1710
    assert parsed.serial == 9
    assert answer[5] == 0x34
