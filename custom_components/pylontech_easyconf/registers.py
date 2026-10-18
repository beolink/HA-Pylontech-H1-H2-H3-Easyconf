"""The Force BMS's register map, and turning its words into a Snapshot.

The map is the one the BMS answers on Modbus slave 1, through its RS485 port
and through the Solarman logger in its Wi-Fi or LAN module alike. Pylontech
publishes it to inverter makers only; what is here was verified register by
register on a Force H2 against the Solarman app and the inverter's own
telemetry (goodwe_manager, 2026-09/10, MIT licence) and agrees with the Force
H1/H2/H3 profile of ha-solarman, which reads the same block at 0x1400 instead
of 0x1100. Both blocks hold the same words; the reader uses whichever the BMS
answers.

Words are unsigned 16-bit; "signed" marks a two's complement word, and a
32-bit value is two words, the high one first.

Summary block, 64 words from 0x1100 (or 0x1400), as offsets:

    00  state, bits 0-2: 1 charging, 2 discharging, 3 idle
    03  stack voltage, 0.1 V
    04  current, 32-bit signed, 0.01 A, positive while charging
    06  BMS board temperature, signed, 0.1 degC
    07  state of charge, %
    08  cycle count
    09  charge voltage limit, 0.1 V
    0A  charge current limit, 32-bit, 0.01 A
    0C  discharge voltage limit, 0.1 V
    0D  discharge current limit, 32-bit signed (negative), 0.01 A
    10  highest / lowest cell voltage, mV; 12, 13 their cells (0-based)
    14  highest / lowest cell temperature, signed, 0.1 degC; 16, 17 their cells
    18  highest / lowest module voltage, 0.01 V; 1A, 1B their modules (0-based)
    1C  highest / lowest module temperature, signed, 0.1 degC; 1E, 1F their modules
    20  state of health, %
    21  remaining energy, 32-bit, Wh
    23  charged today, 32-bit, Wh;  25  discharged today, 32-bit, Wh
    2B  charged in total, 32-bit, kWh;  2D  discharged in total, 32-bit, kWh
    36  modules in series
    37  cells in series, all modules together
    38  1 while the battery is fully charged

Elsewhere: 0x1000 brand (ASCII, "Pylon"), 0x1005 the BMS's name ("Force_H2"),
0x100A firmware (major, minor byte), 0x1450 serial number (16 ASCII
characters), 0x1460 + m module voltage (0.01 V), 0x14B0 + m module
temperature (signed, 0.1 degC), 0x1500 + n cell voltage (mV), 0x1800 + n cell
temperature (signed, 0.1 degC). Cells are numbered across the whole string,
module by module: a Force H1 module has 15 cells, a Force H2 module 15 or 30
depending on its type, a Force H3 module 32.

Free of Home Assistant on purpose, so the tests run without it.
"""

from __future__ import annotations

from .model import Cell, Extreme, Identity, Module, Snapshot

IDENTITY_START = 0x1000
IDENTITY_COUNT = 16
SUMMARY_STARTS = (0x1100, 0x1400)
SUMMARY_COUNT = 64
SERIAL_START = 0x1450
SERIAL_COUNT = 8
MODULE_VOLTAGES_START = 0x1460
MODULE_TEMPERATURES_START = 0x14B0
CELL_VOLTAGES_START = 0x1500
CELL_TEMPERATURES_START = 0x1800

#: The most modules one string has room for in the module blocks, and the
#: most cells across them (a Force H3 string of nine modules has 288).
MAX_MODULES = 16
MAX_CELLS = 512

STATES = {1: "charging", 2: "discharging", 3: "idle"}

#: Cells per module of each family, for naming a BMS that does not say.
CELLS_PER_MODULE_MODEL = {32: "Force H3", 30: "Force H2"}


class DecodeError(ValueError):
    """The words read do not make a plausible reading of a battery."""


def signed(word: int) -> int:
    return word - 0x10000 if word >= 0x8000 else word


def signed32(high: int, low: int) -> int:
    value = (high << 16) | low
    return value - 0x100000000 if value >= 0x80000000 else value


def ascii_words(words: list[int]) -> str:
    """The text in a run of words, two characters each, high byte first."""
    raw = b"".join(w.to_bytes(2, "big") for w in words)
    text = raw.split(b"\x00", 1)[0].decode("ascii", errors="replace")
    return "".join(ch for ch in text if ch.isprintable()).strip()


