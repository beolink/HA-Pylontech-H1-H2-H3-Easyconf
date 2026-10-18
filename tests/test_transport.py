"""The three transports and the reader, over a real loopback socket against
fake_logger.py (transport.py, reader.py)."""

import asyncio

import pytest

from fake_logger import FakeBattery, FakeServer
from fixtures import force_h2 as h2, force_h3 as h3

from custom_components.pylontech_easyconf import reader, transport
from custom_components.pylontech_easyconf.modbus import IllegalDataAddress


def run(coro):
    return asyncio.run(coro)


async def _read(battery, kind=None, **kw):
    async with FakeServer(battery) as server:
        t = transport.make_transport(kind or battery.kind, "127.0.0.1", server.port, **kw)
        try:
            return await reader.read_snapshot(t), t, server
        finally:
            await t.close()


@pytest.mark.parametrize("kind", transport.KINDS)
def test_every_transport_reads_the_whole_stack(kind):
    battery = FakeBattery(h2.bank(), kind=kind)
    reading, t, server = run(_read(battery, serial=battery.serial))
    s = reading.snapshot
    assert reading.summary_start == 0x1100
    assert s.soc == 33 and s.cycles == 679
    assert [len(m.cells) for m in s.modules] == [30, 30]
    assert s.modules[1].cells[0].temperature == pytest.approx(28.0)
    # Summary in two chunks, one request per module block, two per cell block.
    assert battery.requests == [
        (0x1100, 32), (0x1120, 32), (0x1460, 2), (0x14B0, 2),
        (0x1500, 32), (0x1520, 28), (0x1800, 32), (0x1820, 28),
    ]
    assert server.connections == 1
    assert t.failures == 0


def test_the_logger_serial_is_learned_when_not_given():
    battery = FakeBattery(h2.bank())
    learned = []
    reading, t, _ = run(_read(battery, serial=0, on_serial=learned.append))
    assert reading.snapshot.soc == 33
    assert t.serial == battery.serial
    assert learned == [battery.serial]
    assert battery.wrong_serial_answers == 1


def test_a_wrong_serial_is_corrected_by_the_logger():
    battery = FakeBattery(h2.bank())
    reading, t, _ = run(_read(battery, serial=1234))
    assert reading.snapshot.soc == 33
    assert t.serial == battery.serial


def test_heartbeats_in_the_middle_are_answered_and_passed_over():
    battery = FakeBattery(h2.bank(), heartbeat_every=2)
    reading, t, _ = run(_read(battery, serial=battery.serial))
    assert reading.snapshot.cell_count == 60
    assert t.unsolicited == 4


def test_the_0x1400_mirror_is_used_when_0x1100_is_missing():
    battery = FakeBattery(h3.bank(), serial=99)
    reading, _, _ = run(_read(battery, serial=99))
    assert reading.summary_start == 0x1400
    assert reading.snapshot.cells_per_module == 32
    assert reading.snapshot.modules[2].cells[31].voltage == pytest.approx(3.342)


def test_cells_can_be_left_out():
    battery = FakeBattery(h2.bank(), kind="modbus_tcp")

    async def go():
        async with FakeServer(battery) as server:
            t = transport.make_transport("modbus_tcp", "127.0.0.1", server.port)
            try:
                return await reader.read_snapshot(t, cells=False)
            finally:
                await t.close()

    reading = run(go())
    assert all(not m.cells for m in reading.snapshot.modules)
    assert not [r for r in battery.requests if r[0] >= 0x1500]


def test_a_bms_without_cell_temperatures_still_gives_cell_voltages():
    battery = FakeBattery(h2.bank(), kind="rtu_over_tcp", missing=[(0x1800, 0x18FF)])
    reading, _, _ = run(_read(battery))
    cells = reading.snapshot.modules[0].cells
    assert cells[0].voltage == pytest.approx(3.276)
    assert cells[0].temperature is None


def test_a_battery_that_is_off_behind_the_logger():
    battery = FakeBattery(h2.bank(), battery_off=True)
    with pytest.raises(transport.TransportError) as err:
        run(_read(battery, serial=battery.serial))
    assert err.value.connected


