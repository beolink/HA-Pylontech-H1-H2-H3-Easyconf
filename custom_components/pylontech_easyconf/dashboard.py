"""Build, rebuild and take away the Pylontech dashboard.

The layout is dashboard_views.py; this file finds the entities and talks to
Lovelace. A battery is on the dashboard when its entry has the option ticked
(Configure), and the dashboard is built when that dialog is saved: never by
itself, so what a person changed on it by hand stays until they ask for a new
one. Removing the last battery takes the dashboard away again, unless a person
added tabs of their own to it, which are kept.

Home Assistant has no public call for creating a dashboard, so the storage
collection behind Settings > Dashboards is reached through the websocket
command that lists dashboards, the same collection the frontend writes to.
What comes out is an ordinary dashboard: it is in the sidebar and in Settings,
and it can be edited by hand. Everything here is checked before use, and a
failure only means there is no dashboard; it never touches the battery's
entities.
"""

from __future__ import annotations

import asyncio
import logging
import re
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import device_registry as dr, entity_registry as er
from homeassistant.helpers.storage import Store

from . import dashboard_views as views
from .const import CONF_DASHBOARD, DASHBOARD_PENDING, DOMAIN, NAME

_LOGGER = logging.getLogger(__name__)

NOTIFICATION_ID = f"{DOMAIN}_dashboard"
_STORE_KEY = f"{DOMAIN}.dashboard"
_LOCK_KEY = f"{DOMAIN}_dashboard_lock"
_LOVELACE = "lovelace"
_WEBSOCKET = "websocket_api"
_COMMANDS = ("lovelace/dashboards/list", "lovelace/dashboards/create")

_MODULE_ID = re.compile(r"^m(\d+)_(.+)$")
_CELL_KEY = re.compile(r"^cell_(\d+)_(voltage|temperature)$")


def _collect(hass: HomeAssistant, exclude: str | None = None) -> list[dict[str, Any]]:
    """One plain dict per battery that is to be on the dashboard, as
    dashboard_views expects.

    Read off the registries alone, so a battery that is away for the moment
    keeps its place. ``exclude`` is an entry on its way out.
    """
    ent_reg = er.async_get(hass)
    dev_reg = dr.async_get(hass)
    batteries: list[dict[str, Any]] = []
    for entry in hass.config_entries.async_entries(DOMAIN):
        if entry.entry_id == exclude or not entry.options.get(CONF_DASHBOARD):
            continue
        base = entry.unique_id or entry.entry_id
        prefix = f"{base}_"
        device_names = {
            identifier[1]: device.name_by_user or device.name
            for device in dr.async_entries_for_config_entry(dev_reg, entry.entry_id)
            for identifier in device.identifiers if identifier[0] == DOMAIN
        }
        entities: dict[str, str] = {}
        names: dict[str, str] = {}
        modules: dict[int, dict[str, Any]] = {}
        for item in er.async_entries_for_config_entry(ent_reg, entry.entry_id):
            # Leave out what a person switched off or hid, as the built-in
            # dashboards do.
            if item.disabled_by or item.hidden_by or not item.unique_id.startswith(prefix):
                continue
            key = item.unique_id[len(prefix):]
            match = _MODULE_ID.match(key)
            plain = match[2] if match else key
            # The name a person gave it, else the entity's own, else none: for
            # a few the dashboard has a shorter label of its own (SHORT).
            name = item.name or (None if plain in views.SHORT_KEYS else item.original_name)
            if match is None:
                if views.STACK_ENTITIES.get(key) == item.domain:
                    entities[key] = item.entity_id
                    if name:
                        names[key] = name
                continue
            if item.domain != "sensor":
                continue
            number = int(match[1])
            module = modules.setdefault(number, {
                "number": number, "name": device_names.get(f"{base}_module_{number}"),
                "entities": {}, "names": {}, "cells": [], "cell_temperatures": [],
            })
            if plain in views.MODULE_ENTITIES:
                module["entities"][plain] = item.entity_id
                if name:
                    module["names"][plain] = name
            elif cell := _CELL_KEY.match(plain):
                target = "cells" if cell[2] == "voltage" else "cell_temperatures"
                module[target].append((int(cell[1]), item.entity_id))
        batteries.append({
            "name": device_names.get(base) or entry.title,
            # What tells two towers of the same name apart: the end of the
            # serial number, which is on the battery's label.
            "hint": f"…{base[-4:]}",
            "entities": entities,
            "names": names,
            "modules": [modules[number] for number in sorted(modules)],
        })
    return batteries


def _dashboards(hass: HomeAssistant) -> dict | None:
    """Lovelace's dashboards by url path: a dict key before 2025, an attribute since."""
    data = hass.data.get(_LOVELACE)
    found = data.get("dashboards") if isinstance(data, dict) else getattr(data, "dashboards", None)
    return found if isinstance(found, dict) else None


def _collection(hass: HomeAssistant) -> Any:
    """The collection behind Settings > Dashboards, found through its websocket commands.

    The list command is registered as a bound method of the websocket wrapper
    that holds the collection; create is the same method wrapped by decorators
    that keep __wrapped__, so the chain is followed until something has
    __self__.
    """
    handlers = hass.data.get(_WEBSOCKET)
    if not isinstance(handlers, dict):
        return None
    for command in _COMMANDS:
        registered = handlers.get(command)
        handler = registered[0] if isinstance(registered, tuple) and registered else None
        for _ in range(6):
            if handler is None:
                break
            found = getattr(getattr(handler, "__self__", None), "storage_collection", None)
            if found is not None and hasattr(found, "async_create_item"):
                return found
            handler = getattr(handler, "__wrapped__", None)
    return None


