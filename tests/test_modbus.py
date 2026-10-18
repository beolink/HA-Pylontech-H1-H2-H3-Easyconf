"""Modbus RTU and TCP framing (modbus.py)."""

import struct

import pytest

from custom_components.pylontech_easyconf import modbus


def test_crc_of_the_textbook_request():
    # The read of ten registers from 0 on slave 1, as every Modbus guide shows it.
    assert modbus.rtu_read_request(1, 0, 10).hex() == "01030000000ac5cd"


def test_rtu_answer_round_trip():
    body = bytes([1, 3, 4]) + struct.pack(">HH", 0x5079, 0x6C6F)
    frame = body + modbus.crc16(body)
    assert modbus.parse_rtu_response(frame, 1, 2) == [0x5079, 0x6C6F]


def test_rtu_answer_with_the_loggers_extra_zero_bytes_is_accepted():
    body = bytes([1, 3, 2, 0, 33])
    assert modbus.parse_rtu_response(body + modbus.crc16(body) + b"\x00\x00", 1, 1) == [33]


def test_rtu_bad_crc_is_a_frame_error():
    body = bytes([1, 3, 2, 0, 33])
    with pytest.raises(modbus.FrameError):
        modbus.parse_rtu_response(body + b"\x00\x01", 1, 1)


def test_rtu_answer_from_another_slave_is_refused():
    body = bytes([2, 3, 2, 0, 33])
    with pytest.raises(modbus.FrameError):
        modbus.parse_rtu_response(body + modbus.crc16(body), 1, 1)


def test_rtu_exception_two_is_illegal_data_address():
    body = bytes([1, 0x83, 2])
    with pytest.raises(modbus.IllegalDataAddress):
        modbus.parse_rtu_response(body + modbus.crc16(body), 1, 4)


def test_rtu_other_exceptions_keep_their_code():
    body = bytes([1, 0x83, 4])
    with pytest.raises(modbus.ModbusError) as err:
        modbus.parse_rtu_response(body + modbus.crc16(body), 1, 4)
    assert err.value.code == 4
    assert not isinstance(err.value, modbus.IllegalDataAddress)


def test_tcp_request_and_answer():
    request = modbus.tcp_read_request(0x1234, 1, 0x1100, 2)
    assert request.hex() == "12340000000601031100" + "0002"
    answer = bytes.fromhex("123400000007010304") + struct.pack(">HH", 1965, 33)
    assert modbus.tcp_frame_length(answer[:6]) == len(answer)
    assert modbus.parse_tcp_response(answer, 0x1234, 1, 2) == [1965, 33]


def test_tcp_exception():
    answer = bytes.fromhex("0001000000030183" + "02")
    with pytest.raises(modbus.IllegalDataAddress):
        modbus.parse_tcp_response(answer, 1, 1, 2)


def test_tcp_answer_to_another_transaction_is_refused():
    answer = bytes.fromhex("000200000005010302") + struct.pack(">H", 5)
    with pytest.raises(modbus.FrameError):
        modbus.parse_tcp_response(answer, 1, 1, 1)


def test_reads_are_split_in_chunks_of_32():
    assert modbus.chunks(0x1500, 96) == [(0x1500, 32), (0x1520, 32), (0x1540, 32)]
    assert modbus.chunks(0x1500, 60) == [(0x1500, 32), (0x1520, 28)]
    assert modbus.chunks(0x1100, 1) == [(0x1100, 1)]


def test_only_reads_are_built():
    # Nothing in the integration can write to the battery: the module offers
    # no function that builds a write.
    assert not [name for name in dir(modbus) if "write" in name.lower()]


def test_counts_outside_the_protocol_are_refused():
    with pytest.raises(ValueError):
        modbus.rtu_read_request(1, 0, 0)
    with pytest.raises(ValueError):
        modbus.rtu_read_request(1, 0, 126)
