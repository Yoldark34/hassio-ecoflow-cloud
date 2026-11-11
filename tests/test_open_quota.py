"""Open-API quota, pushed nested over MQTT or flattened with '-' over HTTP, lands on the app-API keys."""

from __future__ import annotations

from custom_components.ecoflow_cloud.devices.internal.stream_ac_5000 import StreamAC5000, flatten_open_quota

from .helpers import load_frames, make_device, replay

SN = "ES22TEST00000001"


def _device() -> StreamAC5000:
    device = make_device(StreamAC5000, SN, "STREAM_AC_5000")
    device.device_info.open_data_topic = f"/open/acct/{SN}/quota"
    return device  # type: ignore[return-value]


def test_http_and_mqtt_shapes_flatten_alike():
    http = {"sysEnergyStreamReport-bpPwr": -406, "bpBackupConfig-backupSoc": 10}
    mqtt = {"sysEnergyStreamReport": {"bpPwr": -406}, "bpBackupConfig": {"backupSoc": 10}}
    assert flatten_open_quota(http) == flatten_open_quota(mqtt) == {
        "sysEnergyStreamReport.bpPwr": -406,
        "bpBackupConfig.backupSoc": 10,
    }


def test_work_mode_and_socket_use_the_app_values():
    params = _device().open_quota_params(
        {"workMode": "TIMER_TASK", "devSwitch-acSocketOnoff": False, "powerParameterConfig-feedToGridLimitOnOff": True}
    )
    assert params == {"workMode": 2, "acOutEnabled": 0, "powerParameterConfig.feedToGridLimitOnOff": True}


def test_recorded_open_pushes():
    device = _device()
    replay({SN: device}, load_frames("stream5000_pack_discharge.jsonl"), api="public")
    params = device.data.params
    assert 60 <= params["sysEnergyStreamReport.bpSoc"] <= 75
    assert params["sysEnergyStreamReport.bpPwr"] < -300
    assert params["workMode"] == 2
    assert params["bpBackupConfig.backupSoc"] == 10
    assert device.status_tracker.is_online


def test_open_status_push_marks_the_unit_offline():
    device = _device()
    device.device_info.open_status_topic = f"/open/acct/{SN}/status"
    device.update_data(b'{"params": {"status": 0}}', device.device_info.open_status_topic)
    assert device.status_tracker.is_offline
