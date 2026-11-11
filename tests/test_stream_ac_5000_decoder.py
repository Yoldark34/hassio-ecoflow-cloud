"""The STREAM AC 5000 private-API decoder, replayed over a real two-unit pack capture.

Capture: ES22 (STREAM AC 5000) discharging ~470 W, ES21 (STREAM 5000) idle, pack at 68-69 %,
work mode Scheduled, feed-in limit 900 W, SoC limits 10-90 %.
"""

from __future__ import annotations

from typing import Any

import pytest

from custom_components.ecoflow_cloud.devices.internal.stream_ac_5000 import StreamAC5000

from .helpers import load_frames, make_device

FRAMES = load_frames("stream5000_pack_discharge.jsonl")
SERIALS = {"ES21": "ES21TEST00000001", "ES22": "ES22TEST00000001"}


def replay(prefix: str) -> dict[str, Any]:
    device = make_device(StreamAC5000, SERIALS[prefix], "STREAM_AC_5000")
    for frame in FRAMES:
        if frame["api"] == "private" and frame["device"] == SERIALS[prefix]:
            device.update_data(bytes.fromhex(frame["hex"]), device.device_info.data_topic)
    return device.data.params


@pytest.fixture(scope="module")
def es21() -> dict[str, Any]:
    return replay("ES21")


@pytest.fixture(scope="module")
def es22() -> dict[str, Any]:
    return replay("ES22")


def test_both_units_decode_their_settings(es21, es22):
    for params in (es21, es22):
        assert params["cmsMaxChgSoc"] == 90
        assert params["cmsMinDsgSoc"] == 10
        assert params["feedGridModePowLimit"] == 900
        assert params["chgPowLimit"] == 3000
        assert params["workMode"] == 2
        assert params["cmsBattFullEnergy"] == 5008


def test_battery_power_is_per_unit(es21, es22):
    # bpPower is an unsigned magnitude of each unit's own battery
    assert es22["bpPower"] > 400
    assert es21["bpPower"] < 50


def test_only_the_unit_holding_the_meter_reports_it(es21, es22):
    assert es21["meterLinkUp"] == 1
    assert "meterTotalPower" in es21
    assert es22["meterLinkUp"] == 0
    assert "meterTotalPower" not in es22


def test_state_of_charge_scales(es21, es22):
    for params in (es21, es22):
        assert 60 <= params["packSoc"] <= 75
        assert 60 <= params["f32ShowSoc"] <= 75


def test_status_tracker_sees_the_unit_online():
    device = make_device(StreamAC5000, SERIALS["ES22"], "STREAM_AC_5000")
    frame = next(f for f in FRAMES if f["api"] == "private" and f["device"] == SERIALS["ES22"])
    device.update_data(bytes.fromhex(frame["hex"]), device.device_info.data_topic)
    assert device.status_tracker.is_online


def test_battery_power_is_signed_watts(es21, es22):
    # block 44 field 2 is a zigzag sint32, so a discharging unit reads negative
    assert es22["batteryPower"] < -400
    assert es22["bpPower"] == abs(es22["batteryPower"])
    assert abs(es21["batteryPower"]) < 50


def test_roles_of_the_pack(es21, es22):
    assert es21["systemRole"] == 1  # master
    assert es22["systemRole"] == 2  # slave
    assert es21["systemGroupId"] == es22["systemGroupId"]
    assert es21["systemDevCnt"] == es22["systemDevCnt"] == 2


def test_pack_values_use_the_open_api_names(es21, es22):
    for params in (es21, es22):
        assert params["bpBackupConfig.backupSocOnOff"] is False
        assert params["bpBackupConfig.backupSoc"] == 10
        assert 60 <= params["sysEnergyStreamReport.bpSoc"] <= 75
        # the pack discharges into the house
        assert params["sysEnergyStreamReport.bpPwr"] < -300
        assert params["sysEnergyStreamReport.onGridPwr"] > 300


def test_the_master_keeps_its_own_entry_of_the_unit_lists(es21):
    # blocks 50/54 list both units; the last entry (ES22, discharging) used to overwrite ES21's
    assert abs(es21["gridPortPower"]) < 50
    assert es21["unitInverterPower"] < 50
    other = f"unit.{SERIALS['ES22']}."
    assert es21[other + "gridPortPower"] < -300
    assert es21[other + "unitInverterPower"] > 300
    assert 60 <= es21[other + "soc"] <= 75


def test_a_slave_sends_no_unit_list(es22):
    assert not any(key.startswith("unit.") for key in es22)
