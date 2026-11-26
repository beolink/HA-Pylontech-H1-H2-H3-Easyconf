"""Layout of the Pylontech dashboard, built from a plain description of the batteries.

Free of Home Assistant on purpose, like registers.py, so the layout can be
tested without an installation (tests/test_dashboard.py). dashboard.py looks
the entities up and hands this module one dict per battery:

    {"name": str, "hint": str,
     "entities": {key: entity_id}, "names": {key: short entity name},
     "modules": [{"number": int, "name": str,
                  "entities": {key: entity_id}, "names": {key: short entity name},
                  "cells": [(cell number, entity_id of its voltage)],
                  "cell_temperatures": [(cell number, entity_id)]}]}

The keys are the ones in STACK_ENTITIES and MODULE_ENTITIES, which are the
sensors' own keys (sensor.py). A key that is missing leaves its card out, so a
battery read through the cloud gets no cells and one with cell data switched
off no Cells tab. ``hint`` tells two batteries of the same name apart. A name
that is missing is taken from SHORT, the dashboard's own shorter label for a
sensor whose name does not fit a half-width tile.

Only cards Home Assistant ships are used: nothing to install, and nothing
that breaks when a frontend library moves on.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any

URL_PATH = "pylontech-easyconf"  # Lovelace wants a hyphen in a dashboard's path
TITLE = "Pylontech"
ICON = "mdi:home-battery"

OVERVIEW_PATH = "overview"
MODULES_PATH = "modules"
CELLS_PATH = "cells"
#: The tabs this module owns. Building the dashboard again replaces them and
#: keeps every other tab a person added to the dashboard by hand.
OWN_PATHS = frozenset({OVERVIEW_PATH, MODULES_PATH, CELLS_PATH})

HOURS = 24

#: Stack-level key -> entity domain. The unique id is "<battery id>_<key>".
STACK_ENTITIES = {
    "soc": "sensor",
    "state": "sensor",
    "power": "sensor",
    "remaining_energy": "sensor",
    "voltage": "sensor",
    "current": "sensor",
    "bms_temperature": "sensor",
    "soh": "sensor",
    "cycles": "sensor",
    "fully_charged": "binary_sensor",
    "charge_today": "sensor",
    "discharge_today": "sensor",
    "charge_total": "sensor",
    "discharge_total": "sensor",
    "cell_voltage_max": "sensor",
    "cell_voltage_min": "sensor",
    "cell_voltage_spread": "sensor",
    "cell_temperature_max": "sensor",
    "cell_temperature_min": "sensor",
    "charge_voltage_limit": "sensor",
    "charge_current_limit": "sensor",
    "discharge_voltage_limit": "sensor",
    "discharge_current_limit": "sensor",
}
#: A module's keys. The unique id is "<battery id>_m<number>_<key>".
MODULE_ENTITIES = ("voltage", "temperature", "cell_voltage_max", "cell_voltage_min",
                   "cell_voltage_spread")

# Tiles in the order they appear, as (key, grid columns of 12).
_STATUS_TILES = (
    ("state", 6), ("power", 6),
    ("remaining_energy", 6), ("fully_charged", 6),
    ("voltage", 6), ("current", 6),
    ("bms_temperature", 6), ("soh", 6),
    ("cycles", 6),
)
_ENERGY_TILES = (
    ("charge_today", 6), ("discharge_today", 6),
    # Full width: "Discharged in total" is cut off on half a row.
    ("charge_total", 12), ("discharge_total", 12),
)
_CELL_TILES = (
    ("cell_voltage_max", 6), ("cell_voltage_min", 6),
    ("cell_voltage_spread", 12),
    ("cell_temperature_max", 6), ("cell_temperature_min", 6),
)
#: The limits are a list, not tiles: their names are long and the values are
#: looked up now and then, not watched.
_LIMITS = ("charge_voltage_limit", "charge_current_limit",
           "discharge_voltage_limit", "discharge_current_limit")
_MODULE_TILES = (
    ("voltage", 6), ("temperature", 6),
    ("cell_voltage_max", 6), ("cell_voltage_min", 6),
    ("cell_voltage_spread", 12),
)

TEXT = {
    "sv": {
        "overview": "Översikt", "modules": "Moduler", "cells": "Celler",
        "energy": "Energi", "cell_balance": "Cellbalans", "limits": "BMS:ens gränser",
        "all_modules": "Alla moduler", "module_voltages": "Modulspänningar",
        "module_temperatures": "Modultemperaturer", "temperatures": "Temperaturer",
        "module": "Modul {number}",
    },
    "en": {
        "overview": "Overview", "modules": "Modules", "cells": "Cells",
        "energy": "Energy", "cell_balance": "Cell balance", "limits": "The BMS's limits",
        "all_modules": "All modules", "module_voltages": "Module voltages",
        "module_temperatures": "Module temperatures", "temperatures": "Temperatures",
        "module": "Module {number}",
    },
}


#: Shorter labels for the sensors whose own names are cut off on a half-width
#: tile ("Highest cell voltage" under the heading Cell balance). Used where
#: dashboard.py passes no name, which it does for these unless a person named
#: the entity themselves.
SHORT = {
    "sv": {"remaining_energy": "Energi kvar", "cell_voltage_max": "Högsta cell",
           "cell_voltage_min": "Lägsta cell"},
    "en": {"remaining_energy": "Energy left", "cell_voltage_max": "Highest cell",
           "cell_voltage_min": "Lowest cell"},
}
SHORT_KEYS = frozenset(SHORT["en"])


def language(lang: str | None) -> str:
    """Swedish for any sv-* setting, English otherwise."""
    return "sv" if str(lang or "").lower().startswith("sv") else "en"


def _heading(name: str, icon: str | None = None, subtitle: bool = False) -> dict[str, Any]:
    card: dict[str, Any] = {"type": "heading", "heading": name,
                            "heading_style": "subtitle" if subtitle else "title"}
    if icon:
        card["icon"] = icon
    return card


def _tile(entity_id: str, name: str | None, columns: int) -> dict[str, Any]:
    card: dict[str, Any] = {"type": "tile", "entity": entity_id}
    if name:
        # The registry's short name, so a tile under the battery's heading
        # reads "Voltage" rather than repeating the battery's name before it.
        card["name"] = name
    card["grid_options"] = {"columns": columns}
    return card


def _tiles(entities: Mapping[str, str], names: Mapping[str, str],
           layout: Iterable[tuple[str, int]], short: Mapping[str, str]) -> list[dict[str, Any]]:
    return [_tile(entities[key], names.get(key) or short.get(key), columns)
            for key, columns in layout if entities.get(key)]


def _list(entities: Mapping[str, str], names: Mapping[str, str],
          keys: Iterable[str]) -> dict[str, Any] | None:
    """The entities as rows of one card, each name in full."""
    rows = [{"entity": entities[key], **({"name": names[key]} if names.get(key) else {})}
            for key in keys if entities.get(key)]
    if not rows:
        return None
    return {"type": "entities", "entities": rows, "grid_options": {"columns": 12}}


def _graph(title: str, entities: Iterable[tuple[str, str | None]]) -> dict[str, Any] | None:
    """A history graph of the last day, or None with nothing to draw."""
    rows = [{"entity": entity_id, **({"name": name} if name else {})}
            for entity_id, name in entities if entity_id]
    if not rows:
        return None
    return {"type": "history-graph", "title": title, "hours_to_show": HOURS, "entities": rows,
            "grid_options": {"columns": 12}}


def _named(batteries: Iterable[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """The batteries that have anything to show, by name, each with a name
    of its own: two of the same name get their hint after it."""
    wanted = [dict(b) for b in batteries
              if isinstance(b, Mapping) and (b.get("entities") or b.get("modules"))]
    wanted.sort(key=lambda b: (str(b.get("name") or "").casefold(), str(b.get("hint") or "")))
    seen: dict[str, int] = {}
    for battery in wanted:
        name = str(battery.get("name") or TITLE)
        battery["name"] = name
        seen[name] = seen.get(name, 0) + 1
    for battery in wanted:
        if seen[battery["name"]] > 1 and battery.get("hint"):
            battery["name"] = f"{battery['name']} ({battery['hint']})"
    return wanted


def _modules(battery: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    modules = [m for m in battery.get("modules") or [] if isinstance(m, Mapping)]
    return sorted(modules, key=lambda m: int(m.get("number") or 0))


def _module_name(module: Mapping[str, Any], text: Mapping[str, str]) -> str:
    return str(module.get("name") or text["module"].format(number=module.get("number")))


def overview_sections(battery: Mapping[str, Any], text: Mapping[str, str],
                      short: Mapping[str, str], several: bool) -> list[dict[str, Any]]:
    """The battery's status, its energy and its cell balance, a section each."""
    entities = battery.get("entities") or {}
    names = battery.get("names") or {}
    name = str(battery["name"])

    def titled(title: str) -> str:
        # With several batteries every section says whose it is.
        return f"{title}, {name}" if several else title

    sections: list[dict[str, Any]] = []
    status: list[dict[str, Any]] = []
    if entities.get("soc"):
        status.append({
            "type": "gauge", "entity": entities["soc"], "name": names.get("soc") or "",
            "min": 0, "max": 100, "needle": False,
            "severity": {"green": 40, "yellow": 15, "red": 0},
            "grid_options": {"columns": 12},
        })
    status += _tiles(entities, names, _STATUS_TILES, short)
    if status:
        sections.append({"type": "grid", "cards": [_heading(name, ICON), *status]})

    energy = _tiles(entities, names, _ENERGY_TILES, short)
    for key in ("soc", "power"):
        graph = _graph(names.get(key) or key, [(entities.get(key), names.get(key))])
        if graph:
            energy.append(graph)
    if energy:
        heading = _heading(titled(text["energy"]), "mdi:lightning-bolt")
        sections.append({"type": "grid", "cards": [heading, *energy]})

    cells = _tiles(entities, names, _CELL_TILES, short)
    graph = _graph(names.get("cell_voltage_spread") or text["cell_balance"],
                   [(entities.get("cell_voltage_spread"), names.get("cell_voltage_spread"))])
    if graph:
        cells.append(graph)
    limits = _list(entities, names, _LIMITS)
    if limits:
        cells += [_heading(text["limits"], subtitle=True), limits]
    if cells:
        heading = _heading(titled(text["cell_balance"]), "mdi:scale-balance")
        sections.append({"type": "grid", "cards": [heading, *cells]})
    return sections


