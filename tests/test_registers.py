"""Decoding the BMS's registers (registers.py), against a real Force H2 dump
and a Force H3 string made up in the same layout."""

import pytest

from fixtures import force_h2 as h2, force_h3 as h3

from custom_components.pylontech_easyconf import registers


def _h2(**changes):
    summary = list(h2.SUMMARY)
    for offset, word in changes.items():
        summary[int(offset[1:], 16)] = word
    return summary


def decode_h2(summary=None, cells=True):
    return registers.decode(
        summary or h2.SUMMARY,
        h2.MODULE_VOLTAGES,
        h2.MODULE_TEMPERATURES,
        h2.CELLS if cells else None,
        h2.CELL_TEMPERATURES if cells else None,
    )


def test_the_real_force_h2_dump():
    s = decode_h2()
    assert s.state == "idle"
    assert s.voltage == pytest.approx(196.5)
    assert s.current == 0
    assert s.power == 0
    assert s.bms_temperature == pytest.approx(36.0)
    assert (s.soc, s.soh, s.cycles) == (33, 97, 679)
    assert s.remaining_energy_kwh == pytest.approx(2.347)
    assert s.charge_today_kwh == pytest.approx(2.652)
    assert s.discharge_today_kwh == pytest.approx(4.021)
    assert (s.charge_total_kwh, s.discharge_total_kwh) == (4942, 4902)
    assert s.charge_voltage_limit == pytest.approx(216.0)
    assert s.charge_current_limit == pytest.approx(18.5)
    assert s.discharge_voltage_limit == pytest.approx(174.0)
    assert s.discharge_current_limit == pytest.approx(18.5)
    assert (s.module_count, s.cell_count, s.cells_per_module) == (2, 60, 30)
    assert s.fully_charged is False


def test_extremes_name_their_module_and_cell():
    s = decode_h2()
    # 0-based cell 3 is module 1's fourth cell; cell 24 is module 1's 25th.
    assert (s.cell_voltage_max.value, s.cell_voltage_max.module, s.cell_voltage_max.cell) == (
        pytest.approx(3.276), 1, 4)
    assert (s.cell_voltage_min.value, s.cell_voltage_min.module, s.cell_voltage_min.cell) == (
        pytest.approx(3.273), 1, 25)
    # Cell 30 is the first cell of module 2.
    assert (s.cell_temperature_max.value, s.cell_temperature_max.module,
            s.cell_temperature_max.cell) == (pytest.approx(28.0), 2, 1)
    assert s.cell_voltage_spread_mv == 3
    assert (s.module_voltage_max.value, s.module_voltage_max.module) == (pytest.approx(98.25), 1)
    assert (s.module_temperature_max.value, s.module_temperature_max.module) == (
        pytest.approx(27.2), 2)


def test_modules_and_cells():
    s = decode_h2()
    one, two = s.modules
    assert (one.number, one.voltage, one.temperature) == (1, 98.25, 25.7)
    assert (two.number, two.voltage, two.temperature) == (2, 98.24, 27.2)
    assert [c.number for c in one.cells] == list(range(1, 31))
    assert one.cells[0].voltage == pytest.approx(3.276)
    assert one.cells[24].voltage == pytest.approx(3.273)
    assert one.cells[22].temperature == pytest.approx(25.0)
    assert two.cells[0].temperature == pytest.approx(28.0)
    assert one.cell_voltage_spread_mv == 4
    assert two.cell_voltage_max == pytest.approx(3.277)


def test_without_the_cell_blocks_the_modules_have_no_cells():
    s = decode_h2(cells=False)
    assert [len(m.cells) for m in s.modules] == [0, 0]
    assert s.cells_per_module is None
    assert s.cell_voltage_max.value == pytest.approx(3.276)


def test_state_from_the_low_bits():
    assert decode_h2(_h2(o00=0x801)).state == "charging"
    assert decode_h2(_h2(o00=0x1002)).state == "discharging"
    assert decode_h2(_h2(o00=0x405)).state is None


