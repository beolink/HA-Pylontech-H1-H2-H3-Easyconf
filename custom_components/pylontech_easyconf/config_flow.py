"""Setting up a battery: found on the network, typed in, or via the cloud.

The first choice is the easy one: the integration asks every Solarman logger
on the networks Home Assistant is on who it is, looks on the same networks for
anything that takes a connection on Modbus's ports 8899 and 502 (a Modbus TCP
gateway does not answer the loggers' greeting), asks each whether a Pylontech
BMS is behind it, and offers the batteries it found by name, with no address,
no port and no serial number to type. A module that Home Assistant sees
coming onto the network (DHCP) is asked the same and offered on its own.
Typing an address is the second way, for a battery on another network, an
RS485 converter, or a logger that does not answer the search; the protocol
is found by trying. The Solarman cloud is the third, for when the battery's
logger cannot be reached from Home Assistant at all.
"""

from __future__ import annotations

import asyncio
from collections import defaultdict
import logging
from typing import Any

from homeassistant.config_entries import (
    ConfigEntry,
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlowWithReload,
)
from homeassistant.const import CONF_HOST, CONF_PORT
from homeassistant.core import callback
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.device_registry import format_mac
from homeassistant.helpers.selector import (
    NumberSelector,
    NumberSelectorConfig,
    NumberSelectorMode,
    SelectOptionDict,
    SelectSelector,
    SelectSelectorConfig,
    SelectSelectorMode,
    TextSelector,
    TextSelectorConfig,
    TextSelectorType,
)
from homeassistant.helpers.service_info.dhcp import DhcpServiceInfo
import voluptuous as vol

from . import discovery, reader
from .cloud import CloudAuthError, CloudError, SolarmanCloud, hash_password
from .const import (
    CLOUD_PLACEHOLDERS,
    CONF_ACCOUNT,
    CONF_APP_ID,
    CONF_APP_SECRET,
    CONF_CELL_DATA,
    CONF_DEVICE_SN,
    CONF_LOGGER_SERIAL,
    CONF_MAC,
    CONF_MODEL,
    CONF_ORG_ID,
    CONF_PASSWORD,
    CONF_PASSWORD_SHA256,
    CONF_SCAN_INTERVAL,
    CONF_SEND_STATISTICS,
    CONF_SLAVE,
    CONF_SOURCE,
    CONF_STATION_NAME,
    CONF_TRANSPORT,
    DEFAULT_CLOUD_INTERVAL,
    DEFAULT_LOCAL_INTERVAL,
    DEFAULT_SLAVE,
    DOMAIN,
    MAX_CLOUD_INTERVAL,
    MAX_LOCAL_INTERVAL,
    MIN_CLOUD_INTERVAL,
    MIN_LOCAL_INTERVAL,
    SOURCE_CLOUD,
    SOURCE_LOCAL,
    STATS_PLACEHOLDERS,
)
from .reader import AUTO, ProbeError, ProbeResult
from .registers import model_name
from .transport import KINDS, MODBUS_TCP, SOLARMAN_V5

_LOGGER = logging.getLogger(__name__)

PROBE_TIMEOUT = 4.0
MAX_PROBED = 32


def _unique_id(result: ProbeResult, host: str, port: int) -> str:
    if result.identity.serial:
        return result.identity.serial
    if result.serial:
        return f"logger-{result.serial}"
    return f"{host}:{port}"


def _title(model: str | None, suffix: str = "") -> str:
    return f"Pylontech {model or 'Force'}{suffix}"


def _local_data(result: ProbeResult, host: str, slave: int, mac: str | None = None) -> dict:
    data: dict[str, Any] = {
        CONF_SOURCE: SOURCE_LOCAL,
        CONF_HOST: host,
        CONF_PORT: result.port,
        CONF_TRANSPORT: result.kind,
        CONF_SLAVE: slave,
    }
    if result.serial:
        data[CONF_LOGGER_SERIAL] = result.serial
    if mac:
        data[CONF_MAC] = mac
    return data