def module_sections(battery: Mapping[str, Any], text: Mapping[str, str],
                    short: Mapping[str, str], several: bool) -> list[dict[str, Any]]:
    """The modules side by side in two graphs, then a section per module."""
    modules = _modules(battery)
    sections: list[dict[str, Any]] = []
    compare = [
        _graph(text["module_voltages"],
               [((m.get("entities") or {}).get("voltage"), _module_name(m, text))
                for m in modules]),
        _graph(text["module_temperatures"],
               [((m.get("entities") or {}).get("temperature"), _module_name(m, text))
                for m in modules]),
    ]
    compare = [g for g in compare if g]
    if compare:
        title = battery["name"] if several else text["all_modules"]
        sections.append({"type": "grid", "cards": [_heading(str(title), ICON), *compare]})
    for module in modules:
        tiles = _tiles(module.get("entities") or {}, module.get("names") or {}, _MODULE_TILES,
                       short)
        if tiles:
            heading = _heading(_module_name(module, text), "mdi:battery")
            sections.append({"type": "grid", "cards": [heading, *tiles]})
    return sections


def _glance(cells: Iterable[tuple[int, str]]) -> dict[str, Any] | None:
    """Every cell of a module as a number under its cell number."""
    rows = [{"entity": entity_id, "name": str(number)}
            for number, entity_id in sorted(cells) if entity_id]
    if not rows:
        return None
    return {"type": "glance", "show_icon": False, "show_name": True, "show_state": True,
            "state_color": False, "columns": 5 if len(rows) <= 20 else 6, "entities": rows,
            "grid_options": {"columns": 12}}