def test_current_is_signed_32_bit_and_positive_while_charging():
    charging = decode_h2(_h2(o04=0, o05=1668))
    exporting = decode_h2(_h2(o04=65535, o05=63755))
    assert charging.current == pytest.approx(16.68)
    assert charging.power == pytest.approx(196.5 * 16.68, abs=0.1)
    assert exporting.current == pytest.approx(-17.81)


def test_negative_temperatures_are_signed():
    s = decode_h2(_h2(o1C=65536 - 25, o1D=65536 - 52, o14=65536 - 20, o15=65536 - 60))
    assert s.module_temperature_max.value == pytest.approx(-2.5)
    assert s.cell_temperature_min.value == pytest.approx(-6.0)


def test_fully_charged_flag():
    assert decode_h2(_h2(o38=1)).fully_charged is True


@pytest.mark.parametrize(
    "change, why",
    [
        ({"o07": 101}, "state of charge"),
        ({"o20": 140}, "state of health"),
        ({"o03": 12}, "stack voltage"),
        ({"o06": 1500}, "BMS temperature"),
        ({"o36": 0}, "modules in series"),
        ({"o36": 40}, "modules in series"),
    ],
)
def test_an_implausible_reading_is_refused_as_a_whole(change, why):
    with pytest.raises(registers.DecodeError, match=why):
        decode_h2(_h2(**change))


def test_a_cell_at_zero_volts_refuses_the_reading():
    cells = list(h2.CELLS)
    cells[7] = 0
    with pytest.raises(registers.DecodeError, match="module 1 cell 8"):
        registers.decode(h2.SUMMARY, h2.MODULE_VOLTAGES, h2.MODULE_TEMPERATURES, cells, None)


def test_module_voltages_that_do_not_add_up_refuse_the_reading():
    with pytest.raises(registers.DecodeError, match="module voltages add up"):
        registers.decode(h2.SUMMARY, [9825, 4000], h2.MODULE_TEMPERATURES)


def test_a_short_summary_is_refused():
    with pytest.raises(registers.DecodeError):
        registers.decode(h2.SUMMARY[:40])


def test_identity():
    identity = registers.decode_identity(h2.IDENTITY, h2.text_words(h2.SERIAL, 8))
    assert identity.brand == "Pylon"
    assert identity.device_name == "Force_H2"
    assert identity.model == "Force H2"
    assert identity.firmware == "1.6"
    assert identity.serial == h2.SERIAL
    assert registers.is_pylontech(identity)


def test_an_inverter_is_not_a_pylontech():
    identity = registers.decode_identity(h2.text_words("SOFAR", 5) + [0] * 11)
    assert not registers.is_pylontech(identity)


def test_model_from_the_cells_when_the_bms_has_no_name():
    assert registers.model_name(None, 32) == "Force H3"
    assert registers.model_name(None, 30) == "Force H2"
    assert registers.model_name(None, 15) is None
    assert registers.model_name("FORCE-H1") == "Force H1"


def test_force_h3_string_of_96_cells():
    s = registers.decode(h3.SUMMARY, h3.MODULE_VOLTAGES, h3.MODULE_TEMPERATURES,
                         h3.CELLS, h3.CELL_TEMPERATURES)
    assert s.state == "charging"
    assert s.current == pytest.approx(12.5)
    assert (s.module_count, s.cell_count, s.cells_per_module) == (3, 96, 32)
    assert (s.cell_voltage_max.module, s.cell_voltage_max.cell) == (3, 32)
    assert (s.cell_voltage_min.module, s.cell_voltage_min.cell) == (2, 9)
    assert (s.cell_temperature_min.value, s.cell_temperature_min.module,
            s.cell_temperature_min.cell) == (pytest.approx(-1.5), 2, 5)
    assert s.modules[1].temperature == pytest.approx(-1.0)
    assert s.modules[1].cells[4].temperature == pytest.approx(-1.5)
    assert s.modules[2].cells[31].voltage == pytest.approx(3.342)
    assert s.cell_voltage_spread_mv == 61
    assert s.discharge_current_limit == pytest.approx(50.0)
