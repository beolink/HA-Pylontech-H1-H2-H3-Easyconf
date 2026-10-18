"""Polls the battery, locally or through the cloud, for every entity."""

from __future__ import annotations

from datetime import datetime, timedelta
import logging
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_HOST, CONF_PORT
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util

from . import reader
from .cloud import CloudAuthError, CloudError, SolarmanCloud, snapshot_from_current
from .const import (
    CONF_ACCOUNT,
    CONF_APP_ID,
    CONF_APP_SECRET,
    CONF_CELL_DATA,
    CONF_DEVICE_SN,
    CONF_LOGGER_SERIAL,
    CONF_MODEL,
    CONF_ORG_ID,
    CONF_PASSWORD_SHA256,
    CONF_SCAN_INTERVAL,
    CONF_SLAVE,
    CONF_SOURCE,
    CONF_TRANSPORT,
    DEFAULT_CLOUD_INTERVAL,
    DEFAULT_LOCAL_INTERVAL,
    DEFAULT_SLAVE,
    DOMAIN,
    FAILURES_BEFORE_UNAVAILABLE,
    IDENTITY_REFRESH,
    SOURCE_CLOUD,
)
from .modbus import ModbusError
from .model import Identity, Snapshot
from .registers import DecodeError
from .transport import Transport, TransportError, make_transport

_LOGGER = logging.getLogger(__name__)

type PylontechConfigEntry = ConfigEntry[PylontechCoordinator]


def entry_config(entry: ConfigEntry) -> dict[str, Any]:
    return {**entry.data, **entry.options}


class PylontechCoordinator(DataUpdateCoordinator[Snapshot]):
    """One poll of the stack per interval, a whole reading or the last one."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        config = entry_config(entry)
        self.source = config.get(CONF_SOURCE)
        self.is_cloud = self.source == SOURCE_CLOUD
        default = DEFAULT_CLOUD_INTERVAL if self.is_cloud else DEFAULT_LOCAL_INTERVAL
        interval = int(config.get(CONF_SCAN_INTERVAL, default))
        super().__init__(
            hass,
            _LOGGER,
            config_entry=entry,
            name=f"{DOMAIN} {entry.title}",
            update_interval=timedelta(seconds=interval),
        )
        self.cell_data = bool(config.get(CONF_CELL_DATA, True))
        self.identity = Identity()
        self._identity_read: datetime | None = None
        self.failures_in_row = 0
        self.failures_total = 0
        self.last_error: str | None = None
        self.last_success: datetime | None = None
        self._summary_start: int | None = None
        self.transport: Transport | None = None
        self.cloud: SolarmanCloud | None = None
        #: The stack's device, which the modules' devices sit under.
        self.stack_device_id: str | None = None
        if self.is_cloud:
            self.cloud = SolarmanCloud(
                async_get_clientsession(hass),
                config[CONF_APP_ID],
                config[CONF_APP_SECRET],
                config[CONF_ACCOUNT],
                config[CONF_PASSWORD_SHA256],
                config.get(CONF_ORG_ID),
            )
            self.identity = Identity(
                brand="Pylontech",
                model=config.get(CONF_MODEL),
                serial=config.get(CONF_DEVICE_SN),
            )
        else:
            self.transport = make_transport(
                config[CONF_TRANSPORT],
                config[CONF_HOST],
                config.get(CONF_PORT),
                int(config.get(CONF_SLAVE, DEFAULT_SLAVE)),
                int(config.get(CONF_LOGGER_SERIAL) or 0),
                on_serial=self._learned_serial,
            )

    @callback
    def _learned_serial(self, serial: int) -> None:
        """Keep a logger serial the transport learned, for the next start."""
        entry = self.config_entry
        if entry is None or entry.data.get(CONF_LOGGER_SERIAL) == serial:
            return
        _LOGGER.info("The logger at %s has serial number %s", entry.data.get(CONF_HOST), serial)
        self.hass.config_entries.async_update_entry(
            entry, data={**entry.data, CONF_LOGGER_SERIAL: serial}
        )

    async def _async_setup(self) -> None:
        if self.transport is not None:
            await self._read_identity(required=True)

    async def _read_identity(self, required: bool) -> None:
        assert self.transport is not None
        try:
            self.identity = await reader.read_identity(self.transport)
            self._identity_read = dt_util.utcnow()
        except (TransportError, ModbusError, DecodeError) as err:
            if required:
                raise UpdateFailed(f"Could not read the battery's identity: {err}") from err
            _LOGGER.debug("Identity not read again: %s", err)

    async def _read(self) -> Snapshot:
        if self.cloud is not None:
            data = await self.cloud.current(self.identity.serial or "")
            return snapshot_from_current(data)
        assert self.transport is not None
        if self._identity_read is None or dt_util.utcnow() - self._identity_read > IDENTITY_REFRESH:
            await self._read_identity(required=False)
        reading = await reader.read_snapshot(self.transport, self._summary_start, self.cell_data)
        self._summary_start = reading.summary_start
        return reading.snapshot

    async def _async_update_data(self) -> Snapshot:
        try:
            snapshot = await self._read()
        except CloudAuthError as err:
            raise ConfigEntryAuthFailed(str(err)) from err
        except (TransportError, ModbusError, DecodeError, CloudError) as err:
            self.failures_in_row += 1
            self.failures_total += 1
            self.last_error = str(err)
            if self.data is not None and self.failures_in_row < FAILURES_BEFORE_UNAVAILABLE:
                _LOGGER.debug("Poll %s in a row failed, keeping the last reading: %s",
                              self.failures_in_row, err)
                return self.data
            raise UpdateFailed(str(err)) from err
        if self.failures_in_row >= FAILURES_BEFORE_UNAVAILABLE:
            _LOGGER.info("The battery answers again after %s failed polls", self.failures_in_row)
        self.failures_in_row = 0
        self.last_success = dt_util.utcnow()
        return snapshot

    async def async_shutdown(self) -> None:
        await super().async_shutdown()
        if self.transport is not None:
            await self.transport.close()

    def describe(self) -> dict[str, Any]:
        """The connection's state, for the diagnostics."""
        return {
            "source": self.source,
            "update_interval_s": (
                self.update_interval.total_seconds() if self.update_interval else None
            ),
            "cell_data": self.cell_data,
            "summary_start": hex(self._summary_start) if self._summary_start else None,
            "failures_in_row": self.failures_in_row,
            "failures_total": self.failures_total,
            "last_error": self.last_error,
            "last_success": self.last_success.isoformat() if self.last_success else None,
            "transport": self.transport.describe() if self.transport else None,
            "cloud_calls": self.cloud.calls if self.cloud else None,
        }