def cell_sections(battery: Mapping[str, Any], text: Mapping[str, str],
                  short: Mapping[str, str], several: bool) -> list[dict[str, Any]]:
    """A section per module with every cell's voltage, and its temperature
    where somebody enabled those."""
    sections: list[dict[str, Any]] = []
    for module in _modules(battery):
        voltages = _glance(module.get("cells") or [])
        if voltages is None:
            continue
        name = _module_name(module, text)
        if several:
            name = f"{name}, {battery['name']}"
        cards = [_heading(name, "mdi:battery"), voltages]
        temperatures = _glance(module.get("cell_temperatures") or [])
        if temperatures:
            cards += [_heading(text["temperatures"], subtitle=True), temperatures]
        sections.append({"type": "grid", "cards": cards})
    return sections


def build_dashboard(batteries: Iterable[Mapping[str, Any]], lang: str | None) -> dict[str, Any]:
    """The whole dashboard: an overview, the modules and the cells, each tab
    only when there is something to put on it."""
    named = _named(batteries or [])
    text = TEXT[language(lang)]
    short = SHORT[language(lang)]
    several = len(named) > 1
    views: list[dict[str, Any]] = []
    for path, title, icon, columns, builder in (
        (OVERVIEW_PATH, text["overview"], ICON, 3, overview_sections),
        (MODULES_PATH, text["modules"], "mdi:battery-charging-medium", 4, module_sections),
        (CELLS_PATH, text["cells"], "mdi:view-grid", 3, cell_sections),
    ):
        sections = [s for battery in named for s in builder(battery, text, short, several)]
        if sections:
            views.append({"title": title, "path": path, "icon": icon, "type": "sections",
                          "max_columns": columns, "sections": sections})
    return {"title": TITLE, "views": views}


