"""How the Pylontech dashboard is laid out (dashboard_views.py): what each
battery gets, what is left out when it is not there, and what a rebuild keeps."""

import json
from pathlib import Path
import re

from custom_components.pylontech_easyconf import dashboard_views as dv

PACKAGE = Path(__file__).resolve().parents[1] / "custom_components" / "pylontech_easyconf"


def _module(number, cells=32, temperatures=False, from_cells=True, prefix="h3"):
    keys = dv.MODULE_ENTITIES if from_cells else ("voltage", "temperature")
    return {
        "number": number, "name": f"Force H3 module {number}",
        "entities": {k: f"sensor.{prefix}_m{number}_{k}" for k in keys},
        "names": {k: k.replace("_", " ").capitalize() for k in keys},
        "cells": [(c, f"sensor.{prefix}_m{number}_cell_{c}_voltage")
                  for c in range(1, cells + 1)],
        "cell_temperatures": [(c, f"sensor.{prefix}_m{number}_cell_{c}_temperature")
                              for c in range(1, cells + 1)] if temperatures else [],
    }


def _battery(name="Pylontech Force H3", modules=2, cells=32, hint="…0423", prefix="h3",
             keys=None, **module):
    keys = list(dv.STACK_ENTITIES) if keys is None else keys
    return {
        "name": name, "hint": hint,
        "entities": {k: f"{dv.STACK_ENTITIES[k]}.{prefix}_{k}" for k in keys},
        "names": {k: k.replace("_", " ").capitalize() for k in keys},
        "modules": [_module(n, cells, prefix=prefix, **module) for n in range(1, modules + 1)],
    }


def _view(config, path):
    return next(v for v in config["views"] if v["path"] == path)


def _cards(config):
    for view in config["views"]:
        for section in view["sections"]:
            yield from section["cards"]


def test_the_keys_are_the_sensors_own():
    sensor = (PACKAGE / "sensor.py").read_text()
    stack, module = sensor.split("MODULE_SENSORS:", 1)
    stack_keys = set(re.findall(r'key="(\w+)"', stack))
    module_keys = set(re.findall(r'key="(\w+)"', module))
    binary = set(re.findall(r'super\(\).__init__\(coordinator, "(\w+)"\)',
                            (PACKAGE / "binary_sensor.py").read_text()))
    for key, domain in dv.STACK_ENTITIES.items():
        assert key in (stack_keys if domain == "sensor" else binary), key
    assert set(dv.MODULE_ENTITIES) <= module_keys


def test_a_battery_gets_an_overview_its_modules_and_its_cells():
    config = dv.build_dashboard([_battery()], "en")
    assert config["title"] == "Pylontech"
    assert [v["path"] for v in config["views"]] == ["overview", "modules", "cells"]
    assert [v["title"] for v in config["views"]] == ["Overview", "Modules", "Cells"]
    assert all(v["type"] == "sections" for v in config["views"])

    status, energy, balance = _view(config, "overview")["sections"]
    assert status["cards"][0] == {"type": "heading", "heading": "Pylontech Force H3",
                                  "heading_style": "title", "icon": "mdi:home-battery"}
    gauge = status["cards"][1]
    assert (gauge["type"], gauge["entity"], gauge["min"], gauge["max"]) == (
        "gauge", "sensor.h3_soc", 0, 100)
    assert status["cards"][2] == {"type": "tile", "entity": "sensor.h3_state", "name": "State",
                                  "grid_options": {"columns": 6}}
    assert "binary_sensor.h3_fully_charged" in [c.get("entity") for c in status["cards"]]
    assert energy["cards"][0]["heading"] == "Energy"
    graphs = [c for c in energy["cards"] if c["type"] == "history-graph"]
    assert [g["entities"][0]["entity"] for g in graphs] == ["sensor.h3_soc", "sensor.h3_power"]
    assert all(g["hours_to_show"] == 24 for g in graphs)
    assert balance["cards"][0]["heading"] == "Cell balance"
    limits = [c for c in balance["cards"] if c.get("heading_style") == "subtitle"]
    assert [c["heading"] for c in limits] == ["The BMS's limits"]
    rows = balance["cards"][-1]
    assert rows["type"] == "entities" and [r["entity"] for r in rows["entities"]] == [
        "sensor.h3_charge_voltage_limit", "sensor.h3_charge_current_limit",
        "sensor.h3_discharge_voltage_limit", "sensor.h3_discharge_current_limit"]
    assert rows["entities"][0]["name"] == "Charge voltage limit"

    compare, first, second = _view(config, "modules")["sections"]
    assert compare["cards"][0]["heading"] == "All modules"
    assert [c["title"] for c in compare["cards"][1:]] == ["Module voltages", "Module temperatures"]
    assert [e["name"] for e in compare["cards"][1]["entities"]] == [
        "Force H3 module 1", "Force H3 module 2"]
    assert first["cards"][0]["heading"] == "Force H3 module 1"
    assert first["cards"][1]["entity"] == "sensor.h3_m1_voltage"
    assert second["cards"][0]["heading"] == "Force H3 module 2"

    cells = _view(config, "cells")["sections"]
    assert len(cells) == 2
    glance = cells[0]["cards"][1]
    assert glance["type"] == "glance" and glance["columns"] == 6
    assert glance["show_icon"] is False and glance["show_state"] is True
    assert [e["name"] for e in glance["entities"]] == [str(n) for n in range(1, 33)]
    assert glance["entities"][0]["entity"] == "sensor.h3_m1_cell_1_voltage"