def test_a_silent_device_times_out_and_the_connection_is_dropped():
    battery = FakeBattery(h2.bank(), kind="modbus_tcp", silent=True)

    async def go():
        async with FakeServer(battery) as server:
            t = transport.make_transport("modbus_tcp", "127.0.0.1", server.port, timeout=0.3)
            with pytest.raises(transport.TransportError) as err:
                await t.read_registers(0x1100, 4)
            assert err.value.connected
            assert not t.connected
            assert t.failures == 1

    run(go())


def test_nobody_listening_is_not_connected():
    async def go():
        t = transport.make_transport("modbus_tcp", "127.0.0.1", 1)
        with pytest.raises(transport.TransportError) as err:
            await t.read_registers(0x1100, 4)
        assert not err.value.connected

    run(go())


def test_a_missing_block_is_a_modbus_exception_and_keeps_the_connection():
    battery = FakeBattery(h2.bank(), kind="modbus_tcp")

    async def go():
        async with FakeServer(battery) as server:
            t = transport.make_transport("modbus_tcp", "127.0.0.1", server.port)
            with pytest.raises(IllegalDataAddress):
                await t.read_registers(0x1200, 4)
            assert t.connected
            assert await t.read_registers(0x1107, 1) == [33]
            await t.close()

    run(go())


def test_the_connection_is_opened_again_after_a_failure():
    battery = FakeBattery(h2.bank(), kind="rtu_over_tcp")

    async def go():
        async with FakeServer(battery) as server:
            t = transport.make_transport("rtu_over_tcp", "127.0.0.1", server.port, timeout=0.3)
            battery.silent = True
            with pytest.raises(transport.TransportError):
                await t.read_registers(0x1107, 1)
            battery.silent = False
            assert await t.read_registers(0x1107, 1) == [33]
            assert server.connections == 2
            await t.close()

    run(go())


def test_identity_and_probe_find_the_protocol():
    battery = FakeBattery(h2.bank(), kind="modbus_tcp")

    async def go():
        async with FakeServer(battery) as server:
            return await reader.probe("127.0.0.1", server.port, timeout=1)

    result = run(go())
    # An unusual port is tried as RTU first; the fake answers nothing to that
    # and Modbus TCP is next.
    assert result.kind == "modbus_tcp"
    assert result.identity.model == "Force H2"
    assert result.identity.serial == h2.SERIAL
    assert result.identity.firmware == "1.6"


def test_probe_learns_the_logger_serial():
    battery = FakeBattery(h2.bank())

    async def go():
        async with FakeServer(battery) as server:
            return await reader.probe("127.0.0.1", server.port, kind="solarman_v5", timeout=1)

    result = run(go())
    assert (result.kind, result.serial) == ("solarman_v5", battery.serial)


def test_probe_tells_an_inverter_logger_apart():
    bank = h2.bank()
    for offset, word in enumerate(h2.text_words("Deye", 5) + [0] * 11):
        bank[0x1000 + offset] = word
    battery = FakeBattery(bank)

    async def go():
        async with FakeServer(battery) as server:
            return await reader.probe("127.0.0.1", server.port, kind="solarman_v5", timeout=1)

    with pytest.raises(reader.ProbeError) as err:
        run(go())
    assert err.value.reason == "not_pylontech"


def test_probe_with_nothing_there():
    with pytest.raises(reader.ProbeError) as err:
        run(reader.probe("127.0.0.1", 1, kind="modbus_tcp", timeout=0.5))
    assert err.value.reason == "cannot_connect"


def test_probe_of_a_logger_whose_battery_is_off():
    battery = FakeBattery(h2.bank(), battery_off=True)

    async def go():
        async with FakeServer(battery) as server:
            return await reader.probe("127.0.0.1", server.port, kind="solarman_v5", timeout=1)

    with pytest.raises(reader.ProbeError) as err:
        run(go())
    assert err.value.reason == "no_battery"


def test_auto_attempt_order():
    assert reader.attempts("auto", None)[0] == ("solarman_v5", 8899)
    assert reader.attempts("auto", 502)[0] == ("modbus_tcp", 502)
    assert reader.attempts("auto", 4196)[0] == ("rtu_over_tcp", 4196)
    assert reader.attempts("solarman_v5", None) == [("solarman_v5", 8899)]