def firmware(word: int) -> str | None:
    """The firmware word as "major.minor", or None when it reads zero."""
    if not word:
        return None
    return f"{word >> 8}.{word & 0xFF}"


def model_name(device_name: str | None, cells_per_module: int | None = None) -> str | None:
    """The family in readable form, from the BMS's own name if it has one."""
    if device_name:
        name = device_name.replace("_", " ").strip()
        for family in ("H1", "H2", "H3"):
            if family in name.upper().replace(" ", ""):
                return f"Force {family}"
        return name
    if cells_per_module in CELLS_PER_MODULE_MODEL:
        return CELLS_PER_MODULE_MODEL[cells_per_module]
    return None


def is_pylontech(identity: Identity) -> bool:
    """Whether the identity block is a Pylontech BMS's."""
    brand = (identity.brand or "").lower()
    name = (identity.device_name or "").lower()
    return brand.startswith("pylon") or name.startswith("force")


def decode_identity(words: list[int], serial_words: list[int] | None = None) -> Identity:
    """The identity block from 0x1000 and, if read, the serial from 0x1450."""
    if len(words) < IDENTITY_COUNT:
        raise DecodeError(f"identity block of {len(words)} words, expected {IDENTITY_COUNT}")
    device_name = ascii_words(words[5:10]) or None
    serial = ascii_words(serial_words) if serial_words else None
    return Identity(
        brand=ascii_words(words[0:5]) or None,
        device_name=device_name,
        model=model_name(device_name),
        firmware=firmware(words[10]),
        serial=serial or None,
    )


def counts(summary: list[int]) -> tuple[int, int]:
    """Modules and cells in series, as the summary block states them."""
    if len(summary) < SUMMARY_COUNT:
        raise DecodeError(f"summary block of {len(summary)} words, expected {SUMMARY_COUNT}")
    modules, cells = summary[0x36], summary[0x37]
    if not 1 <= modules <= MAX_MODULES:
        raise DecodeError(f"{modules} modules in series is outside 1-{MAX_MODULES}")
    if not 0 <= cells <= MAX_CELLS:
        raise DecodeError(f"{cells} cells in series is outside 0-{MAX_CELLS}")
    return modules, cells


