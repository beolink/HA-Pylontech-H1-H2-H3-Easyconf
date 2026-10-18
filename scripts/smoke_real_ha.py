#!/usr/bin/env python3
"""The integration under a real Home Assistant, against fake batteries.

The unit tests run without Home Assistant, which is what keeps them fast; the
price is that a renamed Home Assistant import, a selector config the real
selector refuses or a translation key that does not resolve would first show
in a house. This runs the integration the way a house does, with only the
outside world faked (tests/fake_logger.py and tests/fake_cloud.py on the
loopback interface), and checks what the owner would see:

1. An address typed in: the logger's serial learned and kept, the stack, its
   two modules and their sixty cells as devices and entities with the real
   Force H2 dump's values and the translated names, the cells' temperatures
   there but disabled.
2. A logger that misses polls: the last reading kept for two, unavailable at
   the third, back at the next answer.
3. The options: a new interval, cell data off and its entities gone, through
   the options flow's own reload.
4. The diagnostics, without the address and the serial numbers.
5. Reconfigure to the same battery, and the same battery once more (refused).
6. The network search: a logger found over UDP, a Force H3 behind it offered
   by name, set up with its 96 cells; then DHCP for the same logger (already
   set up, by its MAC and by its serial).
7. The Solarman cloud: the battery found on the account, its values and the
   extra ones Solarman sends, the password stored only as its hash; a refused
   login starts a reauth that a new password ends.
8. Every entry unloaded, every connection closed.

No anonymous statistics are sent: every entry is made with them off, and the
endpoint is pointed at a closed port besides.

Usage: pip install homeassistant==<version> && python scripts/smoke_real_ha.py
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
from pathlib import Path
import socket
import sys
import tempfile
import traceback

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tests"))

DOMAIN = "pylontech_easyconf"


class Capture(logging.Handler):
    def __init__(self) -> None:
        super().__init__(level=logging.WARNING)
        self.records: list[logging.LogRecord] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.records.append(record)


def ok(what: str) -> None:
    print(f"smoke   ok    {what}")


def port_free(port: int, kind=socket.SOCK_STREAM) -> bool:
    with socket.socket(socket.AF_INET, kind) as s:
        try:
            s.bind(("127.0.0.1", port))
        except OSError:
            return False
    return True


async def boot(config_dir: str):
    from homeassistant import auth as ha_auth, bootstrap, config_entries, loader
    from homeassistant.core import HomeAssistant
    from homeassistant.setup import async_setup_component

    custom = Path(config_dir) / "custom_components"
    custom.mkdir()
    (custom / DOMAIN).symlink_to(ROOT / "custom_components" / DOMAIN)
    sys.path.insert(0, config_dir)
    hass = HomeAssistant(config_dir)
    hass.config.language = "en"
    hass.config.skip_pip = True
    await hass.config.async_set_time_zone("Europe/Stockholm")
    loader.async_setup(hass)
    hass.config_entries = config_entries.ConfigEntries(hass, {})
    await hass.config_entries.async_initialize()
    assert await bootstrap.async_load_base_functionality(hass)
    hass.auth = await ha_auth.auth_manager_from_config(hass, [{"type": "homeassistant"}], [])
    assert await async_setup_component(hass, "homeassistant", {})
    return hass


def kind(result) -> str:
    value = result.get("type")
    return str(getattr(value, "value", value))


async def run(hass, failures: list[str]) -> None:
    from homeassistant.config_entries import ConfigEntryState
    from homeassistant.helpers import device_registry as dr, entity_registry as er
    from homeassistant.helpers.service_info.dhcp import DhcpServiceInfo

    from fake_cloud import ACCOUNT, APP_ID, APP_SECRET, BATTERY_SN, PASSWORD, FakeSolarman
    from fake_logger import FakeBattery, FakeServer
    from fixtures import force_h2 as h2, force_h3 as h3

    from custom_components.pylontech_easyconf import cloud, config_flow, stats
    from custom_components.pylontech_easyconf.diagnostics import (
        async_get_config_entry_diagnostics,
    )
    from custom_components.pylontech_easyconf.sensor import CELL_UNIQUE_ID

    stats.ENDPOINT = "http://127.0.0.1:1/never"
    flow = hass.config_entries.flow
    ents = er.async_get(hass)
    devs = dr.async_get(hass)

    def entity_id(platform: str, unique_id: str) -> str:
        eid = ents.async_get_entity_id(platform, DOMAIN, unique_id)
        assert eid, f"no {platform} with unique id {unique_id}"
        return eid

    def device(identifier: str, entry_id: str):
        key = (DOMAIN, identifier)
        if hasattr(devs, "async_get_device_by_identifier"):  # 2026.8 and later
            return devs.async_get_device_by_identifier(key, entry_id)
        return devs.async_get_device({key})

    def state(platform: str, unique_id: str):
        s = hass.states.get(entity_id(platform, unique_id))
        assert s is not None, unique_id
        return s

    # 1. An address typed in.
    battery = FakeBattery(h2.bank())
    async with FakeServer(battery) as server:
        result = await flow.async_init(DOMAIN, context={"source": "user"})
        assert kind(result) == "menu", result
        assert result["menu_options"] == ["discover", "manual", "cloud"]
        result = await flow.async_configure(result["flow_id"], {"next_step_id": "manual"})
        assert kind(result) == "form" and result["step_id"] == "manual", result
        result = await flow.async_configure(result["flow_id"], {
            "host": "127.0.0.1", "port": 1, "transport": "modbus_tcp", "slave": 1,
            "send_statistics": False,
        })
        assert kind(result) == "form" and result["errors"] == {"base": "cannot_connect"}, result
        result = await flow.async_configure(result["flow_id"], {
            "host": "127.0.0.1", "port": server.port, "transport": "solarman_v5",
            "logger_serial": "", "slave": 1, "send_statistics": False,
        })
        assert kind(result) == "create_entry", result
        await hass.async_block_till_done()
        entry = result["result"]
        assert entry.title == "Pylontech Force H2", entry.title
        assert entry.unique_id == h2.SERIAL
        assert entry.data["logger_serial"] == battery.serial
        assert entry.data["transport"] == "solarman_v5"
        assert entry.options == {"send_statistics": False}
        assert entry.state is ConfigEntryState.LOADED, entry.state
        ok("manual set-up: serial learned, entry loaded")

        devices = dr.async_entries_for_config_entry(devs, entry.entry_id)
        names = sorted(d.name for d in devices)
        assert names == ["Force H2 module 1", "Force H2 module 2", "Pylontech Force H2"], names
        stack = device(h2.SERIAL, entry.entry_id)
        assert stack.sw_version == "1.6" and stack.serial_number == h2.SERIAL
        assert stack.model == "Force H2"
        module = device(f"{h2.SERIAL}_module_1", entry.entry_id)
        assert module.via_device_id == stack.id
        ok("devices: the stack and its two modules, under it")

        s = h2.SERIAL
        soc = state("sensor", f"{s}_soc")
        assert soc.state == "33", soc
        assert soc.attributes["friendly_name"] == "Pylontech Force H2 State of charge", soc
        assert state("sensor", f"{s}_voltage").state == "196.5"
        assert state("sensor", f"{s}_cycles").state == "679"
        assert state("sensor", f"{s}_soh").state == "97"
        assert state("sensor", f"{s}_state").state == "idle"
        assert state("sensor", f"{s}_charge_total").state == "4942.0"
        high = state("sensor", f"{s}_cell_voltage_max")
        assert high.state == "3.276"
        assert (high.attributes["module"], high.attributes["cell"]) == (1, 4)
        assert state("sensor", f"{s}_cell_voltage_spread").state == "3"
        assert state("binary_sensor", f"{s}_fully_charged").state == "off"
        cell = state("sensor", f"{s}_m1_cell_1_voltage")
        assert cell.state == "3.276", cell
        assert cell.attributes["friendly_name"] == "Force H2 module 1 Cell 1 voltage", cell
        assert state("sensor", f"{s}_m2_voltage").state == "98.24"
        assert state("sensor", f"{s}_m2_temperature").state == "27.2"
        temp = ents.async_get(entity_id("sensor", f"{s}_m2_cell_1_temperature"))
        assert temp.disabled_by is er.RegistryEntryDisabler.INTEGRATION, temp
        mine = er.async_entries_for_config_entry(ents, entry.entry_id)
        cells_v = [e for e in mine if CELL_UNIQUE_ID.search(e.unique_id)
                   and e.unique_id.endswith("_voltage")]
        assert len(cells_v) == 60, len(cells_v)
        ok(f"entities: {len(mine)}, the real dump's values, 60 cell voltages, names translated")

        from homeassistant.helpers.translation import async_get_translations

        sv = await async_get_translations(hass, "sv", "entity", [DOMAIN])
        prefix = f"component.{DOMAIN}.entity.sensor"
        assert sv[f"{prefix}.soc.name"] == "Laddningsnivå", sv.get(f"{prefix}.soc.name")
        assert sv[f"{prefix}.state.state.discharging"] == "Laddar ur"
        assert sv[f"{prefix}.cell_voltage.name"] == "Cell {cell} spänning"
        sv_devices = await async_get_translations(hass, "sv", "device", [DOMAIN])
        assert sv_devices[f"component.{DOMAIN}.device.module.name"] == "{model} modul {number}"
        ok("the Swedish names load")

        # 2. Missed polls.
        coordinator = entry.runtime_data
        coordinator.transport.timeout = 0.5
        battery.silent = True
        for poll in (1, 2):
            await coordinator.async_refresh()
            await hass.async_block_till_done()
            assert state("sensor", f"{s}_soc").state == "33", f"poll {poll}"
        await coordinator.async_refresh()
        await hass.async_block_till_done()
        assert state("sensor", f"{s}_soc").state == "unavailable"
        battery.silent = False
        await coordinator.async_refresh()
        await hass.async_block_till_done()
        assert state("sensor", f"{s}_soc").state == "33"
        assert coordinator.failures_total == 3
        ok("two missed polls keep the reading, the third makes it unavailable, then back")

        # 3. The options.
        result = await hass.config_entries.options.async_init(entry.entry_id)
        assert kind(result) == "form" and result["step_id"] == "init", result
        result = await hass.config_entries.options.async_configure(result["flow_id"], {
            "scan_interval": 15, "cell_data": False, "send_statistics": False,
        })
        assert kind(result) == "create_entry", result
        await hass.async_block_till_done()
        assert entry.state is ConfigEntryState.LOADED
        assert entry.runtime_data.update_interval.total_seconds() == 15
        mine = er.async_entries_for_config_entry(ents, entry.entry_id)
        assert not [e for e in mine if CELL_UNIQUE_ID.search(e.unique_id)], "cell entities left"
        assert not ents.async_get_entity_id("sensor", DOMAIN, f"{s}_m1_cell_voltage_spread")
        assert state("sensor", f"{s}_m1_voltage").state == "98.25"
        assert state("sensor", f"{s}_cell_voltage_max").state == "3.276"
        assert not [r for r in battery.requests[-6:] if r[0] >= 0x1500]
        ok("options: interval 15 s, cell data off, the cells' entities removed")

        # 4. The diagnostics.
        diag = await async_get_config_entry_diagnostics(hass, entry)
        text = json.dumps(diag, default=str)
        assert "127.0.0.1" not in text
        assert h2.SERIAL not in text and str(battery.serial) not in text
        assert diag["reading"]["soc"] == 33
        assert diag["connection"]["transport"]["kind"] == "solarman_v5"
        ok("diagnostics: the reading and the connection, no address and no serial")

        # 5. Reconfigure, and the same battery again.
        result = await flow.async_init(DOMAIN, context={"source": "reconfigure",
                                                        "entry_id": entry.entry_id})
        assert kind(result) == "form" and result["step_id"] == "reconfigure", result
        result = await flow.async_configure(result["flow_id"], {
            "host": "127.0.0.1", "port": server.port, "transport": "auto",
            "logger_serial": str(battery.serial), "slave": 1,
        })
        assert kind(result) == "abort" and result["reason"] == "reconfigure_successful", result
        await hass.async_block_till_done()
        assert entry.state is ConfigEntryState.LOADED
        result = await flow.async_init(DOMAIN, context={"source": "user"})
        result = await flow.async_configure(result["flow_id"], {"next_step_id": "manual"})
        result = await flow.async_configure(result["flow_id"], {
            "host": "127.0.0.1", "port": server.port, "transport": "solarman_v5",
            "slave": 1, "send_statistics": False,
        })
        assert kind(result) == "abort" and result["reason"] == "already_configured", result
        ok("reconfigure to the same battery, and the same battery not set up twice")

        transport = entry.runtime_data.transport
        assert transport.connected
        assert await hass.config_entries.async_unload(entry.entry_id)
        await hass.async_block_till_done()
        assert not transport.connected
        # Removed too: the search below skips loggers at an address already set
        # up, and every fake here is at 127.0.0.1.
        await hass.config_entries.async_remove(entry.entry_id)
        await hass.async_block_till_done()
        assert not er.async_entries_for_config_entry(ents, entry.entry_id)
        assert not dr.async_entries_for_config_entry(devs, entry.entry_id)
        ok("unloaded with the connection closed, removed with its devices and entities")

    # 6. The network search, and DHCP. First the broadcast addresses Home
    # Assistant's network integration gives, unpatched.
    targets = await config_flow._broadcast_targets(hass)
    assert targets and all(t.count(".") == 3 for t in targets), targets
    ok(f"broadcast addresses from Home Assistant's network integration: {len(targets)}")
    if port_free(8899) and port_free(48899, socket.SOCK_DGRAM):
        h3_battery = FakeBattery(h3.bank(), serial=3512345678)
        loop = asyncio.get_running_loop()

        class Responder(asyncio.DatagramProtocol):
            def connection_made(self, transport):
                self.transport = transport

            def datagram_received(self, data, addr):
                self.transport.sendto(b"127.0.0.1,E8FDF8000003,3512345678", addr)

        udp, _ = await loop.create_datagram_endpoint(Responder, local_addr=("127.0.0.1", 48899))

        async def loopback(_hass):
            return ["127.0.0.1"]

        config_flow._broadcast_targets = loopback
        server = FakeServer(h3_battery)
        server.server = await asyncio.start_server(server._client, "127.0.0.1", 8899)
        try:
            # Home Assistant saw the logger by DHCP first, and that discovery is
            # waiting for a yes when the owner searches by hand: the search must
            # still set the battery up, and the discovery must go.
            result = await flow.async_init(DOMAIN, context={"source": "dhcp"}, data=DhcpServiceInfo(
                ip="127.0.0.1", hostname="lsw3", macaddress="e8fdf8000003"))
            assert kind(result) == "form" and result["step_id"] == "dhcp_confirm", result
            waiting = result["flow_id"]
            result = await flow.async_init(DOMAIN, context={"source": "user"})
            result = await flow.async_configure(result["flow_id"], {"next_step_id": "discover"})
            assert kind(result) == "form" and result["step_id"] == "pick", result
            assert result["description_placeholders"]["count"] == "1"
            result = await flow.async_configure(result["flow_id"], {"battery": "0",
                                                                    "send_statistics": False})
            assert kind(result) == "create_entry", result
            await hass.async_block_till_done()
            h3_entry = result["result"]
            assert waiting not in [f["flow_id"] for f in flow.async_progress()], "discovery left"
            assert h3_entry.title == "Pylontech Force H3"
            assert h3_entry.data["mac"] == "e8:fd:f8:00:00:03"
            assert h3_entry.data["port"] == 8899
            assert h3_entry.state is ConfigEntryState.LOADED
            t = h3.SERIAL
            coldest = state("sensor", f"{t}_cell_temperature_min")
            assert coldest.state == "-1.5" and coldest.attributes["module"] == 2
            assert coldest.attributes["cell"] == 5
            assert state("sensor", f"{t}_m3_cell_32_voltage").state == "3.342"
            assert state("sensor", f"{t}_state").state == "charging"
            mine = er.async_entries_for_config_entry(ents, h3_entry.entry_id)
            cells = [e for e in mine if CELL_UNIQUE_ID.search(e.unique_id)
                     and e.unique_id.endswith("_voltage")]
            assert len(cells) == 96, len(cells)
            stack = device(t, h3_entry.entry_id)
            assert ("mac", "e8:fd:f8:00:00:03") in stack.connections
            ok("network search with a DHCP discovery waiting: a Force H3 with 96 cells set up by "
               "name, the discovery closed")

            result = await flow.async_init(DOMAIN, context={"source": "dhcp"}, data=DhcpServiceInfo(
                ip="127.0.0.1", hostname="lsw3", macaddress="e8fdf8000003"))
            assert kind(result) == "abort" and result["reason"] == "already_configured", result
            result = await flow.async_init(DOMAIN, context={"source": "dhcp"}, data=DhcpServiceInfo(
                ip="127.0.0.1", hostname="lsw3", macaddress="e8fdf8000009"))
            assert kind(result) == "abort" and result["reason"] == "already_configured", result
            result = await flow.async_init(DOMAIN, context={"source": "user"})
            result = await flow.async_configure(result["flow_id"], {"next_step_id": "discover"})
            assert kind(result) == "form" and result["step_id"] == "discover_none", result
            result = await flow.async_configure(result["flow_id"], {})
            assert kind(result) == "form" and result["step_id"] == "manual", result
            flow.async_abort(result["flow_id"])
            ok("DHCP for a known logger, by MAC and by serial; a search with nothing new")
            assert await hass.config_entries.async_unload(h3_entry.entry_id)
        finally:
            udp.close()
            await server.close()
    else:
        print("smoke   skip  network search and DHCP: port 8899 or 48899 is taken here")

    # 7. The cloud.
    async with FakeSolarman() as fake:
        cloud.BASE_URL = fake.url
        result = await flow.async_init(DOMAIN, context={"source": "user"})
        result = await flow.async_configure(result["flow_id"], {"next_step_id": "cloud"})
        assert kind(result) == "form" and result["step_id"] == "cloud", result
        result = await flow.async_configure(result["flow_id"], {
            "app_id": APP_ID, "app_secret": APP_SECRET, "account": ACCOUNT,
            "password": "fel", "send_statistics": False,
        })
        assert kind(result) == "form" and result["errors"] == {"base": "invalid_auth"}, result
        result = await flow.async_configure(result["flow_id"], {
            "app_id": APP_ID, "app_secret": APP_SECRET, "account": ACCOUNT,
            "password": PASSWORD, "send_statistics": False,
        })
        assert kind(result) == "create_entry", result
        await hass.async_block_till_done()
        c_entry = result["result"]
        assert c_entry.unique_id == BATTERY_SN and c_entry.title == "Pylontech Force H2 (Solarman)"
        assert "password" not in c_entry.data and len(c_entry.data["password_sha256"]) == 64
        assert PASSWORD not in json.dumps(dict(c_entry.data))
        assert c_entry.state is ConfigEntryState.LOADED
        b = BATTERY_SN
        assert state("sensor", f"{b}_soc").state == "57"
        assert state("sensor", f"{b}_state").state == "discharging"
        assert state("sensor", f"{b}_m2_temperature").state == "27.2"
        extra = state("sensor", f"{b}_cloud_MAX_CV1")
        assert extra.state == "3.281" and extra.attributes["unit_of_measurement"] == "V", extra
        assert state("sensor", f"{b}_cloud_B_ST1").state == "Normal"
        assert c_entry.runtime_data.update_interval.total_seconds() == 300
        ok("cloud: the battery found on the account, its values, only the password's hash kept")

        fake.expire_token = True
        fake.refuse_login = True
        await c_entry.runtime_data.async_refresh()
        await hass.async_block_till_done()
        reauth = [f for f in flow.async_progress_by_handler(DOMAIN)
                  if f["context"]["source"] == "reauth"]
        assert len(reauth) == 1, flow.async_progress_by_handler(DOMAIN)
        fake.refuse_login = False
        result = await flow.async_configure(reauth[0]["flow_id"], {
            "app_secret": APP_SECRET, "password": PASSWORD,
        })
        assert kind(result) == "abort" and result["reason"] == "reauth_successful", result
        await hass.async_block_till_done()
        assert c_entry.state is ConfigEntryState.LOADED
        assert state("sensor", f"{b}_soc").state == "57"
        ok("cloud: a refused login asks for the password again, and the new one works")
        assert await hass.config_entries.async_unload(c_entry.entry_id)
        await hass.async_block_till_done()

    left = [e.title for e in hass.config_entries.async_entries(DOMAIN)
            if e.state is ConfigEntryState.LOADED]
    assert not left, left
    ok("every entry unloaded")


async def main() -> int:
    import homeassistant.const as ha_const

    print(f"Home Assistant {ha_const.__version__}, Python {sys.version.split()[0]}")
    capture = Capture()
    logging.getLogger().addHandler(capture)
    logging.getLogger().setLevel(logging.INFO)
    failures: list[str] = []
    with tempfile.TemporaryDirectory() as config_dir:
        hass = await boot(config_dir)
        try:
            await asyncio.wait_for(run(hass, failures), 240)
        except Exception:
            print(f"smoke   FAIL  {traceback.format_exc()}", flush=True)
            failures.append("a step failed, above")
        finally:
            await asyncio.wait_for(hass.async_stop(force=True), 60)
    expected = (
        "which has not been tested by Home Assistant",
        # Home Assistant's own line when the deliberate outage in step 2 makes
        # the third poll fail.
        "Error fetching pylontech_easyconf Pylontech Force H2 data",
        # And when step 7 refuses the login on purpose.
        "Authentication failed while fetching pylontech_easyconf Pylontech Force H2 (Solarman)",
    )
    loud = [r for r in capture.records
            if ("pylontech" in r.name or "pylontech" in r.getMessage())
            and not any(e in r.getMessage() for e in expected)]
    for record in loud:
        print(f"log     {record.levelname:7} {record.name}: {record.getMessage().splitlines()[0]}")
    if loud:
        failures.append(f"{len(loud)} warnings or errors about the integration in the log")
    for failure in failures:
        print(f"smoke   FAIL  {failure}")
    print("smoke   " + ("FAILED" if failures else "passed"))
    return 1 if failures else 0


if __name__ == "__main__":
    code = asyncio.run(main())
    # Home Assistant on Homebrew's Python 3.14 crashes in the interpreter's
    # shutdown once it has loaded its C extensions, after all of the above
    # has run and printed. The exit code is the smoke's.
    logging.shutdown()
    sys.stdout.flush()
    sys.stderr.flush()
    os._exit(code)
