"""Sensors: the stack, each module, each cell, and what the cloud adds."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
import logging
import re
from typing import Any

from homeassistant.components.sensor import (
    RestoreSensor,
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.const import (
    PERCENTAGE,
    EntityCategory,
    UnitOfElectricCurrent,
    UnitOfElectricPotential,
    UnitOfEnergy,
    UnitOfPower,
    UnitOfTemperature,
)
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .coordinator import PylontechConfigEntry, PylontechCoordinator
from .entity import PylontechEntity
from .model import Extreme, Module, Snapshot

_LOGGER = logging.getLogger(__name__)

PARALLEL_UPDATES = 0

V = UnitOfElectricPotential.VOLT
MV = UnitOfElectricPotential.MILLIVOLT
A = UnitOfElectricCurrent.AMPERE
C = UnitOfTemperature.CELSIUS
KWH = UnitOfEnergy.KILO_WATT_HOUR
MEASUREMENT = SensorStateClass.MEASUREMENT
DIAGNOSTIC = EntityCategory.DIAGNOSTIC

#: The most a battery could charge or discharge in an hour, with room to
#: spare: a total that climbs faster than this between two polls is a glitch
#: of the counter, which the published register scans warn of, not energy.
MAX_KW = 60.0

#: The unique id of one cell's sensor, <stack>_m<module>_cell_<cell>_<kind>.
CELL_UNIQUE_ID = re.compile(r"_m\d+_cell_\d+_(voltage|temperature)$")
#: A module's sensors that come from its cells, gone with the cell data.
FROM_CELLS_UNIQUE_ID = re.compile(r"_m\d+_cell_voltage_(max|min|spread)$")


def _where(extreme: Extreme | None) -> dict[str, Any]:
    if extreme is None:
        return {}
    return {k: v for k, v in (("module", extreme.module), ("cell", extreme.cell)) if v}


def _value(extreme: Extreme | None) -> float | None:
    return extreme.value if extreme is not None else None


@dataclass(frozen=True, kw_only=True)
class StackSensorDescription(SensorEntityDescription):
    value_fn: Callable[[Snapshot], Any]
    attrs_fn: Callable[[Snapshot], dict[str, Any]] | None = None
    #: "lifetime": a total that never falls; "daily": one that falls at midnight.
    guard: str | None = None


STACK_SENSORS: tuple[StackSensorDescription, ...] = (
    StackSensorDescription(
        key="soc", translation_key="soc", device_class=SensorDeviceClass.BATTERY,
        native_unit_of_measurement=PERCENTAGE, state_class=MEASUREMENT,
        value_fn=lambda s: s.soc,
    ),
    StackSensorDescription(
        key="soh", translation_key="soh", native_unit_of_measurement=PERCENTAGE,
        state_class=MEASUREMENT, value_fn=lambda s: s.soh,
    ),
    StackSensorDescription(
        key="state", translation_key="state", device_class=SensorDeviceClass.ENUM,
        options=["charging", "discharging", "idle"], value_fn=lambda s: s.state,
    ),
    StackSensorDescription(
        key="voltage", translation_key="voltage", device_class=SensorDeviceClass.VOLTAGE,
        native_unit_of_measurement=V, state_class=MEASUREMENT, suggested_display_precision=1,
        value_fn=lambda s: s.voltage,
    ),
    StackSensorDescription(
        key="current", translation_key="current", device_class=SensorDeviceClass.CURRENT,
        native_unit_of_measurement=A, state_class=MEASUREMENT, suggested_display_precision=2,
        value_fn=lambda s: s.current,
    ),
    StackSensorDescription(
        key="power", translation_key="power", device_class=SensorDeviceClass.POWER,
        native_unit_of_measurement=UnitOfPower.WATT, state_class=MEASUREMENT,
        suggested_display_precision=0, value_fn=lambda s: s.power,
    ),
    StackSensorDescription(
        key="bms_temperature", translation_key="bms_temperature",
        device_class=SensorDeviceClass.TEMPERATURE, native_unit_of_measurement=C,
        state_class=MEASUREMENT, suggested_display_precision=1,
        value_fn=lambda s: s.bms_temperature,
    ),
    StackSensorDescription(
        key="cycles", translation_key="cycles", state_class=SensorStateClass.TOTAL_INCREASING,
        value_fn=lambda s: s.cycles,
    ),
    StackSensorDescription(
        key="remaining_energy", translation_key="remaining_energy",
        device_class=SensorDeviceClass.ENERGY_STORAGE, native_unit_of_measurement=KWH,
        state_class=MEASUREMENT, suggested_display_precision=2,
        value_fn=lambda s: s.remaining_energy_kwh,
    ),
    StackSensorDescription(
        key="charge_today", translation_key="charge_today",
        device_class=SensorDeviceClass.ENERGY, native_unit_of_measurement=KWH,
        state_class=SensorStateClass.TOTAL_INCREASING, suggested_display_precision=2,
        value_fn=lambda s: s.charge_today_kwh, guard="daily",
    ),
    StackSensorDescription(
        key="discharge_today", translation_key="discharge_today",
        device_class=SensorDeviceClass.ENERGY, native_unit_of_measurement=KWH,
        state_class=SensorStateClass.TOTAL_INCREASING, suggested_display_precision=2,
        value_fn=lambda s: s.discharge_today_kwh, guard="daily",
    ),
    StackSensorDescription(
        key="charge_total", translation_key="charge_total",
        device_class=SensorDeviceClass.ENERGY, native_unit_of_measurement=KWH,
        state_class=SensorStateClass.TOTAL_INCREASING, suggested_display_precision=0,
        value_fn=lambda s: s.charge_total_kwh, guard="lifetime",
    ),
    StackSensorDescription(
        key="discharge_total", translation_key="discharge_total",
        device_class=SensorDeviceClass.ENERGY, native_unit_of_measurement=KWH,
        state_class=SensorStateClass.TOTAL_INCREASING, suggested_display_precision=0,
        value_fn=lambda s: s.discharge_total_kwh, guard="lifetime",
    ),
    StackSensorDescription(
        key="cell_voltage_max", translation_key="cell_voltage_max",
        device_class=SensorDeviceClass.VOLTAGE, native_unit_of_measurement=V,
        state_class=MEASUREMENT, suggested_display_precision=3,
        value_fn=lambda s: _value(s.cell_voltage_max),
        attrs_fn=lambda s: _where(s.cell_voltage_max),
    ),
    StackSensorDescription(
        key="cell_voltage_min", translation_key="cell_voltage_min",
        device_class=SensorDeviceClass.VOLTAGE, native_unit_of_measurement=V,
        state_class=MEASUREMENT, suggested_display_precision=3,
        value_fn=lambda s: _value(s.cell_voltage_min),
        attrs_fn=lambda s: _where(s.cell_voltage_min),
    ),
    StackSensorDescription(
        key="cell_voltage_spread", translation_key="cell_voltage_spread",
        device_class=SensorDeviceClass.VOLTAGE, native_unit_of_measurement=MV,
        state_class=MEASUREMENT, suggested_display_precision=0,
        value_fn=lambda s: s.cell_voltage_spread_mv,
    ),
    StackSensorDescription(
        key="cell_temperature_max", translation_key="cell_temperature_max",
        device_class=SensorDeviceClass.TEMPERATURE, native_unit_of_measurement=C,
        state_class=MEASUREMENT, suggested_display_precision=1,
        value_fn=lambda s: _value(s.cell_temperature_max),
        attrs_fn=lambda s: _where(s.cell_temperature_max),
    ),
    StackSensorDescription(
        key="cell_temperature_min", translation_key="cell_temperature_min",
        device_class=SensorDeviceClass.TEMPERATURE, native_unit_of_measurement=C,
        state_class=MEASUREMENT, suggested_display_precision=1,
        value_fn=lambda s: _value(s.cell_temperature_min),
        attrs_fn=lambda s: _where(s.cell_temperature_min),
    ),
    StackSensorDescription(
        key="module_voltage_max", translation_key="module_voltage_max",
        device_class=SensorDeviceClass.VOLTAGE, native_unit_of_measurement=V,
        state_class=MEASUREMENT, suggested_display_precision=2, entity_category=DIAGNOSTIC,
        value_fn=lambda s: _value(s.module_voltage_max),
        attrs_fn=lambda s: _where(s.module_voltage_max),
    ),
    StackSensorDescription(
        key="module_voltage_min", translation_key="module_voltage_min",
        device_class=SensorDeviceClass.VOLTAGE, native_unit_of_measurement=V,
        state_class=MEASUREMENT, suggested_display_precision=2, entity_category=DIAGNOSTIC,
        value_fn=lambda s: _value(s.module_voltage_min),
        attrs_fn=lambda s: _where(s.module_voltage_min),
    ),
    StackSensorDescription(
        key="module_temperature_max", translation_key="module_temperature_max",
        device_class=SensorDeviceClass.TEMPERATURE, native_unit_of_measurement=C,
        state_class=MEASUREMENT, suggested_display_precision=1, entity_category=DIAGNOSTIC,
        value_fn=lambda s: _value(s.module_temperature_max),
        attrs_fn=lambda s: _where(s.module_temperature_max),
    ),
    StackSensorDescription(
        key="module_temperature_min", translation_key="module_temperature_min",
        device_class=SensorDeviceClass.TEMPERATURE, native_unit_of_measurement=C,
        state_class=MEASUREMENT, suggested_display_precision=1, entity_category=DIAGNOSTIC,
        value_fn=lambda s: _value(s.module_temperature_min),
        attrs_fn=lambda s: _where(s.module_temperature_min),
    ),
    StackSensorDescription(
        key="charge_voltage_limit", translation_key="charge_voltage_limit",
        device_class=SensorDeviceClass.VOLTAGE, native_unit_of_measurement=V,
        state_class=MEASUREMENT, entity_category=DIAGNOSTIC, suggested_display_precision=1,
        value_fn=lambda s: s.charge_voltage_limit,
    ),
    StackSensorDescription(
        key="charge_current_limit", translation_key="charge_current_limit",
        device_class=SensorDeviceClass.CURRENT, native_unit_of_measurement=A,
        state_class=MEASUREMENT, entity_category=DIAGNOSTIC, suggested_display_precision=1,
        value_fn=lambda s: s.charge_current_limit,
    ),
    StackSensorDescription(
        key="discharge_voltage_limit", translation_key="discharge_voltage_limit",
        device_class=SensorDeviceClass.VOLTAGE, native_unit_of_measurement=V,
        state_class=MEASUREMENT, entity_category=DIAGNOSTIC, suggested_display_precision=1,
        value_fn=lambda s: s.discharge_voltage_limit,
    ),
    StackSensorDescription(
        key="discharge_current_limit", translation_key="discharge_current_limit",
        device_class=SensorDeviceClass.CURRENT, native_unit_of_measurement=A,
        state_class=MEASUREMENT, entity_category=DIAGNOSTIC, suggested_display_precision=1,
        value_fn=lambda s: s.discharge_current_limit,
    ),
    StackSensorDescription(
        key="module_count", translation_key="module_count", entity_category=DIAGNOSTIC,
        value_fn=lambda s: s.module_count,
    ),
    StackSensorDescription(
        key="cell_count", translation_key="cell_count", entity_category=DIAGNOSTIC,
        value_fn=lambda s: s.cell_count,
    ),
)


@dataclass(frozen=True, kw_only=True)
class ModuleSensorDescription(SensorEntityDescription):
    value_fn: Callable[[Module], Any]


MODULE_SENSORS: tuple[ModuleSensorDescription, ...] = (
    ModuleSensorDescription(
        key="voltage", translation_key="module_voltage", device_class=SensorDeviceClass.VOLTAGE,
        native_unit_of_measurement=V, state_class=MEASUREMENT, suggested_display_precision=2,
        value_fn=lambda m: m.voltage,
    ),
    ModuleSensorDescription(
        key="temperature", translation_key="module_temperature",
        device_class=SensorDeviceClass.TEMPERATURE, native_unit_of_measurement=C,
        state_class=MEASUREMENT, suggested_display_precision=1, value_fn=lambda m: m.temperature,
    ),
    ModuleSensorDescription(
        key="cell_voltage_max", translation_key="cell_voltage_max",
        device_class=SensorDeviceClass.VOLTAGE, native_unit_of_measurement=V,
        state_class=MEASUREMENT, suggested_display_precision=3,
        value_fn=lambda m: m.cell_voltage_max,
    ),
    ModuleSensorDescription(
        key="cell_voltage_min", translation_key="cell_voltage_min",
        device_class=SensorDeviceClass.VOLTAGE, native_unit_of_measurement=V,
        state_class=MEASUREMENT, suggested_display_precision=3,
        value_fn=lambda m: m.cell_voltage_min,
    ),
    ModuleSensorDescription(
        key="cell_voltage_spread", translation_key="cell_voltage_spread",
        device_class=SensorDeviceClass.VOLTAGE, native_unit_of_measurement=MV,
        state_class=MEASUREMENT, suggested_display_precision=0,
        value_fn=lambda m: m.cell_voltage_spread_mv,
    ),
)


def _module(snapshot: Snapshot | None, number: int) -> Module | None:
    if snapshot is None:
        return None
    for module in snapshot.modules:
        if module.number == number:
            return module
    return None


class StackSensor(PylontechEntity, RestoreSensor):
    entity_description: StackSensorDescription

    def __init__(self, coordinator: PylontechCoordinator,
                 description: StackSensorDescription) -> None:
        super().__init__(coordinator, description.key)
        self.entity_description = description
        self._last_good: float | None = None

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        last = await self.async_get_last_sensor_data() if self.entity_description.guard else None
        if last is not None and isinstance(last.native_value, int | float):
            self._last_good = float(last.native_value)

    def _guarded(self, value: Any) -> Any:
        guard = self.entity_description.guard
        if guard is None or not isinstance(value, int | float):
            return value
        previous = self._last_good
        if previous is not None:
            interval = self.coordinator.update_interval
            hours = (interval.total_seconds() if interval else 60) / 3600
            limit = 1.0 + MAX_KW * hours * (1 + self.coordinator.failures_in_row)
            if value - previous > limit:
                _LOGGER.debug("%s jumped from %s to %s; kept %s", self.entity_id, previous,
                              value, previous)
                return previous
            if guard == "lifetime" and value < previous:
                return previous
        self._last_good = float(value)
        return value

    @property
    def native_value(self) -> Any:
        if self.coordinator.data is None:
            return None
        return self._guarded(self.entity_description.value_fn(self.coordinator.data))

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        fn = self.entity_description.attrs_fn
        if fn is None or self.coordinator.data is None:
            return None
        return fn(self.coordinator.data) or None


class ModuleSensor(PylontechEntity, SensorEntity):
    entity_description: ModuleSensorDescription

    def __init__(self, coordinator: PylontechCoordinator, number: int,
                 description: ModuleSensorDescription) -> None:
        super().__init__(coordinator, description.key, number)
        self.entity_description = description

    @property
    def native_value(self) -> Any:
        module = _module(self.coordinator.data, self.module_number or 0)
        return None if module is None else self.entity_description.value_fn(module)


class CellSensor(PylontechEntity, SensorEntity):
    """One cell's voltage or temperature."""

    _attr_state_class = MEASUREMENT

    def __init__(self, coordinator: PylontechCoordinator, module: int, cell: int,
                 kind: str) -> None:
        super().__init__(coordinator, f"cell_{cell}_{kind}", module)
        self.cell_number = cell
        self.kind = kind
        self._attr_translation_key = f"cell_{kind}"
        self._attr_translation_placeholders = {"cell": str(cell)}
        if kind == "voltage":
            self._attr_device_class = SensorDeviceClass.VOLTAGE
            self._attr_native_unit_of_measurement = V
            self._attr_suggested_display_precision = 3
        else:
            self._attr_device_class = SensorDeviceClass.TEMPERATURE
            self._attr_native_unit_of_measurement = C
            self._attr_suggested_display_precision = 1
            # Several cells share each temperature sensor in a Force module, so
            # the module's own temperature and the stack's coldest and warmest
            # cell say almost all of it; one per cell is there for those who
            # want it.
            self._attr_entity_registry_enabled_default = False

    @property
    def native_value(self) -> float | None:
        module = _module(self.coordinator.data, self.module_number or 0)
        if module is None or self.cell_number > len(module.cells):
            return None
        cell = module.cells[self.cell_number - 1]
        return cell.voltage if self.kind == "voltage" else cell.temperature


