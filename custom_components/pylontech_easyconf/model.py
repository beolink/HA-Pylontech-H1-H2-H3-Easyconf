"""What one reading of a Pylontech Force stack holds.

Shared by the local reader (registers.py) and the cloud (cloud.py), so the
entities do not need to know where a value came from. Free of Home Assistant
on purpose. A value the source does not have is None, never zero: a cloud
reading without cell voltages has no cells, not cells at 0 V.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class Identity:
    """Who the battery is. Read at set-up and now and then after."""

    brand: str | None = None
    #: The name the BMS gives itself, for example "Force_H2".
    device_name: str | None = None
    #: The family in readable form, "Force H1", "Force H2" or "Force H3".
    model: str | None = None
    firmware: str | None = None
    #: The BMS's own serial number.
    serial: str | None = None


@dataclass
class Cell:
    """One cell, numbered from 1 within its module."""

    number: int
    voltage: float | None = None
    temperature: float | None = None


@dataclass
class Module:
    """One battery module, numbered from 1 in the order the BMS lists them."""

    number: int
    voltage: float | None = None
    temperature: float | None = None
    cells: list[Cell] = field(default_factory=list)

    @property
    def cell_voltage_max(self) -> float | None:
        values = [c.voltage for c in self.cells if c.voltage is not None]
        return max(values) if values else None

    @property
    def cell_voltage_min(self) -> float | None:
        values = [c.voltage for c in self.cells if c.voltage is not None]
        return min(values) if values else None

    @property
    def cell_voltage_spread_mv(self) -> int | None:
        high, low = self.cell_voltage_max, self.cell_voltage_min
        if high is None or low is None:
            return None
        return round((high - low) * 1000)


@dataclass
class Extreme:
    """The highest or lowest of something, and where it is."""

    value: float | None
    #: 1-based module number, or None where the BMS does not say.
    module: int | None = None
    #: 1-based cell number within the module.
    cell: int | None = None


@dataclass
class Extra:
    """A value the cloud sends that the integration has no name of its own for."""

    name: str
    value: Any
    unit: str | None = None


@dataclass
class Snapshot:
    """One whole reading of the stack."""

    #: "charging", "discharging" or "idle", or None.
    state: str | None = None
    voltage: float | None = None
    #: Amperes, positive while the battery charges.
    current: float | None = None
    bms_temperature: float | None = None
    soc: int | None = None
    soh: int | None = None
    cycles: int | None = None
    remaining_energy_kwh: float | None = None
    charge_today_kwh: float | None = None
    discharge_today_kwh: float | None = None
    charge_total_kwh: float | None = None
    discharge_total_kwh: float | None = None
    charge_voltage_limit: float | None = None
    charge_current_limit: float | None = None
    discharge_voltage_limit: float | None = None
    discharge_current_limit: float | None = None
    cell_voltage_max: Extreme | None = None
    cell_voltage_min: Extreme | None = None
    cell_temperature_max: Extreme | None = None
    cell_temperature_min: Extreme | None = None
    module_voltage_max: Extreme | None = None
    module_voltage_min: Extreme | None = None
    module_temperature_max: Extreme | None = None
    module_temperature_min: Extreme | None = None
    fully_charged: bool | None = None
    module_count: int | None = None
    cell_count: int | None = None
    modules: list[Module] = field(default_factory=list)
    #: Values without a name of their own, keyed by the source's key.
    extras: dict[str, Extra] = field(default_factory=dict)
    #: The raw words or fields behind the reading, for the diagnostics.
    raw: dict[str, Any] = field(default_factory=dict)

    @property
    def power(self) -> float | None:
        """Watts, positive while the battery charges."""
        if self.voltage is None or self.current is None:
            return None
        return round(self.voltage * self.current, 1)

    @property
    def cell_voltage_spread_mv(self) -> int | None:
        high = self.cell_voltage_max.value if self.cell_voltage_max else None
        low = self.cell_voltage_min.value if self.cell_voltage_min else None
        if high is None or low is None:
            return None
        return round((high - low) * 1000)

    @property
    def cells_per_module(self) -> int | None:
        if not self.modules:
            return None
        counts = {len(m.cells) for m in self.modules}
        return counts.pop() if len(counts) == 1 and 0 not in counts else None
