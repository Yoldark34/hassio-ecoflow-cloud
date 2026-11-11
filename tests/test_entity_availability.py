"""What a data entity shows once its device stops reporting."""

from __future__ import annotations

import pytest

from custom_components.ecoflow_cloud.devices.data_coordinator import EcoflowBroadcastDataHolder
from custom_components.ecoflow_cloud.devices.internal.stream_ac_5000 import StreamAC5000
from custom_components.ecoflow_cloud.sensor import WattsSensorEntity

from .helpers import detach, fake_client, make_device


def _sensor(hass, **opts):
    device = make_device(StreamAC5000, "ES22TEST00000001", "STREAM_AC_5000", **opts)
    device.configure(hass)
    device.data.params["bpPower"] = 470.0
    sensor = detach(WattsSensorEntity(fake_client(), device, "bpPower", "Battery Power"))
    sensor._updated(device.data.params)
    return device, sensor


def _tick(device, changed: bool):
    device.coordinator.data = EcoflowBroadcastDataHolder(device.data, changed)


async def test_reporting_device_is_available(hass):
    device, sensor = _sensor(hass)
    device.status_tracker.on_data_received()
    _tick(device, changed=False)
    sensor._handle_coordinator_update()
    assert sensor.available
    assert sensor.native_value == 470.0


@pytest.mark.xfail(strict=True, reason="entities never leave available once set")
async def test_offline_device_turns_unavailable(hass):
    device, sensor = _sensor(hass)
    device.status_tracker.on_explicit_status(False)
    _tick(device, changed=False)
    sensor._handle_coordinator_update()
    assert not sensor.available


async def test_device_back_online_is_available_again(hass):
    device, sensor = _sensor(hass)
    device.status_tracker.on_explicit_status(False)
    _tick(device, changed=False)
    sensor._handle_coordinator_update()
    device.status_tracker.on_data_received()
    _tick(device, changed=True)
    sensor._handle_coordinator_update()
    assert sensor.available
