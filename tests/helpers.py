"""Builders shared by the tests: devices without a broker, and replay of recorded frames."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

from custom_components.ecoflow_cloud.device_data import DeviceData, DeviceOptions
from custom_components.ecoflow_cloud.devices import BaseDevice, EcoflowDeviceInfo

FIXTURES = Path(__file__).parent / "fixtures"


def options(**overrides: Any) -> DeviceOptions:
    values: dict[str, Any] = {
        "refresh_period": 5,
        "power_step": 100,
        "diagnostic_mode": False,
        "verbose_status_mode": False,
        "assume_offline_sec": 300,
        "reset_sensors_on_offline": True,
        "energy_update_interval": 0,
    }
    values.update(overrides)
    return DeviceOptions(**values)


def private_info(sn: str, device_type: str, user_id: str = "1") -> EcoflowDeviceInfo:
    return EcoflowDeviceInfo(
        public_api=False,
        sn=sn,
        name=f"{device_type}-{sn[-4:]}",
        device_type=device_type,
        status=-1,
        data_topic=f"/app/device/property/{sn}",
        set_topic=f"/app/{user_id}/{sn}/thing/property/set",
        set_reply_topic=f"/app/{user_id}/{sn}/thing/property/set_reply",
        get_topic=f"/app/{user_id}/{sn}/thing/property/get",
        get_reply_topic=f"/app/{user_id}/{sn}/thing/property/get_reply",
    )


def make_device(cls: type[BaseDevice], sn: str, device_type: str, **opts: Any) -> BaseDevice:
    data = DeviceData(sn, f"{device_type}-{sn[-4:]}", device_type, options(**opts), None, None)
    return cls(private_info(sn, device_type), data)


def fake_client() -> MagicMock:
    client = MagicMock()
    client.has_open_api = False
    client.mqtt_client.is_connected.return_value = True
    client.schedule_mqtt_reconnect.return_value = None
    return client


def load_frames(name: str) -> list[dict[str, Any]]:
    return [json.loads(line) for line in (FIXTURES / name).read_text().splitlines() if line.strip()]


def detach(entity: Any) -> Any:
    """Let an entity update its state without being added to hass."""
    entity.schedule_update_ha_state = lambda *args, **kwargs: None
    return entity


def replay(devices: dict[str, BaseDevice], frames: list[dict[str, Any]], api: str = "private") -> None:
    """Feed recorded frames to the device whose serial they carry, in capture order."""
    for frame in frames:
        device = devices.get(frame["device"])
        if device is None or frame["api"] != api:
            continue
        topic = device.device_info.data_topic if api == "private" else device.device_info.open_data_topic
        assert topic, f"{frame['device']} has no {api} data topic"
        device.update_data(bytes.fromhex(frame["hex"]), topic)
