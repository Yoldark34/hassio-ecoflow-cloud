"""Config flow: hybrid entry with discovered devices, and developer keys added to an app-API entry."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest
from homeassistant import config_entries
from homeassistant.data_entry_flow import FlowResultType
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.ecoflow_cloud import CONFIG_VERSION, ECOFLOW_DOMAIN
from custom_components.ecoflow_cloud.api import EcoflowSpace
from custom_components.ecoflow_cloud.config_flow import APP_API_HOSTS, OPEN_API_HOSTS, _host_selector
from custom_components.ecoflow_cloud.devices import EcoflowDeviceInfo

from .helpers import private_info

ES21, ES22, ES81 = "ES21TEST00000001", "ES22TEST00000001", "ES81TEST00000001"


def _found() -> list[EcoflowDeviceInfo]:
    devices = []
    for sn, name, kind in (
        (ES22, "STREAM AC 5000-0001", "STREAM_AC_5000"),
        (ES21, "STREAM 5000-0001", "STREAM_AC_5000"),
        (ES81, "Smart Meter Dual CT-0001", "DIAGNOSTIC"),
    ):
        info = private_info(sn, kind)
        info.name = name
        devices.append(info)
    return devices


async def _login(self):
    self.user_id = "42"


HOME = {ES21: EcoflowSpace("100", "Ma maison", True), ES22: EcoflowSpace("100", "Ma maison", True)}
PRIVATE = "custom_components.ecoflow_cloud.api.private_api.EcoflowPrivateApiClient"


@pytest.fixture(autouse=True)
def no_setup():
    with patch("custom_components.ecoflow_cloud.async_setup_entry", return_value=True):
        yield


def test_region_options_show_their_host():
    labels = {o["value"]: o["label"] for o in _host_selector(APP_API_HOSTS).config["options"]}
    assert labels == {"api-e.ecoflow.com": "EU - api-e.ecoflow.com", "api.ecoflow.com": "US - api.ecoflow.com"}
    labels = {o["value"]: o["label"] for o in _host_selector(OPEN_API_HOSTS).config["options"]}
    assert labels["api-a.ecoflow.com"] == "US - api-a.ecoflow.com"


async def test_hybrid_entry_adds_the_discovered_devices(hass):
    with (
        patch("custom_components.ecoflow_cloud.api.hybrid_api.EcoflowHybridApiClient.login", _login),
        patch(
            "custom_components.ecoflow_cloud.api.hybrid_api.EcoflowHybridApiClient.fetch_all_available_devices",
            AsyncMock(return_value=_found()),
        ),
        patch(f"{PRIVATE}.fetch_device_spaces", AsyncMock(return_value=HOME)),
    ):
        result = await hass.config_entries.flow.async_init(ECOFLOW_DOMAIN, context={"source": config_entries.SOURCE_USER})
        # no name to invent: the API comes first
        assert result["type"] is FlowResultType.MENU
        assert result["menu_options"][0] == "hybrid"
        result = await hass.config_entries.flow.async_configure(result["flow_id"], {"next_step_id": "hybrid"})
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            {
                "api_host": "api-e.ecoflow.com",
                "username": "me@example.com",
                "password": "pw",
                "open_api_host": "api-e.ecoflow.com",
                "access_key": " ak ",
                "secret_key": "sk",
            },
        )
        assert result["step_id"] == "discover_devices"
        schema = result["data_schema"].schema
        default = next(k for k in schema if k == "devices").default()
        # the meter cannot be read, so it is not even offered; both batteries come preselected
        assert sorted(default) == [ES21, ES22]
        assert next(k for k in schema if k == "auto_add_devices").default() is True
        result = await hass.config_entries.flow.async_configure(result["flow_id"], {"devices": default})

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "Ma maison"
    assert result["result"].unique_id == "account-42"
    assert result["data"]["auto_add_devices"] is True
    data = result["data"]
    assert data["access_key"] == "ak"
    assert data["username"] == "me@example.com"
    assert data["devices_list"][ES22] == {"device_name": "STREAM AC 5000-0001", "device_type": "STREAM_AC_5000"}
    assert set(result["options"]["devices_list"]) == {ES21, ES22}


async def test_keys_turn_an_app_entry_hybrid_and_retype_its_units(hass):
    entry = MockConfigEntry(
        domain=ECOFLOW_DOMAIN,
        version=CONFIG_VERSION,
        unique_id="group-Home",
        title="Home",
        data={
            "group": "Home",
            "api_host": "api-e.ecoflow.com",
            "username": "me@example.com",
            "password": "pw",
            "devices_list": {ES22: {"device_name": "My AC", "device_type": "STREAM_AC"}},
        },
        options={"devices_list": {ES22: {"refresh_period_sec": 5, "power_step": 100, "diagnostic_mode": False,
                                         "verbose_status_mode": False, "assume_offline_sec": 300,
                                         "reset_sensors_on_offline": True}}},
    )
    entry.add_to_hass(hass)
    private = PRIVATE
    with (
        patch(f"{private}.login", _login),
        patch(f"{private}.fetch_all_available_devices", AsyncMock(return_value=_found())),
        patch("custom_components.ecoflow_cloud.api.public_api.EcoflowPublicApiClient.login", AsyncMock()),
    ):
        result = await entry.start_reconfigure_flow(hass)
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {"api_host": "api-e.ecoflow.com", "username": "me@example.com", "password": "pw"}
        )
        assert "open_api_keys" in result["menu_options"]
        result = await hass.config_entries.flow.async_configure(result["flow_id"], {"next_step_id": "discover_devices"})
        default = next(k for k in result["data_schema"].schema if k == "devices").default()
        assert sorted(default) == [ES21, ES22]  # ES22 is configured with another type
        result = await hass.config_entries.flow.async_configure(result["flow_id"], {"devices": default})
        assert result["reason"] == "reconfigure_successful"

    assert entry.data["devices_list"][ES22] == {"device_name": "My AC", "device_type": "STREAM_AC_5000"}
    assert entry.data["devices_list"][ES21]["device_type"] == "STREAM_AC_5000"
    assert "power_step" in entry.options["devices_list"][ES21]

    with (
        patch(f"{private}.login", _login),
        patch("custom_components.ecoflow_cloud.api.public_api.EcoflowPublicApiClient.login", AsyncMock()),
    ):
        result = await entry.start_reconfigure_flow(hass)
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {"api_host": "api-e.ecoflow.com", "username": "me@example.com", "password": "pw"}
        )
        result = await hass.config_entries.flow.async_configure(result["flow_id"], {"next_step_id": "open_api_keys"})
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {"open_api_host": "api-e.ecoflow.com", "access_key": "ak", "secret_key": "sk"}
        )
        assert result["reason"] == "reconfigure_successful"

    assert entry.data["access_key"] == "ak"
    assert entry.data["open_api_host"] == "api-e.ecoflow.com"
    assert entry.data["username"] == "me@example.com"


async def test_adding_an_account_that_has_an_entry_continues_as_its_reconfiguration(hass):
    # an entry from before accounts were the key: found by its email, whatever its group
    entry = MockConfigEntry(
        domain=ECOFLOW_DOMAIN,
        version=CONFIG_VERSION,
        unique_id="group-Home",
        title="Home",
        data={"group": "Home", "api_host": "api-e.ecoflow.com", "username": "Me@Example.com", "password": "old",
              "devices_list": {}},
        options={"devices_list": {}},
    )
    entry.add_to_hass(hass)
    with (
        patch("custom_components.ecoflow_cloud.api.hybrid_api.EcoflowHybridApiClient.login", _login),
        patch(
            "custom_components.ecoflow_cloud.api.hybrid_api.EcoflowHybridApiClient.fetch_all_available_devices",
            AsyncMock(return_value=_found()),
        ),
    ):
        result = await hass.config_entries.flow.async_init(ECOFLOW_DOMAIN, context={"source": config_entries.SOURCE_USER})
        result = await hass.config_entries.flow.async_configure(result["flow_id"], {"next_step_id": "hybrid"})
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            {"api_host": "api-e.ecoflow.com", "username": "me@example.com", "password": "new",
             "open_api_host": "api-e.ecoflow.com", "access_key": "ak", "secret_key": "sk"},
        )
        # straight to that entry's menu, already hybrid: no keys to add any more
        assert result["type"] is FlowResultType.MENU
        assert "open_api_keys" not in result["menu_options"]
        result = await hass.config_entries.flow.async_configure(result["flow_id"], {"next_step_id": "discover_devices"})
        result = await hass.config_entries.flow.async_configure(result["flow_id"], {"devices": [ES22]})
    assert result["reason"] == "reconfigure_successful"
    assert len(hass.config_entries.async_entries(ECOFLOW_DOMAIN)) == 1
    assert entry.data["password"] == "new"
    assert entry.data["access_key"] == "ak"
    assert list(entry.data["devices_list"]) == [ES22]


async def test_new_account_devices_are_added_at_start(hass):
    from custom_components.ecoflow_cloud import _add_new_account_devices

    entry = MockConfigEntry(
        domain=ECOFLOW_DOMAIN,
        version=CONFIG_VERSION,
        data={"group": "Home", "username": "u", "password": "p", "api_host": "api-e.ecoflow.com",
              "auto_add_devices": True,
              "devices_list": {ES22: {"device_name": "My AC", "device_type": "STREAM_AC_5000"}}},
        options={"devices_list": {ES22: {"refresh_period_sec": 5, "power_step": 100, "diagnostic_mode": False,
                                         "verbose_status_mode": False, "assume_offline_sec": 300,
                                         "reset_sensors_on_offline": True}}},
    )
    entry.add_to_hass(hass)
    added = _add_new_account_devices(hass, entry, _found())
    # the meter's type is unknown, so it is left out
    assert list(added) == [ES21]
    assert added[ES21].device_type == "STREAM_AC_5000"
    assert set(entry.data["devices_list"]) == {ES21, ES22}
    assert entry.data["devices_list"][ES22]["device_name"] == "My AC"
    assert _add_new_account_devices(hass, entry, _found()) == {}