def _stats_field(default: bool = True) -> dict:
    return {vol.Optional(CONF_SEND_STATISTICS, default=default): bool}


def _number(minimum: int, maximum: int, step: int = 1, unit: str | None = None) -> NumberSelector:
    config = NumberSelectorConfig(min=minimum, max=maximum, step=step,
                                  mode=NumberSelectorMode.BOX)
    if unit:
        config["unit_of_measurement"] = unit
    return NumberSelector(config)


def _manual_schema(current: dict[str, Any], with_stats: bool = True) -> vol.Schema:
    fields: dict[Any, Any] = {
        vol.Required(CONF_HOST, default=current.get(CONF_HOST, "")): str,
        vol.Required(CONF_PORT, default=current.get(CONF_PORT, 8899)): _number(1, 65535),
        vol.Required(CONF_TRANSPORT, default=current.get(CONF_TRANSPORT, AUTO)): SelectSelector(
            SelectSelectorConfig(options=[AUTO, *KINDS], translation_key="transport",
                                 mode=SelectSelectorMode.DROPDOWN)
        ),
        vol.Optional(
            CONF_LOGGER_SERIAL,
            description={"suggested_value": str(current.get(CONF_LOGGER_SERIAL) or "")},
        ): str,
        vol.Required(CONF_SLAVE, default=current.get(CONF_SLAVE, DEFAULT_SLAVE)): _number(1, 247),
    }
    if with_stats:
        fields.update(_stats_field())
    return vol.Schema(fields)


def _password() -> TextSelector:
    return TextSelector(TextSelectorConfig(type=TextSelectorType.PASSWORD))


async def _local_networks(hass) -> list[tuple[str, int]]:
    """(address, prefix) of every network Home Assistant's enabled adapters are on."""
    from homeassistant.components import network

    networks: list[tuple[str, int]] = []
    for adapter in await network.async_get_adapters(hass):
        if not adapter.get("enabled"):
            continue
        for ip in adapter.get("ipv4") or []:
            networks.append((ip["address"], ip["network_prefix"]))
    return networks


async def _broadcast_targets(hass) -> list[str]:
    """The broadcast address of every network Home Assistant is on."""
    return discovery.broadcast_addresses(await _local_networks(hass))


async def _scan_hosts(hass) -> list[str]:
    """Every other address of the networks Home Assistant is on."""
    return discovery.scan_hosts(await _local_networks(hass))


def _found_label(result: ProbeResult, found: discovery.FoundLogger) -> str:
    where = f"{found.ip}:{result.port}" if result.kind != SOLARMAN_V5 else found.ip
    via = f"logger {found.serial}" if found.serial else result.kind.replace("_", " ")
    return f"{_title(result.identity.model)}, {where} ({via})"


