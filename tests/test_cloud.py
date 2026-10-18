"""The Solarman cloud client and its mapping (cloud.py), against fake_cloud.py."""

import asyncio
import hashlib

import aiohttp
import pytest

from fake_cloud import ACCOUNT, APP_ID, APP_SECRET, BATTERY_SN, PASSWORD, FakeSolarman

from custom_components.pylontech_easyconf import cloud


def run(coro):
    return asyncio.run(coro)


async def _with_client(fake: FakeSolarman, action, password=PASSWORD):
    async with fake, aiohttp.ClientSession() as session:
        client = cloud.SolarmanCloud(session, APP_ID, APP_SECRET, ACCOUNT,
                                     cloud.hash_password(password), base_url=fake.url)
        return await action(client)


def test_the_password_is_hashed_as_the_api_wants():
    assert cloud.hash_password("abc") == hashlib.sha256(b"abc").hexdigest()


def test_batteries_are_found_on_the_account():
    batteries = run(_with_client(FakeSolarman(), lambda c: c.batteries()))
    assert [b["deviceSn"] for b in batteries] == [BATTERY_SN]
    assert batteries[0]["stationName"] == "Hemma"


def test_a_wrong_password_is_an_auth_error():
    with pytest.raises(cloud.CloudAuthError):
        run(_with_client(FakeSolarman(), lambda c: c.batteries(), password="fel"))


def test_an_expired_token_is_renewed_once():
    fake = FakeSolarman()

    async def go(client):
        await client.current(BATTERY_SN)
        fake.expire_token = True
        return await client.current(BATTERY_SN)

    data = run(_with_client(fake, go))
    assert data["deviceSn"] == BATTERY_SN
    assert fake.calls.count("token") == 2


def test_current_data_becomes_a_snapshot():
    data = run(_with_client(FakeSolarman(), lambda c: c.current(BATTERY_SN)))
    s = cloud.snapshot_from_current(data)
    assert (s.voltage, s.current, s.soc, s.soh, s.cycles) == (196.4, -3.2, 57, 97, 684)
    assert s.state == "discharging"
    assert [(m.number, m.voltage, m.temperature) for m in s.modules] == [
        (1, 98.21, 25.7), (2, 98.19, 27.2)]
    assert s.module_count == 2
    assert all(not m.cells for m in s.modules)
    assert set(s.extras) == {"INFO_Bbas1", "MAX_CV1", "B_ST1"}
    assert s.extras["MAX_CV1"].unit == "V"
    assert s.raw["collection_time"] == 1792300000


def test_only_a_refused_login_or_token_asks_for_new_credentials():
    assert cloud.is_auth_refusal("auth invalid username or password")
    assert cloud.is_auth_refusal("auth invalid token")
    assert not cloud.is_auth_refusal("device not found")
    assert not cloud.is_auth_refusal("appid insufficient allowance")


def test_states_from_the_cloud_text():
    def state(text):
        return cloud.snapshot_from_current(
            {"dataList": [{"key": "INFO_Bbas1", "value": text}]}).state

    assert state("Charging") == "charging"
    assert state("Discharging") == "discharging"
    assert state("Static") == "idle"
    assert state("Fault") is None


def test_an_impossible_charge_from_the_cloud_is_refused():
    with pytest.raises(cloud.CloudError):
        cloud.snapshot_from_current({"dataList": [{"key": "SOC_BAP1", "value": "250"}]})


def test_unreachable_cloud():
    async def go():
        async with aiohttp.ClientSession() as session:
            client = cloud.SolarmanCloud(session, APP_ID, APP_SECRET, ACCOUNT, "x",
                                         base_url="http://127.0.0.1:1")
            await client.batteries()

    with pytest.raises(cloud.CloudError):
        run(go())
