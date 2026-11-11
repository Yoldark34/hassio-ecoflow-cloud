"""A pack of two STREAM units, fed with the recorded capture: shared values, master, status, routing."""

from __future__ import annotations

import json
from unittest.mock import MagicMock

import pytest

from custom_components.ecoflow_cloud.api import EcoflowSystem
from custom_components.ecoflow_cloud.api.hybrid_api import EcoflowHybridApiClient
from custom_components.ecoflow_cloud.api.message import OpenAPICommand
from custom_components.ecoflow_cloud.api.private_api import EcoflowPrivateApiClient
from custom_components.ecoflow_cloud.devices.internal.stream_ac_5000 import StreamAC5000CommandMessage, StreamAC5000
from custom_components.ecoflow_cloud.devices.data_holder import PreparedData
from custom_components.ecoflow_cloud.devices.internal.stream_pack import StreamPack, build_packs
from custom_components.ecoflow_cloud.number import MinMaxLevelEntity
from custom_components.ecoflow_cloud.select import PowerDictSelectEntity

from .helpers import fake_client, load_frames, make_device, replay

ES21, ES22 = "ES21TEST00000001", "ES22TEST00000001"
FRAMES = load_frames("stream5000_pack_discharge.jsonl")


def _system(main_sn: str | None = ES21) -> EcoflowSystem:
    return EcoflowSystem("200", "Système STREAM 0001", [ES21, ES22], main_sn, {ES21: True, ES22: True})


@pytest.fixture
def units() -> dict[str, StreamAC5000]:
    return {sn: make_device(StreamAC5000, sn, "STREAM_AC_5000") for sn in (ES21, ES22)}  # type: ignore[misc]


@pytest.fixture
def pack(units) -> StreamPack:
    (pack,) = build_packs([_system()], dict(units))
    replay(dict(units), FRAMES)
    return pack


def test_a_pack_needs_two_configured_units(units):
    assert build_packs([_system()], {ES22: units[ES22]}) == []


def test_pack_carries_the_shared_values(pack):
    params = pack.data.params
    assert 60 <= params["sysEnergyStreamReport.bpSoc"] <= 75
    assert params["sysEnergyStreamReport.bpPwr"] < -300
    assert params["bpBackupConfig.backupSoc"] == 10
    assert params["cmsMaxChgSoc"] == 90
    assert params["workMode"] == 2
    assert params["systemDevCnt"] == 2
    # the meter hangs off ES21 only, ES22's empty block must not hide it
    assert params["meterLinkUp"] == 1
    assert "meterTotalPower" in params
    # per-unit values stay on the units
    assert "batteryPower" not in params
    assert "soc" not in params


def test_master_comes_from_the_units_roles(pack):
    assert pack.master_sn() == ES21
    assert pack.data.params["masterSn"] == ES21


def test_master_falls_back_to_the_app_main_unit(units):
    (pack,) = build_packs([_system(main_sn=ES22)], dict(units))
    assert pack.master_sn() == ES22


def test_status_and_write_target_follow_the_units(pack, units):
    assert pack.pack_state() == "ready"
    assert pack.target_sn() == ES21
    units[ES21].status_tracker.on_explicit_status(False)
    assert pack.pack_state() == "degraded"
    assert pack.target_sn() == ES22  # any unit applies a pack setting
    units[ES22].status_tracker.on_explicit_status(False)
    assert pack.pack_state() == "offline"
    assert pack.status_tracker.is_offline


async def test_units_drop_the_shared_entities_in_a_pack(hass, pack, units):
    for device in (*units.values(), pack):
        device.configure(hass)
    client = fake_client()
    unit_keys = {e.mqtt_key for e in units[ES22].sensors(client) if hasattr(e, "mqtt_key")}
    assert "batteryPower" in unit_keys
    assert "systemRole" in unit_keys
    assert "sysEnergyStreamReport.bpSoc" not in unit_keys
    assert units[ES22].numbers(client) == []
    pack_keys = {e.mqtt_key for e in pack.sensors(client) if hasattr(e, "mqtt_key")}
    assert {"sysEnergyStreamReport.bpSoc", "masterSn", "meterTotalPower"} <= pack_keys


def _number(pack, client, key):
    return next(e for e in pack.numbers(client) if e.mqtt_key == key)


async def test_pack_writes_go_to_the_master_over_the_app_api(hass, pack):
    pack.configure(hass)
    command = _number(pack, fake_client(), "bpBackupConfig.backupSoc").command_dict(20)
    assert isinstance(command, StreamAC5000CommandMessage)
    assert command.target_sn == ES21
    assert command.to_dict()["StreamAC5000SendCommandMsg"]["msg"]["pdata"] == {
        "StreamAC5000SetCommand": {"propertyId": 30, "bpBackupConfig": {"backupSoc": 20}}
    }


async def test_pack_writes_prefer_the_open_api(hass, pack):
    pack.configure(hass)
    client = fake_client()
    client.has_open_api = True
    command = _number(pack, client, "bpBackupConfig.backupSoc").command_dict(20)
    assert isinstance(command, OpenAPICommand)
    assert command.target_sn == ES21
    payload = json.loads(command.to_mqtt_payload())
    assert payload["params"] == {"bpBackupConfig": {"backupSoc": 20}}
    assert (payload["cmdId"], payload["cmdFunc"], payload["sn"]) == (38, 254, ES21)
    mode = next(e for e in pack.selects(client) if isinstance(e, PowerDictSelectEntity))
    assert json.loads(mode.command_dict(0).to_mqtt_payload())["params"] == {"workMode": "SELF_CONSUMPTION"}