def batteries_shown(batteries: Iterable[Mapping[str, Any]]) -> int:
    """How many batteries a dashboard built from these would show."""
    return len(_named(batteries or []))


def merge(existing: Mapping[str, Any] | None, generated: Mapping[str, Any]) -> dict[str, Any]:
    """Put the generated tabs first and keep everything else a person added."""
    config: dict[str, Any] = {}
    kept: list[Any] = []
    if isinstance(existing, Mapping):
        # A strategy would make Lovelace pass over the tabs written here.
        config = {k: v for k, v in existing.items() if k not in ("views", "strategy")}
        old = existing.get("views")
        kept = [v for v in (old if isinstance(old, list) else [])
                if not (isinstance(v, Mapping) and v.get("path") in OWN_PATHS)]
    config.setdefault("title", generated.get("title", TITLE))
    config["views"] = list(generated.get("views") or []) + kept
    return config


def without_own(existing: Mapping[str, Any] | None) -> dict[str, Any]:
    """The dashboard with this module's tabs taken out and the rest as it was."""
    return merge(existing, {"title": TITLE, "views": []})


def notification_text(lang: str | None, batteries: int, kept_tabs: int = 0) -> str:
    """What the person sees after the dashboard was built or taken away."""
    swedish = language(lang) == "sv"
    if batteries:
        if swedish:
            what = "1 batteri" if batteries == 1 else f"{batteries} batterier"
            return f"Dashboarden {TITLE} visar nu {what}. [Öppna den](/{URL_PATH})"
        what = "1 battery" if batteries == 1 else f"{batteries} batteries"
        return f"The {TITLE} dashboard now shows {what}. [Open it](/{URL_PATH})"
    if kept_tabs:
        if swedish:
            return (f"Batterierna är borttagna från dashboarden {TITLE}. Dina egna flikar står "
                    f"kvar. [Öppna den](/{URL_PATH})")
        return (f"The batteries are off the {TITLE} dashboard. The tabs you added are still "
                f"there. [Open it](/{URL_PATH})")
    if swedish:
        return f"Dashboarden {TITLE} är borttagen."
    return f"The {TITLE} dashboard is removed."