def test_only_cards_home_assistant_ships_and_plain_json():
    config = dv.build_dashboard([_battery(temperatures=True)], "sv")
    assert {c["type"] for c in _cards(config)} == {"heading", "gauge", "tile", "history-graph",
                                                   "glance", "entities"}
    assert json.loads(json.dumps(config)) == config


def test_swedish_headings():
    config = dv.build_dashboard([_battery()], "sv-SE")
    assert [v["title"] for v in config["views"]] == ["Översikt", "Moduler", "Celler"]
    _, energy, balance = _view(config, "overview")["sections"]
    assert (energy["cards"][0]["heading"], balance["cards"][0]["heading"]) == (
        "Energi", "Cellbalans")
    assert _view(config, "modules")["sections"][0]["cards"][0]["heading"] == "Alla moduler"


def test_cell_data_switched_off_leaves_the_cells_tab_out():
    battery = _battery(cells=0, from_cells=False)
    config = dv.build_dashboard([battery], "en")
    assert [v["path"] for v in config["views"]] == ["overview", "modules"]
    module = _view(config, "modules")["sections"][1]
    assert [c["entity"] for c in module["cards"][1:]] == [
        "sensor.h3_m1_voltage", "sensor.h3_m1_temperature"]


def test_a_cloud_battery_gets_what_the_cloud_has():
    keys = ["soc", "soh", "state", "voltage", "current", "power", "cycles"]
    battery = _battery(name="Pylontech Force H2", keys=keys, cells=0, from_cells=False)
    config = dv.build_dashboard([battery], "en")
    assert [v["path"] for v in config["views"]] == ["overview", "modules"]
    status, energy = _view(config, "overview")["sections"]
    assert [c.get("entity") for c in status["cards"][1:]] == [
        "sensor.h3_soc", "sensor.h3_state", "sensor.h3_power", "sensor.h3_voltage",
        "sensor.h3_current", "sensor.h3_soh", "sensor.h3_cycles"]
    assert [c["type"] for c in energy["cards"]] == ["heading", "history-graph", "history-graph"]


def test_enabled_cell_temperatures_get_a_grid_of_their_own():
    config = dv.build_dashboard([_battery(modules=1, temperatures=True)], "en")
    cards = _view(config, "cells")["sections"][0]["cards"]
    assert [c["type"] for c in cards] == ["heading", "glance", "heading", "glance"]
    assert cards[2] == {"type": "heading", "heading": "Temperatures", "heading_style": "subtitle"}
    assert cards[3]["entities"][0]["entity"] == "sensor.h3_m1_cell_1_temperature"


def test_fifteen_cells_sit_five_to_a_row():
    config = dv.build_dashboard([_battery(modules=1, cells=15)], "en")
    assert _view(config, "cells")["sections"][0]["cards"][1]["columns"] == 5


def test_two_towers_of_the_same_name_are_told_apart():
    towers = [_battery(hint="…0423", prefix="a"), _battery(hint="…0117", prefix="b")]
    config = dv.build_dashboard(towers, "en")
    overview = _view(config, "overview")["sections"]
    assert [s["cards"][0]["heading"] for s in overview] == [
        "Pylontech Force H3 (…0117)", "Energy, Pylontech Force H3 (…0117)",
        "Cell balance, Pylontech Force H3 (…0117)",
        "Pylontech Force H3 (…0423)", "Energy, Pylontech Force H3 (…0423)",
        "Cell balance, Pylontech Force H3 (…0423)"]
    modules = _view(config, "modules")["sections"]
    assert modules[0]["cards"][0]["heading"] == "Pylontech Force H3 (…0117)"
    cells = _view(config, "cells")["sections"]
    assert cells[0]["cards"][0]["heading"] == "Force H3 module 1, Pylontech Force H3 (…0117)"
    assert dv.batteries_shown(towers) == 2


