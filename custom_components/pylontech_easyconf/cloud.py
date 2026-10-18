"""The Solarman cloud, the second way in.

When the battery's logger cannot be reached on the local network, its data
still goes to the Solarman cloud every five minutes, and Solarman's OpenAPI
hands it out again. It takes an app id and an app secret, which Solarman's
customer service gives out on request, besides the account's e-mail and
password. The password never leaves Home Assistant: the API wants its SHA-256
hash, and that hash is all the integration stores.

The cloud knows less than the BMS: the stack's voltage, current, charge,
health and cycles and the modules' voltages and temperatures, by the keys
below. Whatever else it sends for the battery becomes a sensor under the name
Solarman gives it, so a value Solarman adds later shows up without a new
release.

Free of Home Assistant on purpose: the aiohttp session comes from it.
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
import re
from typing import Any

from .model import Extra, Module, Snapshot

_LOGGER = logging.getLogger(__name__)

BASE_URL = "https://globalapi.solarmanpv.com"
TIMEOUT = 30

#: The battery's keys in Solarman's currentData, as seen on a Force H2.
KEY_FIELDS = {
    "V_BAP1": "voltage",
    "I_BAP1": "current",
    "SOC_BAP1": "soc",
    "SOH_BAP1": "soh",
    "NUMcyc1": "cycles",
}
KEY_STATE = "INFO_Bbas1"
MODULE_KEY = re.compile(r"^(?P<kind>[TV])_MDU(?P<index>\d+)$")
INTEGER_FIELDS = {"soc", "soh", "cycles"}


class CloudError(Exception):
    """The cloud did not answer, or answered with an error."""


class CloudAuthError(CloudError):
    """The app id, the app secret or the account was refused."""


def hash_password(password: str) -> str:
    """The lowercase SHA-256 hex digest the token request wants."""
    return hashlib.sha256(password.encode("utf-8")).hexdigest()


#: Words in the message of a refused login or token. Solarman's codes are not
#: published as a list, and its 2101xxx family also holds "device not found"
#: and "insufficient allowance", which a new password would not mend.
AUTH_WORDS = ("auth", "token", "password", "username", "secret", "locked")


def is_auth_refusal(message: Any) -> bool:
    text = str(message or "").lower()
    return any(word in text for word in AUTH_WORDS)


def _number(value: Any) -> float | None:
    try:
        return float(str(value).strip())
    except (TypeError, ValueError):
        return None


def snapshot_from_current(data: dict[str, Any]) -> Snapshot:
    """A Snapshot from a currentData answer for a battery device."""
    snap = Snapshot()
    modules: dict[int, Module] = {}
    for item in data.get("dataList") or []:
        if not isinstance(item, dict) or not item.get("key"):
            continue
        key = str(item["key"])
        value = item.get("value")
        if key in KEY_FIELDS:
            number = _number(value)
            field = KEY_FIELDS[key]
            if number is not None:
                setattr(snap, field, int(number) if field in INTEGER_FIELDS else number)
            continue
        if key == KEY_STATE:
            text = str(value or "").strip().lower()
            snap.state = (
                "charging" if "charg" in text and "dis" not in text
                else "discharging" if "discharg" in text
                else "idle" if text in {"idle", "standby", "static"}
                else None
            )
            snap.extras[key] = Extra(str(item.get("name") or key), value, None)
            continue
        if match := MODULE_KEY.match(key):
            number = _number(value)
            index = int(match["index"])
            module = modules.setdefault(index, Module(number=index + 1))
            if match["kind"] == "T":
                module.temperature = number
            else:
                module.voltage = number
            continue
        snap.extras[key] = Extra(str(item.get("name") or key), value, item.get("unit") or None)
    snap.modules = [modules[i] for i in sorted(modules)]
    snap.module_count = len(snap.modules) or None
    if snap.soc is not None and not 0 <= snap.soc <= 100:
        raise CloudError(f"state of charge {snap.soc} from the cloud is outside 0-100")
    snap.raw = {
        "collection_time": data.get("collectionTime"),
        "device_state": data.get("deviceState"),
        "keys": sorted(
            str(i.get("key")) for i in data.get("dataList") or [] if isinstance(i, dict)
        ),
    }
    return snap


class SolarmanCloud:
    """A small client for Solarman's OpenAPI."""

    def __init__(self, session, app_id: str, app_secret: str, account: str,
                 password_sha256: str, org_id: str | None = None,
                 base_url: str | None = None) -> None:
        self._session = session
        self._app_id = app_id
        self._app_secret = app_secret
        self._account = account
        self._password = password_sha256
        self._org_id = org_id or None
        self._base = (base_url or BASE_URL).rstrip("/")
        self._token: str | None = None
        self.calls = 0
        self.failures = 0

    async def _post(self, path: str, body: dict, params: dict | None = None,
                    authed: bool = True) -> dict:
        headers = {"Content-Type": "application/json"}
        if authed:
            if self._token is None:
                await self.authenticate()
            headers["Authorization"] = f"bearer {self._token}"
        self.calls += 1
        try:
            async with asyncio.timeout(TIMEOUT):
                async with self._session.post(f"{self._base}{path}", json=body, params=params,
                                              headers=headers) as resp:
                    status = resp.status
                    try:
                        data = await resp.json(content_type=None)
                    except ValueError:
                        data = None
        except (TimeoutError, OSError) as err:
            self.failures += 1
            raise CloudError(f"{path}: {err!r}") from err
        except Exception as err:  # aiohttp.ClientError and the like
            self.failures += 1
            raise CloudError(f"{path}: {err!r}") from err
        if status == 401:
            raise CloudAuthError(f"{path}: refused (401)")
        if status >= 400 or not isinstance(data, dict):
            self.failures += 1
            raise CloudError(f"{path}: HTTP {status}")
        if data.get("success") is False:
            code, msg = data.get("code"), data.get("msg")
            if is_auth_refusal(msg):
                raise CloudAuthError(f"{path}: {code} {msg}")
            self.failures += 1
            raise CloudError(f"{path}: {code} {msg}")
        return data

    async def authenticate(self) -> None:
        body: dict[str, Any] = {"appSecret": self._app_secret, "password": self._password}
        body["email" if "@" in self._account else "username"] = self._account
        if self._org_id:
            body["orgId"] = self._org_id
        data = await self._post("/account/v1.0/token", body,
                                params={"appId": self._app_id, "language": "en"}, authed=False)
        token = data.get("access_token")
        if not token:
            raise CloudAuthError(f"no token: {data.get('code')} {data.get('msg')}")
        self._token = str(token)

    async def _authed(self, path: str, body: dict) -> dict:
        try:
            return await self._post(path, body)
        except CloudAuthError:
            # A token that ran out: one new one, and the call once more.
            self._token = None
            return await self._post(path, body)

    async def stations(self) -> list[dict]:
        data = await self._authed("/station/v1.0/list", {"page": 1, "size": 100})
        return list(data.get("stationList") or [])

    async def devices(self, station_id: int) -> list[dict]:
        data = await self._authed("/station/v1.0/device", {"stationId": station_id})
        return list(data.get("deviceListItems") or [])

    async def batteries(self) -> list[dict]:
        """Every battery device on the account, with its station's name."""
        found = []
        for station in await self.stations():
            for device in await self.devices(station["id"]):
                if str(device.get("deviceType", "")).upper() == "BATTERY":
                    found.append({**device, "stationName": station.get("name"),
                                  "stationId": station["id"]})
        return found

    async def current(self, device_sn: str) -> dict:
        return await self._authed("/device/v1.0/currentData", {"deviceSn": device_sn})
