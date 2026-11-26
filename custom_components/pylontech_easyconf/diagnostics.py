"""Diagnostics: what was read, how, and what went wrong last.

Both summary blocks are read as the file is made (0x1100 and 0x1400, 64 words
each), though a poll reads only one: on a single tower they hold the same
values, and on the master of several towers in parallel one is the tower's own
and the other the whole system's, which is what somebody looking at such a
system needs to see side by side. Neither holds a serial number.
"""

from __future__ import annotations

from dataclasses import asdict
from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.const import CONF_HOST
from homeassistant.core import HomeAssistant

from .const import (
    CONF_ACCOUNT,
    CONF_APP_ID,
    CONF_APP_SECRET,
    CONF_DEVICE_SN,
    CONF_LOGGER_SERIAL,
    CONF_MAC,
    CONF_ORG_ID,
    CONF_PASSWORD_SHA256,
)
from .coordinator import PylontechConfigEntry, PylontechCoordinator
from .modbus import ModbusError
from .registers import SUMMARY_COUNT, SUMMARY_STARTS
from .transport import TransportError

REDACTED = "**REDACTED**"

TO_REDACT = {
    CONF_HOST,
    CONF_LOGGER_SERIAL,
    CONF_MAC,
    CONF_APP_ID,
    CONF_APP_SECRET,
    CONF_ACCOUNT,
    CONF_PASSWORD_SHA256,
    CONF_ORG_ID,
    CONF_DEVICE_SN,
    "serial",
}


def _without(text: Any, host: str | None) -> Any:
    """An error text without the battery's address, which a failed connection
    names."""
    return text.replace(host, REDACTED) if host and isinstance(text, str) else text


async def _summary_blocks(coordinator: PylontechCoordinator, host: str | None) -> dict[str, Any]:
    """Both summary blocks as the BMS has them now, or why one was not read."""
    blocks: dict[str, Any] = {}
    if coordinator.transport is None:
        return blocks
    for start in SUMMARY_STARTS:
        try:
            blocks[hex(start)] = await coordinator.transport.read_registers(start, SUMMARY_COUNT)
        except (TransportError, ModbusError) as err:
            blocks[hex(start)] = _without(f"not read: {err}", host)
    return blocks


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: PylontechConfigEntry
) -> dict[str, Any]:
    coordinator = entry.runtime_data
    data = coordinator.data
    host = entry.data.get(CONF_HOST)
    connection = coordinator.describe()
    connection["last_error"] = _without(connection["last_error"], host)
    if connection["transport"]:
        connection["transport"]["last_error"] = _without(
            connection["transport"]["last_error"], host
        )
    return {
        "entry": {
            "data": async_redact_data(dict(entry.data), TO_REDACT),
            "options": dict(entry.options),
        },
        "identity": async_redact_data(asdict(coordinator.identity), TO_REDACT),
        "connection": connection,
        "summary_blocks": await _summary_blocks(coordinator, host),
        "reading": None if data is None else {
            **asdict(data),
            "power": data.power,
            "cell_voltage_spread_mv": data.cell_voltage_spread_mv,
            "cells_per_module": data.cells_per_module,
        },
    }
