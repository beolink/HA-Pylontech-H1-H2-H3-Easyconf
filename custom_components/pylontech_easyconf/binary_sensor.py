"""The battery's fully-charged flag."""

from __future__ import annotations

from homeassistant.components.binary_sensor import BinarySensorEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .coordinator import PylontechConfigEntry, PylontechCoordinator
from .entity import PylontechEntity

PARALLEL_UPDATES = 0


class FullyChargedSensor(PylontechEntity, BinarySensorEntity):
    """On while the BMS reports the stack fully charged (0x1138)."""

    _attr_translation_key = "fully_charged"

    def __init__(self, coordinator: PylontechCoordinator) -> None:
        super().__init__(coordinator, "fully_charged")

    @property
    def is_on(self) -> bool | None:
        data = self.coordinator.data
        return None if data is None else data.fully_charged


async def async_setup_entry(hass: HomeAssistant, entry: PylontechConfigEntry,
                            async_add_entities: AddConfigEntryEntitiesCallback) -> None:
    coordinator = entry.runtime_data
    if coordinator.data is not None and coordinator.data.fully_charged is not None:
        async_add_entities([FullyChargedSensor(coordinator)])