_UNIT_CLASSES = {
    "V": (SensorDeviceClass.VOLTAGE, V),
    "mV": (SensorDeviceClass.VOLTAGE, MV),
    "A": (SensorDeviceClass.CURRENT, A),
    "W": (SensorDeviceClass.POWER, UnitOfPower.WATT),
    "kW": (SensorDeviceClass.POWER, UnitOfPower.KILO_WATT),
    "kWh": (SensorDeviceClass.ENERGY, KWH),
    "Wh": (SensorDeviceClass.ENERGY, UnitOfEnergy.WATT_HOUR),
    "℃": (SensorDeviceClass.TEMPERATURE, C),
    "°C": (SensorDeviceClass.TEMPERATURE, C),
    "%": (None, PERCENTAGE),
}


def _as_number(value: Any) -> float | None:
    try:
        return float(str(value).strip())
    except (TypeError, ValueError):
        return None


class ExtraSensor(PylontechEntity, SensorEntity):
    """A value the cloud sends under a name of Solarman's choosing."""

    _attr_entity_category = DIAGNOSTIC

    def __init__(self, coordinator: PylontechCoordinator, key: str, name: str,
                 unit: str | None, numeric: bool) -> None:
        super().__init__(coordinator, f"cloud_{key}")
        self.key = key
        self._attr_name = name
        self.numeric = numeric
        if numeric and unit in _UNIT_CLASSES:
            device_class, native = _UNIT_CLASSES[unit]
            self._attr_device_class = device_class
            self._attr_native_unit_of_measurement = native
        elif numeric and unit:
            self._attr_native_unit_of_measurement = unit
        if numeric and self._attr_device_class != SensorDeviceClass.ENERGY:
            self._attr_state_class = MEASUREMENT

    @property
    def native_value(self) -> Any:
        data = self.coordinator.data
        extra = data.extras.get(self.key) if data else None
        if extra is None:
            return None
        return _as_number(extra.value) if self.numeric else str(extra.value)[:255]