def _locate_cell(index: int, cells_per_module: int | None) -> Extreme:
    if not cells_per_module:
        return Extreme(None, None, index + 1)
    return Extreme(None, index // cells_per_module + 1, index % cells_per_module + 1)


def _extreme_cell(value: float, index: int, cells_per_module: int | None) -> Extreme:
    where = _locate_cell(index, cells_per_module)
    where.value = value
    return where


def decode(
    summary: list[int],
    module_voltages: list[int] | None = None,
    module_temperatures: list[int] | None = None,
    cell_voltages: list[int] | None = None,
    cell_temperatures: list[int] | None = None,
) -> Snapshot:
    """A Snapshot from the summary block and whichever detail blocks were read.

    Raises DecodeError when the reading is not plausible, so a garbled answer
    never reaches an entity: a whole reading or none.
    """
    modules_in_series, cells_in_series = counts(summary)
    w = summary

    def reg32(offset: int) -> int:
        return signed32(w[offset], w[offset + 1])

    cpm = cells_in_series // modules_in_series if cells_in_series % modules_in_series == 0 else None
    if cpm == 0:
        cpm = None

    snap = Snapshot(
        state=STATES.get(w[0x00] & 0x7),
        voltage=w[0x03] / 10,
        current=reg32(0x04) / 100,
        bms_temperature=signed(w[0x06]) / 10,
        soc=w[0x07],
        soh=w[0x20],
        cycles=w[0x08],
        remaining_energy_kwh=reg32(0x21) / 1000,
        charge_today_kwh=reg32(0x23) / 1000,
        discharge_today_kwh=reg32(0x25) / 1000,
        charge_total_kwh=float(reg32(0x2B)),
        discharge_total_kwh=float(reg32(0x2D)),
        charge_voltage_limit=w[0x09] / 10,
        charge_current_limit=reg32(0x0A) / 100,
        discharge_voltage_limit=w[0x0C] / 10,
        discharge_current_limit=abs(reg32(0x0D)) / 100,
        cell_voltage_max=_extreme_cell(w[0x10] / 1000, w[0x12], cpm),
        cell_voltage_min=_extreme_cell(w[0x11] / 1000, w[0x13], cpm),
        cell_temperature_max=_extreme_cell(signed(w[0x14]) / 10, w[0x16], cpm),
        cell_temperature_min=_extreme_cell(signed(w[0x15]) / 10, w[0x17], cpm),
        module_voltage_max=Extreme(w[0x18] / 100, w[0x1A] + 1),
        module_voltage_min=Extreme(w[0x19] / 100, w[0x1B] + 1),
        module_temperature_max=Extreme(signed(w[0x1C]) / 10, w[0x1E] + 1),
        module_temperature_min=Extreme(signed(w[0x1D]) / 10, w[0x1F] + 1),
        fully_charged=bool(w[0x38]),
        module_count=modules_in_series,
        cell_count=cells_in_series,
        raw={"summary": list(summary), "status_word": w[0x00]},
    )

    modules = [Module(number=m + 1) for m in range(modules_in_series)]
    if module_voltages is not None:
        for module, word in zip(modules, module_voltages, strict=False):
            module.voltage = word / 100
    if module_temperatures is not None:
        for module, word in zip(modules, module_temperatures, strict=False):
            module.temperature = signed(word) / 10
    if cell_voltages is not None and cpm:
        for index, word in enumerate(cell_voltages[:cells_in_series]):
            module = modules[index // cpm]
            module.cells.append(Cell(number=index % cpm + 1, voltage=word / 1000))
        if cell_temperatures is not None:
            for index, word in enumerate(cell_temperatures[:cells_in_series]):
                cells = modules[index // cpm].cells
                if index % cpm < len(cells):
                    cells[index % cpm].temperature = signed(word) / 10
    snap.modules = modules
    check(snap)
    return snap


def check(snap: Snapshot) -> None:
    """Raise DecodeError unless the reading is that of a working battery."""
    def fail(why: str) -> None:
        raise DecodeError(why)

    if snap.soc is None or not 0 <= snap.soc <= 100:
        fail(f"state of charge {snap.soc} is outside 0-100")
    if snap.soh is not None and not 0 <= snap.soh <= 100:
        fail(f"state of health {snap.soh} is outside 0-100")
    if snap.voltage is None or not 40 <= snap.voltage <= 1100:
        fail(f"stack voltage {snap.voltage} V is outside 40-1100 V")
    highest = snap.cell_temperature_max.value if snap.cell_temperature_max else None
    lowest = snap.cell_temperature_min.value if snap.cell_temperature_min else None
    for name, value in (("BMS", snap.bms_temperature), ("highest cell", highest),
                        ("lowest cell", lowest)):
        if value is not None and not -40 <= value <= 90:
            fail(f"{name} temperature {value} degC is outside -40-90 degC")
    cells = [c for m in snap.modules for c in m.cells]
    for module in snap.modules:
        for cell in module.cells:
            if cell.voltage is not None and not 1.5 <= cell.voltage <= 4.5:
                fail(f"module {module.number} cell {cell.number} at {cell.voltage} V")
            if cell.temperature is not None and not -40 <= cell.temperature <= 90:
                fail(f"module {module.number} cell {cell.number} at {cell.temperature} degC")
        if module.temperature is not None and not -40 <= module.temperature <= 90:
            fail(f"module {module.number} at {module.temperature} degC")
    if cells and snap.cell_count and len(cells) != snap.cell_count:
        fail(f"{len(cells)} cell voltages for {snap.cell_count} cells in series")
    voltages = [m.voltage for m in snap.modules if m.voltage is not None]
    if voltages and len(voltages) == len(snap.modules) and snap.voltage:
        total = sum(voltages)
        if abs(total - snap.voltage) > 0.03 * snap.voltage + 1:
            fail(f"module voltages add up to {total:.1f} V, the stack reads {snap.voltage} V")
    if cells and snap.voltage:
        total = sum(c.voltage for c in cells if c.voltage is not None)
        if abs(total - snap.voltage) > 0.03 * snap.voltage + 1:
            fail(f"cell voltages add up to {total:.1f} V, the stack reads {snap.voltage} V")