def _wire(client, units, pack):
    client.devices = {**units, pack.device_info.sn: pack}
    client.mqtt_client = MagicMock()


async def test_client_publishes_a_pack_write_on_the_target_unit_topic(hass, pack, units):
    client = EcoflowPrivateApiClient("api-e.ecoflow.com", "u", "p", "Home")
    _wire(client, units, pack)
    pack.configure(hass)
    entity = _number(pack, client, "bpBackupConfig.backupSoc")
    client.send_set_message(pack.device_info.sn, {"'bpBackupConfig.backupSoc'": 20}, entity.command_dict(20))
    topic = client.mqtt_client.publish.call_args.args[0]
    assert topic == units[ES21].device_info.set_topic
    # shown at once on the pack, before the units confirm it
    assert pack.data.params["bpBackupConfig.backupSoc"] == 20


async def test_hybrid_client_sends_open_commands_on_the_open_broker(hass, pack, units):
    client = EcoflowHybridApiClient("api-e.ecoflow.com", "u", "p", "Home", "api-e.ecoflow.com", "ak", "sk")
    _wire(client, units, pack)
    client.open_mqtt_client = MagicMock()
    for unit in units.values():
        unit.device_info.open_set_topic = f"/open/acct/{unit.device_info.sn}/set"
    command = OpenAPICommand(ES21, {"cmdId": 38}, {"workMode": "AI_MODE"})
    client.send_set_message(pack.device_info.sn, {"'workMode'": 1}, command)
    client.open_mqtt_client.publish.assert_called_once()
    assert client.open_mqtt_client.publish.call_args.args[0] == f"/open/acct/{ES21}/set"
    client.mqtt_client.publish.assert_not_called()


async def test_quota_requests_skip_the_pack(hass, pack, units):
    client = EcoflowPrivateApiClient("api-e.ecoflow.com", "u", "p", "Home")
    _wire(client, units, pack)
    await client.quota_all(None)
    topics = [call.args[0] for call in client.mqtt_client.publish.call_args_list]
    assert sorted(topics) == sorted(u.device_info.get_topic for u in units.values())


def test_the_pack_hands_each_unit_its_entry_from_the_master(pack, units):
    slave = units[ES22].data.params
    assert slave["gridPortPower"] < -300
    assert slave["unitInverterPower"] > 300
    assert 60 <= slave["soc"] <= 75
    assert abs(units[ES21].data.params["gridPortPower"]) < 50


async def test_solar_sensors_only_on_units_with_solar_inputs(hass, pack, units):
    for device in units.values():
        device.configure(hass)
    client = fake_client()

    def enabled_keys(device):
        return {e.mqtt_key for e in device.sensors(client) if getattr(e, "enabled_default", False)}

    assert {"unitPvPower", "pv1Power", "pv4Power"} <= enabled_keys(units[ES21])
    assert not any(k.startswith(("pv", "unitPv")) for k in enabled_keys(units[ES22]))
    assert {"unitOnGridPower", "remainCap", "batteryPower"} <= enabled_keys(units[ES22])


async def test_a_room_of_the_app_becomes_the_suggested_area(hass, pack, units):
    from custom_components.ecoflow_cloud.sensor import WattsSensorEntity

    units[ES21].configure(hass)
    units[ES22].configure(hass)
    units[ES21].suggested_area = "Garage"
    in_room = WattsSensorEntity(fake_client(), units[ES21], "batteryPower", "Battery Power").device_info
    no_room = WattsSensorEntity(fake_client(), units[ES22], "batteryPower", "Battery Power").device_info
    assert in_room["suggested_area"] == "Garage"
    assert "suggested_area" not in no_room
    assert in_room["via_device"] == ("ecoflow_cloud", pack.device_info.sn)


def test_roles_start_from_the_app_main_unit(units):
    (pack,) = build_packs([_system(main_sn=ES21)], dict(units))
    assert units[ES21].data.params["systemRole"] == 1
    assert units[ES22].data.params["systemRole"] == 2
    assert pack.data.params["masterSn"] == ES21
    # a unit's own report wins
    units[ES22].data.add_data(PreparedData(None, {"params": {"systemRole": 1}}, None))
    units[ES21].data.add_data(PreparedData(None, {"params": {"systemRole": 2}}, None))
    assert pack.master_sn() == ES22
    assert pack.data.params["masterSn"] == ES22


def test_pack_counters_sum_the_units_own(pack, units):
    for key in ("accuChgEnergy", "accuDsgEnergy"):
        assert pack.data.params[key] == sum(u.data.params[key] for u in units.values())


def test_pack_counter_never_goes_down(pack, units):
    before = pack.data.params["accuChgEnergy"]
    units[ES22].data.add_data(PreparedData(None, {"params": {"accuChgEnergy": 1}}, None))
    assert pack.data.params["accuChgEnergy"] == before


async def test_the_pack_counts_energy_with_its_units_counters(hass, pack):
    pack.configure(hass)
    keys = {getattr(e, "mqtt_key", None) for e in pack.sensors(fake_client())}
    assert {"accuChgEnergy", "accuDsgEnergy"} <= keys