async def async_setup_entry(hass: HomeAssistant, entry: PylontechConfigEntry,
                            async_add_entities: AddConfigEntryEntitiesCallback) -> None:
    coordinator = entry.runtime_data
    known: set[str] = set()
    if not coordinator.cell_data and not coordinator.is_cloud:
        # Cell data switched off in the options: the cells' entities go, rather
        # than staying on as unknown.
        registry = er.async_get(hass)
        for item in er.async_entries_for_config_entry(registry, entry.entry_id):
            if item.domain == "sensor" and (
                CELL_UNIQUE_ID.search(item.unique_id) or FROM_CELLS_UNIQUE_ID.search(item.unique_id)
            ):
                registry.async_remove(item.entity_id)

    @callback
    def add_new() -> None:
        snapshot = coordinator.data
        if snapshot is None:
            return
        new: list[SensorEntity] = []

        def want(key: str) -> bool:
            if key in known:
                return False
            known.add(key)
            return True

        for description in STACK_SENSORS:
            if description.value_fn(snapshot) is not None and want(f"stack:{description.key}"):
                new.append(StackSensor(coordinator, description))
        for module in snapshot.modules:
            for description in MODULE_SENSORS:
                if description.value_fn(module) is not None and want(
                    f"m{module.number}:{description.key}"
                ):
                    new.append(ModuleSensor(coordinator, module.number, description))
            for cell in module.cells:
                if cell.voltage is not None and want(f"m{module.number}:c{cell.number}:v"):
                    new.append(CellSensor(coordinator, module.number, cell.number, "voltage"))
                if cell.temperature is not None and want(f"m{module.number}:c{cell.number}:t"):
                    new.append(CellSensor(coordinator, module.number, cell.number, "temperature"))
        for key, extra in snapshot.extras.items():
            if want(f"extra:{key}"):
                numeric = _as_number(extra.value) is not None
                new.append(ExtraSensor(coordinator, key, extra.name, extra.unit, numeric))
        if new:
            async_add_entities(new)

    add_new()
    entry.async_on_unload(coordinator.async_add_listener(add_new))
