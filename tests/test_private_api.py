"""App-API discovery: the account's devices with their type, and the systems that group them."""

from __future__ import annotations

from typing import Any

import pytest

from custom_components.ecoflow_cloud.api.private_api import EcoflowPrivateApiClient
from custom_components.ecoflow_cloud.devices.sn_prefixes import device_type_for

# Shapes recorded from the app API, with fake serials and ids
USER_DEVICES = {
    "code": "0",
    "data": {
        "bound": {
            "ES22TEST00000001": {"deviceName": "STREAM AC 5000-0001", "productType": 396, "online": 1},
            "ES81TEST00000001": {"deviceName": "Smart Meter Dual CT-0001", "productType": 421, "online": 1},
            "ES21TEST00000001": {"deviceName": "STREAM 5000-0001", "productType": 396, "online": 0},
        },
        "share": {"HW52TEST00000001": {"deviceName": "Smart Plug-0001", "productType": 1, "online": 1}},
    },
}
SPACE = {"code": "0", "data": {"spaceId": "100", "rootSpaceId": "100"}}
SPACE_DEVICES = {
    "code": "0",
    "data": {
        "systemList": [
            {
                "systemNo": "200",
                "systemName": "Système STREAM 0001",
                "mainSns": ["ES21TEST00000001", "ES22TEST00000001"],
                "childDeviceList": [
                    {"sn": "ES21TEST00000001", "online": 1},
                    {"sn": "ES81TEST00000001", "online": 1},
                    {"sn": "ES22TEST00000001", "online": 0},
                ],
                "systemProperty": {"systemMainSn": "ES21TEST00000001"},
            }
        ],
        "otherDeviceList": [],
    },
}


@pytest.fixture
def client(monkeypatch) -> EcoflowPrivateApiClient:
    client = EcoflowPrivateApiClient("api-e.ecoflow.com", "user", "pw", "Home")
    client.user_id = "1"
    calls: list[tuple[str, dict | None]] = []

    async def fake_call(endpoint: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        calls.append((endpoint, params))
        return {
            "/iot-devices/user/device": USER_DEVICES,
            "/app/space/getSpaceInfoBySn": SPACE,
            "/app/space/v3/all/device/list": SPACE_DEVICES,
        }[endpoint]

    monkeypatch.setattr(client, "_EcoflowPrivateApiClient__call_api", fake_call)
    client.calls = calls  # type: ignore[attr-defined]
    return client


async def test_lists_the_account_devices_with_types(client):
    devices = {d.sn: d for d in await client.fetch_all_available_devices()}
    assert devices["ES22TEST00000001"].device_type == "STREAM_AC_5000"
    assert devices["ES21TEST00000001"].device_type == "STREAM_AC_5000"
    assert devices["ES21TEST00000001"].status == 0
    assert devices["ES22TEST00000001"].status == 1
    assert devices["ES81TEST00000001"].device_type == "DIAGNOSTIC"
    assert devices["ES22TEST00000001"].name == "STREAM AC 5000-0001"
    # shared with the account, so listed as well
    assert devices["HW52TEST00000001"].device_type == "SMART_PLUG"


async def test_systems_list_the_pack_and_its_main_unit(client):
    systems = await client.fetch_systems(["ES21TEST00000001", "ES22TEST00000001"])
    assert len(systems) == 1
    system = systems[0]
    assert system.system_no == "200"
    assert system.member_sns == ["ES21TEST00000001", "ES22TEST00000001"]
    assert system.main_sn == "ES21TEST00000001"
    assert system.online == {"ES21TEST00000001": True, "ES81TEST00000001": True, "ES22TEST00000001": False}
    # both units share a space: it is listed once
    assert [c[0] for c in client.calls].count("/app/space/v3/all/device/list") == 1


@pytest.mark.parametrize(
    ("sn", "expected"),
    [
        ("ES22ZZZZZZZZ0001", "STREAM_AC_5000"),
        ("BK21ZZZZZZZZ0001", "SMART_METER"),
        ("BK11ZZZZZZZZ0001", "STREAM_AC"),
        ("R331ZZZZZZZZ0001", "DELTA_2"),
        ("ZZZZ", None),
    ],
)
def test_type_by_serial_prefix(sn, expected):
    assert device_type_for(sn) == expected
