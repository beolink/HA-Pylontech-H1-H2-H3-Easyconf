"""Diagnostics: what was read, how, and what went wrong last."""

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
from .coordinator import PylontechConfigEntry

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


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: PylontechConfigEntry
) -> dict[str, Any]:
    coordinator = entry.runtime_data
    data = coordinator.data
    return {
        "entry": {
            "data": async_redact_data(dict(entry.data), TO_REDACT),
            "options": dict(entry.options),
        },
        "identity": async_redact_data(asdict(coordinator.identity), TO_REDACT),
        "connection": coordinator.describe(),
        "reading": None if data is None else {
            **asdict(data),
            "power": data.power,
            "cell_voltage_spread_mv": data.cell_voltage_spread_mv,
            "cells_per_module": data.cells_per_module,
        },
    }
