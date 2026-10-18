"""Pylontech Easyconf: every value a Pylontech Force H1, H2 or H3 BMS has.

Read locally through the battery's own Wi-Fi or LAN module (Solarman V5 on
port 8899, or Modbus TCP), through a converter on its RS485 port, or, when
none of that can be reached, through the Solarman cloud. Read only: nothing
in the integration writes to the battery.
"""

from __future__ import annotations

import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
from homeassistant.loader import async_get_integration

from .const import CONF_CELL_DATA, CONF_SOURCE, CONF_TRANSPORT, DOMAIN, SOURCE_CLOUD
from .coordinator import PylontechConfigEntry, PylontechCoordinator, entry_config
from .entity import stack_device
from .stats import async_setup_stats, async_stop_stats
from .stats_extra import FailureCounter, build_extra

_LOGGER = logging.getLogger(__name__)

PLATFORMS: list[Platform] = [Platform.SENSOR, Platform.BINARY_SENSOR]

_FAILURES: dict[str, FailureCounter] = {}


def _stats_extra_for(entry: ConfigEntry) -> dict:
    """The integration's part of the anonymous daily report.

    Resolved when the report is built, not when it is armed, so a set-up that
    did not finish (the battery away) still reports the integration as
    installed. Reads what the coordinator already has and never the battery.
    What goes in it: stats_extra.py, and why: https://stats.rnet.se/integritet
    """
    config = entry_config(entry)
    cloud = config.get(CONF_SOURCE) == SOURCE_CLOUD
    transport = SOURCE_CLOUD if cloud else config.get(CONF_TRANSPORT)
    coordinator = getattr(entry, "runtime_data", None)
    if not isinstance(coordinator, PylontechCoordinator):
        coordinator = None
    failures = _FAILURES.setdefault(entry.entry_id, FailureCounter())
    data = coordinator.data if coordinator else None
    identity = coordinator.identity if coordinator else None
    return build_extra(
        model=identity.model if identity else None,
        transport=transport,
        modules=data.module_count if data else None,
        cells_per_module=data.cells_per_module if data else None,
        cell_data=bool(config.get(CONF_CELL_DATA, True)) and not cloud,
        firmware=identity.firmware if identity else None,
        failures=failures.delta(coordinator.failures_total if coordinator else 0),
    )


async def async_setup_entry(hass: HomeAssistant, entry: PylontechConfigEntry) -> bool:
    # Armed before anything that can raise, and stopped only from
    # async_unload_entry: Home Assistant runs an entry's on-unload callbacks
    # after every failed set-up attempt, so a reporter tied to them goes quiet
    # exactly while the battery is away.
    try:
        integration = await async_get_integration(hass, DOMAIN)
        await async_setup_stats(
            hass, entry, DOMAIN, str(integration.version),
            extra=lambda: _stats_extra_for(entry),
        )
    except Exception:
        _LOGGER.debug("Could not arm the statistics reporter", exc_info=True)

    coordinator = PylontechCoordinator(hass, entry)
    try:
        await coordinator.async_config_entry_first_refresh()
    except Exception:
        await coordinator.async_shutdown()
        raise
    entry.runtime_data = coordinator
    # The stack's device first, so the modules' devices can name it as the one
    # they sit under.
    device = dr.async_get(hass).async_get_or_create(
        config_entry_id=entry.entry_id, **stack_device(coordinator)
    )
    coordinator.stack_device_id = device.id
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: PylontechConfigEntry) -> bool:
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        await entry.runtime_data.async_shutdown()
        # Only here, never from an on-unload callback: those also run when a
        # set-up attempt fails, and the report has to survive that.
        await async_stop_stats(hass, entry, DOMAIN)
    return unload_ok