def _item_id(collection: Any) -> str | None:
    """The collection's id of the dashboard at our address."""
    try:
        items = collection.async_items()
    except Exception:  # a collection that changed shape has no item of ours
        return None
    for item in items:
        if isinstance(item, dict) and item.get("url_path") == views.URL_PATH:
            return item.get("id")
    return None


async def _load(dashboard: Any) -> Any:
    try:
        return await dashboard.async_load(False)
    except HomeAssistantError:  # ConfigNotFound: never saved before
        return None


async def _build(hass: HomeAssistant, store: Store, batteries: list[dict[str, Any]],
                 lang: str) -> None:
    dashboards = _dashboards(hass)
    if dashboards is None:
        raise HomeAssistantError("Lovelace is not loaded, so no dashboard can be made")
    dashboard = dashboards.get(views.URL_PATH)
    if dashboard is None:
        collection = _collection(hass)
        if collection is None:
            raise HomeAssistantError(
                f"could not create a dashboard; add one at /{views.URL_PATH} by hand "
                "(Settings, Dashboards) and save the battery's options again")
        # Adding the item runs Lovelace's own listener, which creates the
        # storage and the sidebar entry before this returns.
        await collection.async_create_item({
            "url_path": views.URL_PATH, "title": views.TITLE, "icon": views.ICON,
            "show_in_sidebar": True, "require_admin": False})
        await store.async_save({"created": True})
        dashboard = dashboards.get(views.URL_PATH)
    if dashboard is None or getattr(dashboard, "mode", None) != "storage":
        raise HomeAssistantError(f"/{views.URL_PATH} is not a dashboard that can be written to")
    config = views.build_dashboard(batteries, lang)
    await dashboard.async_save(views.merge(await _load(dashboard), config))


async def _take_away(hass: HomeAssistant, store: Store) -> int | None:
    """Take the batteries' tabs off the dashboard, and the dashboard with them
    when this integration made it and nothing else is on it.

    Returns how many tabs of a person's own were kept, or None when there was
    no dashboard to change.
    """
    dashboards = _dashboards(hass)
    dashboard = dashboards.get(views.URL_PATH) if dashboards is not None else None
    if dashboard is None or getattr(dashboard, "mode", None) != "storage":
        return None
    existing = await _load(dashboard)
    if not isinstance(existing, dict):
        existing = None
    if existing is None:
        kept: list[Any] = []
    else:
        stripped = views.without_own(existing)
        kept = stripped["views"]
        if len(kept) == len(existing.get("views") or []) and kept:
            return None  # none of the tabs were ours
    if kept:
        await dashboard.async_save(stripped)
        return len(kept)
    made_here = bool((await store.async_load() or {}).get("created"))
    collection = _collection(hass) if made_here else None
    item_id = _item_id(collection) if collection is not None else None
    if item_id is not None:
        # Lovelace's own listener takes the sidebar entry and the storage away.
        await collection.async_delete_item(item_id)
        await store.async_save({"created": False})
    elif existing is not None:
        # Somebody else's dashboard, or one that cannot be reached: emptied.
        await dashboard.async_save(views.without_own(existing))
    return 0


def _notify(hass: HomeAssistant, text: str) -> None:
    from homeassistant.components import persistent_notification

    persistent_notification.async_create(hass, text, title=NAME, notification_id=NOTIFICATION_ID)


async def async_apply(hass: HomeAssistant, exclude: str | None = None) -> int:
    """Make the dashboard show the batteries that are to be on it now.

    Returns how many batteries it shows. Raises HomeAssistantError when the
    dashboard could not be written.
    """
    lock = hass.data.setdefault(_LOCK_KEY, asyncio.Lock())
    lang = hass.config.language
    async with lock:
        store: Store = Store(hass, 1, _STORE_KEY)
        batteries = _collect(hass, exclude)
        shown = views.batteries_shown(batteries)
        if shown:
            await _build(hass, store, batteries, lang)
            _LOGGER.info("Dashboard /%s built with %s batteries", views.URL_PATH, shown)
            _notify(hass, views.notification_text(lang, shown))
            return shown
        kept = await _take_away(hass, store)
        if kept is not None:
            _LOGGER.info("The batteries are off the dashboard /%s", views.URL_PATH)
            _notify(hass, views.notification_text(lang, 0, kept))
    return 0


async def async_apply_safely(hass: HomeAssistant, exclude: str | None = None) -> None:
    """The same, for where a dashboard must never break what called it."""
    try:
        await async_apply(hass, exclude)
    except HomeAssistantError as err:
        _LOGGER.warning("The dashboard was not built: %s", err)
        _notify(hass, f"{views.TITLE}: {err}")
    except Exception:  # a dashboard must never break the integration
        _LOGGER.exception("Could not build the dashboard")


def async_request(hass: HomeAssistant, entry_id: str) -> None:
    """Ask for the dashboard to be built once this entry, which is about to
    reload, has its entities again (async_apply_pending, from its set-up)."""
    hass.data.setdefault(DASHBOARD_PENDING, set()).add(entry_id)


async def async_apply_pending(hass: HomeAssistant, entry_id: str) -> None:
    """Build the dashboard if this entry's options asked for it. Only in that
    entry's own set-up: another battery that happens to start in between
    would build it from entities the reload has not changed yet."""
    pending = hass.data.get(DASHBOARD_PENDING)
    if pending and entry_id in pending:
        pending.discard(entry_id)
        await async_apply_safely(hass)
