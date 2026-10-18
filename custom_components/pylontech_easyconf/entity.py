"""The devices and the base entity.

A stack is one device, named after its family ("Pylontech Force H2"), and
every module in it is a device of its own under the stack, holding the
module's voltage and temperature and its cells. Modules are numbered from 1 in
the order the BMS lists them, cells from 1 within their module.
"""

from __future__ import annotations

from homeassistant.helpers.device_registry import CONNECTION_NETWORK_MAC, DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import CONF_MAC, DOMAIN, MANUFACTURER
from .coordinator import PylontechCoordinator

#: Home Assistant 2026.8 links a device to the one it sits under by that
#: device's id, and deprecates the identifier tuple it took before; the
#: releases before it know only the tuple.
VIA_DEVICE_ID = "via_device_id" in (DeviceInfo.__required_keys__ | DeviceInfo.__optional_keys__)


def base_id(coordinator: PylontechCoordinator) -> str:
    entry = coordinator.config_entry
    assert entry is not None
    return entry.unique_id or entry.entry_id


def stack_device(coordinator: PylontechCoordinator) -> DeviceInfo:
    identity = coordinator.identity
    entry = coordinator.config_entry
    assert entry is not None
    model = identity.model or "Force"
    info = DeviceInfo(
        identifiers={(DOMAIN, base_id(coordinator))},
        manufacturer=MANUFACTURER,
        name=f"{MANUFACTURER} {model}",
        model=model,
        sw_version=identity.firmware,
        serial_number=identity.serial,
    )
    if mac := entry.data.get(CONF_MAC):
        info["connections"] = {(CONNECTION_NETWORK_MAC, mac)}
    return info


def module_device(coordinator: PylontechCoordinator, number: int) -> DeviceInfo:
    model = coordinator.identity.model or "Force"
    info = DeviceInfo(
        identifiers={(DOMAIN, f"{base_id(coordinator)}_module_{number}")},
        manufacturer=MANUFACTURER,
        translation_key="module",
        translation_placeholders={"model": model, "number": str(number)},
        model=f"{model} module",
    )
    if VIA_DEVICE_ID and coordinator.stack_device_id:
        info["via_device_id"] = coordinator.stack_device_id
    else:
        info["via_device"] = (DOMAIN, base_id(coordinator))  # type: ignore[typeddict-unknown-key]
    return info


class PylontechEntity(CoordinatorEntity[PylontechCoordinator]):
    """An entity of a stack, or of one of its modules."""

    _attr_has_entity_name = True

    def __init__(self, coordinator: PylontechCoordinator, key: str,
                 module: int | None = None) -> None:
        super().__init__(coordinator)
        self.module_number = module
        prefix = base_id(coordinator) if module is None else f"{base_id(coordinator)}_m{module}"
        self._attr_unique_id = f"{prefix}_{key}"
        self._attr_device_info = (
            stack_device(coordinator) if module is None else module_device(coordinator, module)
        )