class PylontechConfigFlow(ConfigFlow, domain=DOMAIN):
    VERSION = 1

    def __init__(self) -> None:
        self._found: list[tuple[ProbeResult, discovery.FoundLogger]] = []
        self._loggers_seen = 0
        self._gateways_seen = 0
        self._candidate: tuple[ProbeResult, str, str | None] | None = None
        self._cloud: dict[str, Any] = {}
        self._batteries: list[dict] = []

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> PylontechOptionsFlow:
        return PylontechOptionsFlow()

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        return self.async_show_menu(step_id="user", menu_options=["discover", "manual", "cloud"])

    # The network search.

    async def async_step_discover(self, user_input: dict[str, Any] | None = None
                                  ) -> ConfigFlowResult:
        targets, hosts = await asyncio.gather(_broadcast_targets(self.hass),
                                              _scan_hosts(self.hass))
        loggers, open_ports = await asyncio.gather(discovery.scan(targets),
                                                   discovery.tcp_scan(hosts))
        configured = {(e.data.get(CONF_HOST), e.data.get(CONF_PORT))
                      for e in self._async_current_entries()}
        # Who to ask, and how: a logger that answered the greeting in its own
        # protocol first, then as plain Modbus TCP (a logger switched to it);
        # anything else that took a connection as Modbus TCP first.
        ask_list: dict[str, tuple[list[tuple[str, int]], discovery.FoundLogger]] = {}
        for logger in loggers:
            if (logger.ip, 8899) not in configured:
                ask_list[logger.ip] = ([(SOLARMAN_V5, 8899), (MODBUS_TCP, 8899)], logger)
        ports_by_host: dict[str, set[int]] = defaultdict(set)
        for host, port in open_ports:
            if host not in ask_list and (host, port) not in configured:
                ports_by_host[host].add(port)
        for host, ports in ports_by_host.items():
            order = [(MODBUS_TCP, port) for port in discovery.SCAN_PORTS if port in ports]
            if 8899 in ports and host not in {lg.ip for lg in loggers}:
                order.append((SOLARMAN_V5, 8899))
            ask_list[host] = (order, discovery.FoundLogger(host, "", 0))
        self._loggers_seen = len(loggers)
        self._gateways_seen = len(ports_by_host)

        async def ask(order: list[tuple[str, int]], found: discovery.FoundLogger):
            try:
                return await reader.probe(found.ip, serial=found.serial, timeout=PROBE_TIMEOUT,
                                          order=order), found
            except ProbeError as err:
                _LOGGER.debug("No Pylontech at %s: %s", found.ip, err)
                return None

        answers = await asyncio.gather(
            *(ask(order, found) for order, found in list(ask_list.values())[:MAX_PROBED])
        )
        self._found = [a for a in answers if a is not None]
        if not self._found:
            return await self.async_step_discover_none()
        return await self.async_step_pick()

    async def async_step_discover_none(self, user_input: dict[str, Any] | None = None
                                       ) -> ConfigFlowResult:
        if user_input is not None:
            return await self.async_step_manual()
        return self.async_show_form(
            step_id="discover_none",
            data_schema=vol.Schema({}),
            description_placeholders={"loggers": str(self._loggers_seen),
                                      "gateways": str(self._gateways_seen)},
        )

    async def async_step_pick(self, user_input: dict[str, Any] | None = None
                              ) -> ConfigFlowResult:
        if user_input is not None:
            result, found = self._found[int(user_input["battery"])]
            # Not stopped by a discovery of the same battery waiting in the
            # list: the owner chose this way, and Home Assistant closes the
            # discovery once this entry is made.
            await self.async_set_unique_id(
                _unique_id(result, found.ip, result.port), raise_on_progress=False
            )
            self._abort_if_unique_id_configured(updates={CONF_HOST: found.ip})
            return self.async_create_entry(
                title=_title(result.identity.model),
                data=_local_data(result, found.ip, DEFAULT_SLAVE,
                                 format_mac(found.mac) if found.mac else None),
                options={CONF_SEND_STATISTICS: user_input.get(CONF_SEND_STATISTICS, True)},
            )
        options = [
            SelectOptionDict(value=str(index), label=_found_label(result, found))
            for index, (result, found) in enumerate(self._found)
        ]
        return self.async_show_form(
            step_id="pick",
            data_schema=vol.Schema({
                vol.Required("battery", default="0"): SelectSelector(
                    SelectSelectorConfig(options=options, mode=SelectSelectorMode.LIST)
                ),
                **_stats_field(),
            }),
            description_placeholders={"count": str(len(self._found)), **STATS_PLACEHOLDERS},
        )

    # An address typed in.

    async def _probe_form(
        self, user_input: dict[str, Any]
    ) -> tuple[ProbeResult | None, str | None]:
        serial_text = str(user_input.get(CONF_LOGGER_SERIAL) or "").strip()
        if serial_text and not serial_text.isdigit():
            return None, "invalid_serial"
        try:
            result = await reader.probe(
                user_input[CONF_HOST].strip(),
                int(user_input[CONF_PORT]),
                user_input[CONF_TRANSPORT],
                int(serial_text or 0),
                int(user_input[CONF_SLAVE]),
                timeout=PROBE_TIMEOUT,
            )
        except ProbeError as err:
            _LOGGER.debug("Probe of %s failed: %s", user_input[CONF_HOST], err)
            return None, err.reason
        return result, None

    async def async_step_manual(self, user_input: dict[str, Any] | None = None
                                ) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            result, error = await self._probe_form(user_input)
            if result is not None:
                host = user_input[CONF_HOST].strip()
                await self.async_set_unique_id(
                    _unique_id(result, host, result.port), raise_on_progress=False
                )
                self._abort_if_unique_id_configured(updates={CONF_HOST: host})
                return self.async_create_entry(
                    title=_title(result.identity.model),
                    data=_local_data(result, host, int(user_input[CONF_SLAVE])),
                    options={CONF_SEND_STATISTICS: user_input.get(CONF_SEND_STATISTICS, True)},
                )
            errors["base"] = error or "cannot_connect"
        return self.async_show_form(
            step_id="manual",
            data_schema=self.add_suggested_values_to_schema(
                _manual_schema({}), user_input or {}
            ),
            errors=errors,
            description_placeholders=STATS_PLACEHOLDERS,
        )

    # A logger Home Assistant saw on the network.

    async def async_step_dhcp(self, discovery_info: DhcpServiceInfo) -> ConfigFlowResult:
        ip = discovery_info.ip
        mac = format_mac(discovery_info.macaddress)
        for entry in self._async_current_entries(include_ignore=False):
            if entry.data.get(CONF_MAC) == mac:
                if entry.data.get(CONF_HOST) != ip:
                    self.hass.config_entries.async_update_entry(
                        entry, data={**entry.data, CONF_HOST: ip}
                    )
                    self.hass.config_entries.async_schedule_reload(entry.entry_id)
                return self.async_abort(reason="already_configured")
        # A Solarman logger in its own protocol first, then Modbus TCP on 502
        # and 8899, where a Modbus TCP gateway such as an Elfin module answers.
        try:
            result = await reader.probe(ip, 8899, AUTO, timeout=PROBE_TIMEOUT)
        except ProbeError:
            return self.async_abort(reason="not_pylontech")
        await self.async_set_unique_id(_unique_id(result, ip, result.port))
        self._abort_if_unique_id_configured(updates={CONF_HOST: ip, CONF_MAC: mac})
        self._candidate = (result, ip, mac)
        self.context["title_placeholders"] = {"name": _title(result.identity.model)}
        return await self.async_step_dhcp_confirm()

    async def async_step_dhcp_confirm(self, user_input: dict[str, Any] | None = None
                                      ) -> ConfigFlowResult:
        assert self._candidate is not None
        result, ip, mac = self._candidate
        if user_input is not None:
            return self.async_create_entry(
                title=_title(result.identity.model),
                data=_local_data(result, ip, DEFAULT_SLAVE, mac),
                options={CONF_SEND_STATISTICS: user_input.get(CONF_SEND_STATISTICS, True)},
            )
        self._set_confirm_only()
        return self.async_show_form(
            step_id="dhcp_confirm",
            data_schema=vol.Schema(_stats_field()),
            description_placeholders={
                "name": _title(result.identity.model),
                "host": ip,
                **STATS_PLACEHOLDERS,
            },
        )

    # The Solarman cloud.

    def _cloud_client(self, data: dict[str, Any]) -> SolarmanCloud:
        return SolarmanCloud(
            async_get_clientsession(self.hass),
            data[CONF_APP_ID],
            data[CONF_APP_SECRET],
            data[CONF_ACCOUNT],
            data[CONF_PASSWORD_SHA256],
            data.get(CONF_ORG_ID),
        )

    async def async_step_cloud(self, user_input: dict[str, Any] | None = None
                               ) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            self._cloud = {
                CONF_APP_ID: user_input[CONF_APP_ID].strip(),
                CONF_APP_SECRET: user_input[CONF_APP_SECRET].strip(),
                CONF_ACCOUNT: user_input[CONF_ACCOUNT].strip(),
                CONF_PASSWORD_SHA256: hash_password(user_input[CONF_PASSWORD]),
                CONF_ORG_ID: (user_input.get(CONF_ORG_ID) or "").strip() or None,
                CONF_SEND_STATISTICS: user_input.get(CONF_SEND_STATISTICS, True),
            }
            try:
                self._batteries = await self._cloud_client(self._cloud).batteries()
            except CloudAuthError:
                errors["base"] = "invalid_auth"
            except CloudError as err:
                _LOGGER.debug("Solarman cloud: %s", err)
                errors["base"] = "cloud_unreachable"
            else:
                if not self._batteries:
                    errors["base"] = "no_cloud_battery"
                elif len(self._batteries) == 1:
                    return await self._create_cloud_entry(self._batteries[0])
                else:
                    return await self.async_step_cloud_pick()
        schema = vol.Schema({
            vol.Required(CONF_APP_ID): str,
            vol.Required(CONF_APP_SECRET): _password(),
            vol.Required(CONF_ACCOUNT): str,
            vol.Required(CONF_PASSWORD): _password(),
            vol.Optional(CONF_ORG_ID): str,
            **_stats_field(),
        })
        if user_input:
            secret = (CONF_PASSWORD, CONF_APP_SECRET)
            safe = {k: v for k, v in user_input.items() if k not in secret}
            schema = self.add_suggested_values_to_schema(schema, safe)
        return self.async_show_form(
            step_id="cloud",
            data_schema=schema,
            errors=errors,
            description_placeholders={**CLOUD_PLACEHOLDERS, **STATS_PLACEHOLDERS},
        )

    async def async_step_cloud_pick(self, user_input: dict[str, Any] | None = None
                                    ) -> ConfigFlowResult:
        if user_input is not None:
            return await self._create_cloud_entry(self._batteries[int(user_input["battery"])])
        options = [
            SelectOptionDict(
                value=str(index),
                label=f"{device.get('deviceSn')} ({device.get('stationName') or '?'})",
            )
            for index, device in enumerate(self._batteries)
        ]
        return self.async_show_form(
            step_id="cloud_pick",
            data_schema=vol.Schema({
                vol.Required("battery", default="0"): SelectSelector(
                    SelectSelectorConfig(options=options, mode=SelectSelectorMode.LIST)
                ),
            }),
        )

    async def _create_cloud_entry(self, device: dict) -> ConfigFlowResult:
        sn = str(device.get("deviceSn"))
        await self.async_set_unique_id(sn, raise_on_progress=False)
        self._abort_if_unique_id_configured()
        model = model_name(str(device.get("deviceModel") or "") or None)
        stats = self._cloud.pop(CONF_SEND_STATISTICS, True)
        return self.async_create_entry(
            title=_title(model, " (Solarman)"),
            data={
                CONF_SOURCE: SOURCE_CLOUD,
                **self._cloud,
                CONF_DEVICE_SN: sn,
                CONF_STATION_NAME: device.get("stationName"),
                CONF_MODEL: model,
            },
            options={CONF_SEND_STATISTICS: stats, CONF_SCAN_INTERVAL: DEFAULT_CLOUD_INTERVAL},
        )

    # A new password or secret for the cloud.

    async def async_step_reauth(self, entry_data: dict[str, Any]) -> ConfigFlowResult:
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(self, user_input: dict[str, Any] | None = None
                                        ) -> ConfigFlowResult:
        entry = self._get_reauth_entry()
        errors: dict[str, str] = {}
        if user_input is not None:
            data = {
                **entry.data,
                CONF_APP_SECRET: user_input[CONF_APP_SECRET].strip(),
                CONF_PASSWORD_SHA256: hash_password(user_input[CONF_PASSWORD]),
            }
            try:
                await self._cloud_client(data).authenticate()
            except CloudAuthError:
                errors["base"] = "invalid_auth"
            except CloudError:
                errors["base"] = "cloud_unreachable"
            else:
                return self.async_update_reload_and_abort(entry, data=data)
        return self.async_show_form(
            step_id="reauth_confirm",
            data_schema=vol.Schema({
                vol.Required(CONF_APP_SECRET): _password(),
                vol.Required(CONF_PASSWORD): _password(),
            }),
            errors=errors,
            description_placeholders={"account": str(entry.data.get(CONF_ACCOUNT, ""))},
        )

    # A new address for a battery already set up.

    async def async_step_reconfigure(self, user_input: dict[str, Any] | None = None
                                     ) -> ConfigFlowResult:
        entry = self._get_reconfigure_entry()
        if entry.data.get(CONF_SOURCE) == SOURCE_CLOUD:
            return self.async_abort(reason="reconfigure_cloud")
        errors: dict[str, str] = {}
        if user_input is not None:
            result, error = await self._probe_form(user_input)
            if result is not None:
                host = user_input[CONF_HOST].strip()
                await self.async_set_unique_id(_unique_id(result, host, result.port))
                self._abort_if_unique_id_mismatch(reason="another_battery")
                data = {**entry.data, **_local_data(result, host, int(user_input[CONF_SLAVE]))}
                return self.async_update_reload_and_abort(entry, data=data)
            errors["base"] = error or "cannot_connect"
        return self.async_show_form(
            step_id="reconfigure",
            data_schema=_manual_schema(user_input or dict(entry.data), with_stats=False),
            errors=errors,
        )