def test_two_batteries_of_different_names_keep_their_names():
    config = dv.build_dashboard([_battery(name="House"), _battery(name="Garage")], "en")
    headings = [s["cards"][0]["heading"] for s in _view(config, "overview")["sections"]]
    assert headings[0] == "Garage" and headings[3] == "House"


def test_a_battery_with_nothing_enabled_is_left_out():
    empty = {"name": "Pylontech Force H3", "hint": "…0001", "entities": {}, "names": {},
             "modules": []}
    assert dv.build_dashboard([empty], "en")["views"] == []
    assert dv.batteries_shown([empty]) == 0
    assert dv.batteries_shown([empty, _battery()]) == 1


def test_a_rebuild_replaces_its_own_tabs_and_keeps_the_rest():
    mine = {"title": "My notes", "path": "notes", "cards": []}
    existing = {"title": "Batteries", "strategy": {"type": "x"},
                "views": [{"title": "Old", "path": "overview"}, mine,
                          {"title": "Old cells", "path": "cells"}]}
    merged = dv.merge(existing, dv.build_dashboard([_battery()], "en"))
    assert merged["title"] == "Batteries" and "strategy" not in merged
    assert [v["path"] for v in merged["views"]] == ["overview", "modules", "cells", "notes"]
    assert merged["views"][0]["title"] == "Overview"
    assert dv.merge(None, {"title": "Pylontech", "views": []}) == {"title": "Pylontech",
                                                                    "views": []}


def test_taking_the_batteries_off_keeps_a_person_s_own_tabs():
    mine = {"title": "My notes", "path": "notes", "cards": []}
    built = dv.merge({"views": [mine]}, dv.build_dashboard([_battery()], "en"))
    assert dv.without_own(built)["views"] == [mine]
    assert dv.without_own(dv.build_dashboard([_battery()], "en"))["views"] == []


def test_the_notification_says_what_happened():
    assert dv.notification_text("en", 1) == (
        "The Pylontech dashboard now shows 1 battery. [Open it](/pylontech-easyconf)")
    assert "3 batterier" in dv.notification_text("sv", 3)
    assert "1 batteri." in dv.notification_text("sv", 1)
    assert dv.notification_text("sv", 0) == "Dashboarden Pylontech är borttagen."
    assert "egna flikar" in dv.notification_text("sv", 0, kept_tabs=2)
    assert "tabs you added" in dv.notification_text("en", 0, kept_tabs=1)


def test_no_dashes_in_the_dashboard_s_texts():
    text = json.dumps(dv.TEXT, ensure_ascii=False) + "".join(
        dv.notification_text(lang, n, k) for lang in ("en", "sv") for n in (0, 1, 2)
        for k in (0, 1))
    assert chr(0x2013) not in text and chr(0x2014) not in text


def test_a_long_name_gets_the_dashboard_s_shorter_label_unless_a_person_named_it():
    # dashboard.py passes no name for these unless the entity was renamed.
    battery = _battery(modules=1)
    for key in dv.SHORT_KEYS:
        del battery["names"][key]
    battery["modules"][0]["names"].pop("cell_voltage_max")
    battery["modules"][0]["names"]["cell_voltage_min"] = "Weakest"
    config = dv.build_dashboard([battery], "en")
    names = {c["entity"]: c.get("name") for c in _cards(config) if c["type"] == "tile"}
    assert names["sensor.h3_remaining_energy"] == "Energy left"
    assert names["sensor.h3_cell_voltage_max"] == "Highest cell"
    assert names["sensor.h3_cell_voltage_min"] == "Lowest cell"
    assert names["sensor.h3_m1_cell_voltage_max"] == "Highest cell"
    assert names["sensor.h3_m1_cell_voltage_min"] == "Weakest"
    swedish = dv.build_dashboard([battery], "sv")
    names = {c["entity"]: c.get("name") for c in _cards(swedish) if c["type"] == "tile"}
    assert names["sensor.h3_remaining_energy"] == "Energi kvar"
    assert set(dv.SHORT["sv"]) == set(dv.SHORT["en"]) == dv.SHORT_KEYS
