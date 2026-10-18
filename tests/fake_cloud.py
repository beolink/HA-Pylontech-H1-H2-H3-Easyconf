"""A stand-in for Solarman's OpenAPI on a loopback port (aiohttp).

It answers the four calls the integration makes, with a station holding a
Force H2 battery and an inverter, and can refuse the credentials or the token
the way the real API does: HTTP 200 with success false and a 2101xxx code.
"""

from __future__ import annotations

import hashlib

from aiohttp import web

PASSWORD = "hemligt"
APP_ID = "1234567890"
APP_SECRET = "s3cr3t"
ACCOUNT = "owner@example.com"
BATTERY_SN = "BT2410123456"

DATA_LIST = [
    {"key": "V_BAP1", "name": "Battery Voltage", "value": "196.4", "unit": "V"},
    {"key": "I_BAP1", "name": "Battery Current", "value": "-3.20", "unit": "A"},
    {"key": "SOC_BAP1", "name": "SoC", "value": "57", "unit": "%"},
    {"key": "SOH_BAP1", "name": "SoH", "value": "97", "unit": "%"},
    {"key": "NUMcyc1", "name": "Cycles", "value": "684", "unit": None},
    {"key": "INFO_Bbas1", "name": "Battery Status", "value": "Discharging", "unit": None},
    {"key": "T_MDU0", "name": "Module 0 Temperature", "value": "25.7", "unit": "℃"},
    {"key": "T_MDU1", "name": "Module 1 Temperature", "value": "27.2", "unit": "℃"},
    {"key": "V_MDU0", "name": "Module 0 Voltage", "value": "98.21", "unit": "V"},
    {"key": "V_MDU1", "name": "Module 1 Voltage", "value": "98.19", "unit": "V"},
    {"key": "MAX_CV1", "name": "Max Cell Voltage", "value": "3.281", "unit": "V"},
    {"key": "B_ST1", "name": "BMS State", "value": "Normal", "unit": None},
]


class FakeSolarman:
    def __init__(self) -> None:
        self.token = "token-1"
        self.refuse_login = False
        self.expire_token = False
        self.calls: list[str] = []
        self.data_list = list(DATA_LIST)
        self.url = ""
        self._runner: web.AppRunner | None = None

    async def __aenter__(self) -> FakeSolarman:
        app = web.Application()
        app.router.add_post("/account/v1.0/token", self._token)
        app.router.add_post("/station/v1.0/list", self._stations)
        app.router.add_post("/station/v1.0/device", self._devices)
        app.router.add_post("/device/v1.0/currentData", self._current)
        self._runner = web.AppRunner(app)
        await self._runner.setup()
        site = web.TCPSite(self._runner, "127.0.0.1", 0)
        await site.start()
        port = site._server.sockets[0].getsockname()[1]
        self.url = f"http://127.0.0.1:{port}"
        return self

    async def __aexit__(self, *exc) -> None:
        if self._runner is not None:
            await self._runner.cleanup()

    @staticmethod
    def _refused(code: str = "2101019", msg: str = "auth invalid token"):
        return web.json_response({"success": False, "code": code, "msg": msg})

    async def _token(self, request: web.Request) -> web.Response:
        self.calls.append("token")
        body = await request.json()
        good = (
            request.query.get("appId") == APP_ID
            and body.get("appSecret") == APP_SECRET
            and body.get("email") == ACCOUNT
            and body.get("password") == hashlib.sha256(PASSWORD.encode()).hexdigest()
            and not self.refuse_login
        )
        if not good:
            return self._refused("2101006", "auth invalid username or password")
        self.expire_token = False
        return web.json_response({"success": True, "access_token": self.token,
                                  "token_type": "bearer", "expires_in": "5183999"})

    def _authed(self, request: web.Request) -> bool:
        return (not self.expire_token
                and request.headers.get("Authorization") == f"bearer {self.token}")

    async def _stations(self, request: web.Request) -> web.Response:
        self.calls.append("stations")
        if not self._authed(request):
            return self._refused()
        return web.json_response({"success": True, "stationList": [{"id": 4711, "name": "Hemma"}]})

    async def _devices(self, request: web.Request) -> web.Response:
        self.calls.append("devices")
        if not self._authed(request):
            return self._refused()
        return web.json_response({"success": True, "deviceListItems": [
            {"deviceSn": "LOG2712345678", "deviceType": "COLLECTOR"},
            {"deviceSn": "INV2203011234", "deviceType": "INVERTER"},
            {"deviceSn": BATTERY_SN, "deviceType": "BATTERY", "deviceModel": "Force_H2"},
        ]})

    async def _current(self, request: web.Request) -> web.Response:
        self.calls.append("current")
        if not self._authed(request):
            return self._refused()
        body = await request.json()
        if body.get("deviceSn") != BATTERY_SN:
            return web.json_response(
                {"success": False, "code": "2101030", "msg": "device not found"}
            )
        return web.json_response({"success": True, "deviceSn": BATTERY_SN, "deviceType": "BATTERY",
                                  "collectionTime": 1792300000, "dataList": self.data_list})