class PylontechOptionsFlow(OptionsFlowWithReload):
    async def async_step_init(self, user_input: dict[str, Any] | None = None
                              ) -> ConfigFlowResult:
        entry = self.config_entry
        current = {**entry.data, **entry.options}
        cloud = entry.data.get(CONF_SOURCE) == SOURCE_CLOUD
        if user_input is not None:
            was_on = current.get(CONF_SEND_STATISTICS, True)
            if was_on and not user_input.get(CONF_SEND_STATISTICS, True):
                # Switching it off sends the one call that tells the service
                # the installation has stopped reporting, rather than merely
                # going quiet; what was sent stays there. Imported here:
                # stats.py pulls in Home Assistant's storage, which only this
                # branch needs.
                from .stats import async_forget_install

                await async_forget_install(self.hass, entry, DOMAIN)
            return self.async_create_entry(data={**entry.options, **user_input})
        if cloud:
            interval = _number(MIN_CLOUD_INTERVAL, MAX_CLOUD_INTERVAL, 60, "s")
            default_interval = DEFAULT_CLOUD_INTERVAL
        else:
            interval = _number(MIN_LOCAL_INTERVAL, MAX_LOCAL_INTERVAL, 5, "s")
            default_interval = DEFAULT_LOCAL_INTERVAL
        fields: dict[Any, Any] = {
            vol.Required(CONF_SCAN_INTERVAL,
                         default=current.get(CONF_SCAN_INTERVAL, default_interval)): interval,
        }
        if not cloud:
            fields[vol.Required(CONF_CELL_DATA, default=current.get(CONF_CELL_DATA, True))] = bool
        fields[vol.Optional(CONF_SEND_STATISTICS,
                            default=current.get(CONF_SEND_STATISTICS, True))] = bool
        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema(fields),
            description_placeholders=STATS_PLACEHOLDERS,
        )
