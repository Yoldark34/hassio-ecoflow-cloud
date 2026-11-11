"""EcoFlow STREAM AC 5000 (SN prefix ``ES22``) -- internal/App API.

Transport: MQTT topic ``/app/device/property/<SN>``, envelope protobuf
``StreamACSendHeaderMsg`` from ``proto/stream_ac_pb2.py`` -- the same envelope
every Stream device uses. Unlike the STREAM Microinverter, ``msg.pdata`` is
**not** XOR-obfuscated; it parses as plain protobuf.

Not a ``STREAM_AC`` alias: the AC 5000's telemetry (``cmd_id`` 39/40) sends
small nested blocks keyed by serial number, where ``StreamACChamp_cmd21_3`` is
flat with field numbers in the 500-1200 range. Only the ``cmd_id`` 50 pack frame
resembles the existing schema, so configuring one as ``STREAM_AC`` yields a
handful of SoC values and little else. This decoder dispatches on ``cmd_id``
rather than blind-parsing every schema, so a frame is either understood or
skipped, never mislabelled.

Field meanings were decoded from MQTT captures anchored to app readings; the
commit history carries the evidence for each. Blocks 60/61/62 (``cmd_id`` 40)
are deliberately left undecoded.
"""

import logging
from collections.abc import Callable
from typing import Any, Iterator, override

from google.protobuf.json_format import MessageToDict
from google.protobuf.message import Message as ProtoMessageRaw
from homeassistant.components.binary_sensor import BinarySensorEntity
from homeassistant.components.number import NumberEntity
from homeassistant.components.select import SelectEntity
from homeassistant.components.sensor import SensorDeviceClass, SensorEntity
from homeassistant.components.switch import SwitchEntity
from homeassistant.util import utcnow

from custom_components.ecoflow_cloud.api import EcoflowApiClient
from custom_components.ecoflow_cloud.api.message import Message, OpenAPICommand, PrivateAPIMessageProtocol
from custom_components.ecoflow_cloud.binary_sensor import MiscBinarySensorEntity
from custom_components.ecoflow_cloud.devices import BaseDevice, BaseInternalDevice, const
from custom_components.ecoflow_cloud.devices.internal.proto import stream_ac_5000_pb2, stream_ac_pb2
from custom_components.ecoflow_cloud.number import (
    ChargingPowerEntity,
    MaxBatteryLevelEntity,
    MinBatteryLevelEntity,
    MinMaxLevelEntity,
)
from custom_components.ecoflow_cloud.select import PowerDictSelectEntity
from custom_components.ecoflow_cloud.switch import EnabledEntity
from custom_components.ecoflow_cloud.sensor import (
    CumulativeCapacitySensorEntity,
    EnergySensorEntity,
    EnergyStorageSensorEntity,
    FrequencySensorEntity,
    LevelSensorEntity,
    MilliVoltSensorEntity,
    MiscSensorEntity,
    RemainSensorEntity,
    StateOfHealthSensorEntity,
    StatusSensorEntity,
    StoredEnergyFromSocSensorEntity,
    VoltSensorEntity,
    WattsSensorEntity,
)

_LOGGER = logging.getLogger(__name__)

# cmd_id -> payload message. cmd_id 40 (blocks 60/61/62) is intentionally absent.
_CMD_ID_STATUS = 2
_CMD_ID_RUNTIME = 39
_CMD_ID_PACK = 50

# Wire tag for field 1, wire type 2 -- every EcoPacket starts with it.
_ECOPACKET_TAG = 0x0A

# Property ids, as sent in pdata field 1 of a set command.
_PROP_POWER_LIMITS = 10
_PROP_AC_OUT = 19
_PROP_DEVICE_CFG = 23
_PROP_WORK_MODE = 25
_PROP_SOC_LIMITS = 29
_PROP_BACKUP = 30

# Envelope constants, copied verbatim from the app's own writes.
_SET_CMD_FUNC = 254
_SET_CMD_ID = 38
_OUT_LIMIT_FIELD4 = 4
_OUT_LIMIT_MAX = 800

# Entity keys for controls whose protobuf field name differs.
_KEY_AC_OUT = "acOutEnabled"
_KEY_XBOOST = "xboostEnabled"
_KEY_WORK_MODE = "workMode"

# Raw pack SoC. Reads above the app-facing system scale near empty, so it is kept
# on its own key rather than fighting it.
_KEY_PACK_SOC = "packSoc"

# On a P1 outage the device still sends meter block 16, but empty -- which would
# otherwise leave every meter sensor holding a stale reading.
_KEY_METER_LINK = "meterLinkUp"

# This unit's own battery, signed: >0 charging, <0 discharging.
KEY_BATTERY_POWER = "batteryPower"

# Pack membership from block 27. Role values follow the app: 0 election, 1 master, 2 slave.
KEY_SYSTEM_ROLE = "systemRole"
KEY_SYSTEM_GROUP = "systemGroupId"
KEY_SYSTEM_UNITS = "systemDevCnt"
SYSTEM_ROLES = {0: "election", 1: "master", 2: "slave"}

# Models with solar inputs, by serial prefix
SOLAR_PREFIXES = ("ES21",)

# Another unit's figures as the master lists them: unit.<sn>.<key>
UNIT_PREFIX = "unit."
# Block 50 fields of one unit, and the keys they take on that unit
UNIT_FLOW_KEYS = (
    ("gridPortPower", "gridPortPower"),
    ("pvSelfPwr", "unitPvPower"),
    ("invPwr", "unitInverterPower"),
    ("onGridPwr", "unitOnGridPower"),
    ("backupPwr", "unitBackupPower"),
    ("pv1Pwr", "pv1Power"),
    ("pv2Pwr", "pv2Power"),
    ("pv3Pwr", "pv3Power"),
    ("pv4Pwr", "pv4Power"),
)

SYS_ENERGY_FIELDS = ("loadPwr", "gridPwr", "pvPwr", "bpPwr", "bpSoc", "onGridPwr", "backupPwr")

# Work modes as the app numbers them; the open API sends their names.
WORK_MODES = {"SELF_CONSUMPTION": 0, "AI_MODE": 1, "TIMER_TASK": 2, "POU_MODE": 3, "EMERGENCY_STOP": 4}


class RoleSensorEntity(MiscSensorEntity):
    """A unit's role in its pack, as the units elect it among themselves."""

    _attr_device_class = SensorDeviceClass.ENUM
    _attr_options = list(SYSTEM_ROLES.values())
    _attr_icon = "mdi:crown-outline"

    def _update_value(self, val: Any) -> bool:
        return super()._update_value(SYSTEM_ROLES.get(int(val)))


def flatten_open_quota(quota: dict[str, Any], prefix: str = "") -> dict[str, Any]:
    """Open-API quota as flat dotted keys: MQTT pushes it nested, HTTP joins levels with '-'."""
    flat: dict[str, Any] = {}
    for key, value in quota.items():
        name = f"{prefix}{key.replace('-', '.')}"
        if isinstance(value, dict):
            flat.update(flatten_open_quota(value, f"{name}."))
        else:
            flat[name] = value
    return flat


class StreamAC5000CommandMessage(PrivateAPIMessageProtocol):
    """One property write, in the envelope the EcoFlow app uses."""

    def __init__(self, device_sn: str, payload: ProtoMessageRaw):
        self.target_sn = device_sn
        self._payload = payload
        self._packet = stream_ac_5000_pb2.StreamAC5000SendCommandMsg()
        message = self._packet.msg

        pdata = payload.SerializeToString()
        message.pdata = pdata
        message.data_len = len(pdata)

        message.src = 32
        message.dest = 2
        message.d_src = 1
        message.d_dest = 1
        message.check_type = 3
        message.need_ack = 1
        message.version = 4
        message.seq = Message.gen_seq()
        message.cmd_func = _SET_CMD_FUNC
        message.cmd_id = _SET_CMD_ID
        message.from_ = "HomeAssistant"
        # The app repeats the serial in all three of these.
        message.device_sn = device_sn
        message.device_sn_2 = device_sn
        message.device_sn_3 = device_sn

    @override
    def to_mqtt_payload(self) -> Any:
        return self._packet.SerializeToString()

    @override
    def to_dict(self) -> dict:
        result = MessageToDict(self._packet, preserving_proto_field_name=True)
        result["msg"]["pdata"] = {
            type(self._payload).__name__: MessageToDict(self._payload, preserving_proto_field_name=True)
        }
        result["msg"].pop("seq", None)
        return {type(self._packet).__name__: result}


def _read_varint(buf: bytes, pos: int) -> tuple[int, int]:
    shift = 0
    result = 0
    while True:
        if pos >= len(buf):
            raise ValueError("truncated varint")
        byte = buf[pos]
        pos += 1
        result |= (byte & 0x7F) << shift
        shift += 7
        if not byte & 0x80:
            return result, pos
        if shift > 63:
            raise ValueError("varint too long")


def _iter_packets(payload: bytes) -> Iterator[Any]:
    """Split a payload into EcoPackets and yield each parsed header.

    One MQTT message can carry several concatenated packets, and handing the
    whole buffer to ``ParseFromString`` would merge them into one instead.
    """
    offset = 0
    while offset < len(payload):
        try:
            tag, pos = _read_varint(payload, offset)
            if tag != _ECOPACKET_TAG:
                return
            length, pos = _read_varint(payload, pos)
            end = pos + length
            if end > len(payload):
                return
            packet = stream_ac_pb2.StreamACSendHeaderMsg()
            packet.ParseFromString(payload[offset:end])
        except Exception as error:
            _LOGGER.debug("Stopped splitting payload at offset %d: %s", offset, error)
            return
        yield packet.msg
        offset = end


# Open-API set envelope for the STREAM 5000 family (BKW3), as the app routes it
OPEN_SET_ENVELOPE: dict[str, Any] = {
    "cmdId": 38,
    "cmdFunc": 254,
    "dirDest": 1,
    "dirSrc": 1,
    "dest": 2,
    "needAck": True,
}

WORK_MODE_NAMES = {value: name for name, value in WORK_MODES.items()}


def private_command(sn: str, **fields: Any) -> StreamAC5000CommandMessage:
    return StreamAC5000CommandMessage(device_sn=sn, payload=stream_ac_5000_pb2.StreamAC5000SetCommand(**fields))


def open_command(sn: str, params: dict[str, Any]) -> OpenAPICommand:
    return OpenAPICommand(sn, OPEN_SET_ENVELOPE, params)


def soc_limits_command(sn: str, max_chg: int, min_dsg: int) -> StreamAC5000CommandMessage:
    """Write both SoC limits at once, as the app does."""
    return private_command(
        sn,
        propertyId=_PROP_SOC_LIMITS,
        socLimits=stream_ac_5000_pb2.StreamAC5000SetSocLimits(cmsMaxChgSoc=max_chg, cmsMinDsgSoc=min_dsg),
    )


def backup_command(client: EcoflowApiClient, sn: str, enabled: bool | None = None, level: int | None = None):
    if client.has_open_api:
        params: dict[str, Any] = {}
        if enabled is not None:
            params["backupSocOnOff"] = enabled
        if level is not None:
            params["backupSoc"] = level
        return open_command(sn, {"bpBackupConfig": params})
    config = stream_ac_5000_pb2.StreamAC5000BackupConfig()
    if enabled is not None:
        config.backupSocOnOff = enabled
    if level is not None:
        config.backupSoc = level
    return private_command(sn, propertyId=_PROP_BACKUP, bpBackupConfig=config)


def work_mode_command(client: EcoflowApiClient, sn: str, mode: int):
    if client.has_open_api:
        return open_command(sn, {"workMode": WORK_MODE_NAMES[mode]})
    return private_command(sn, propertyId=_PROP_WORK_MODE, workMode=mode)


class StreamSystemControls:
    """Settings that apply to a whole system, from a lone unit or from the pack that groups several.

    ``target`` names the unit a write goes to; any unit of a pack applies it to all of them.
    """

    def __init__(self, client: EcoflowApiClient, device: BaseDevice, target: Callable[[], str]):
        self.client = client
        self.device = device
        self.target = target

    def sensors(self) -> list[SensorEntity]:
        c, d = self.client, self.device
        return [
            LevelSensorEntity(c, d, "sysEnergyStreamReport.bpSoc", const.STREAM_PACK_BATTERY_LEVEL),
            WattsSensorEntity(c, d, "sysEnergyStreamReport.bpPwr", const.STREAM_PACK_BATTERY_POWER),
            WattsSensorEntity(c, d, "sysEnergyStreamReport.loadPwr", const.STREAM_AC5000_SYS_LOAD_POWER),
            WattsSensorEntity(c, d, "sysEnergyStreamReport.gridPwr", const.STREAM_AC5000_SYS_GRID_POWER),
            WattsSensorEntity(c, d, "sysEnergyStreamReport.pvPwr", const.STREAM_AC5000_SYS_PV_POWER),
            WattsSensorEntity(c, d, "sysEnergyStreamReport.onGridPwr", const.STREAM_AC5000_SYS_INVERTER_POWER),
            WattsSensorEntity(c, d, "sysEnergyStreamReport.backupPwr", const.STREAM_AC5000_SYS_BACKUP_POWER, False),
            WattsSensorEntity(c, d, "meterTotalPower", const.SMART_METER_POWER_GLOBAL),
            WattsSensorEntity(c, d, "meterPhaseAPower", const.SMART_METER_POWER_L1),
            WattsSensorEntity(c, d, "meterPhaseBPower", const.SMART_METER_POWER_L2),
            WattsSensorEntity(c, d, "meterPhaseCPower", const.SMART_METER_POWER_L3),
            VoltSensorEntity(c, d, "meterPhaseAVol", const.SMART_METER_VOLT_L1, False),
            VoltSensorEntity(c, d, "meterPhaseBVol", const.SMART_METER_VOLT_L2, False),
            VoltSensorEntity(c, d, "meterPhaseCVol", const.SMART_METER_VOLT_L3, False),
            FrequencySensorEntity(c, d, "meterFreq", const.POWER_GRID_FREQUENCY, False),
            WattsSensorEntity(c, d, "feedGridModePowMax", const.STREAM_FEED_GRID_MODE_POW_MAX, False),
        ]

    def binary_sensors(self) -> list[BinarySensorEntity]:
        return [MiscBinarySensorEntity(self.client, self.device, _KEY_METER_LINK, const.STREAM_AC5000_METER_LINK)]

    def numbers(self) -> list[NumberEntity]:
        c, d, target = self.client, self.device, self.target
        return [
            MaxBatteryLevelEntity(
                c, d, "cmsMaxChgSoc", const.MAX_CHARGE_LEVEL, 50, 100,
                lambda value, params: soc_limits_command(target(), value, int(params.get("cmsMinDsgSoc", 5))),
            ),
            MinBatteryLevelEntity(
                c, d, "cmsMinDsgSoc", const.MIN_DISCHARGE_LEVEL, 0, 30,
                lambda value, params: soc_limits_command(target(), int(params.get("cmsMaxChgSoc", 100)), value),
            ),
            MinMaxLevelEntity(
                c, d, "bpBackupConfig.backupSoc", const.BACKUP_RESERVE_LEVEL, 0, 100,
                lambda value: backup_command(c, target(), level=value),
            ),
            # Property 10 accepts partial writes, so each slider sends only its
            # own field. 2500 W is the most an owner can unlock without an
            # installer; nothing in the telemetry reports the approved ceiling,
            # so the bound is static and compliance stays the owner's business.
            ChargingPowerEntity(
                c, d, "feedGridModePowLimit", const.STREAM_AC5000_NET_POWER_OUT, 0, 2500,
                lambda value: private_command(
                    target(),
                    propertyId=_PROP_POWER_LIMITS,
                    powerLimits=stream_ac_5000_pb2.StreamAC5000SetPowerLimits(
                        feedGridModePowLimit=value, outLimitField4=_OUT_LIMIT_FIELD4, outLimitMax=_OUT_LIMIT_MAX
                    ),
                ),
            ),
            # The app allows 7200 W but the hardware does 2500 W, or 3000 W with a
            # second battery, so the slider stops where the device can deliver.
            ChargingPowerEntity(
                c, d, "chgPowLimit", const.STREAM_AC5000_NET_POWER_IN, 0, 3000,
                lambda value: private_command(
                    target(),
                    propertyId=_PROP_POWER_LIMITS,
                    powerLimits=stream_ac_5000_pb2.StreamAC5000SetPowerLimits(chgPowLimit=value),
                ),
            ),
        ]

    def switches(self) -> list[SwitchEntity]:
        c, d, target = self.client, self.device, self.target
        switches: list[SwitchEntity] = [
            EnabledEntity(
                c, d, "bpBackupConfig.backupSocOnOff", const.STREAM_AC5000_BACKUP_RESERVE,
                lambda value: backup_command(c, target(), enabled=bool(value)),
            ),
        ]
        if c.has_open_api:
            # Only the open API is known to write this flag; the app's own block 10 write is unverified
            switches.append(
                EnabledEntity(
                    c, d, "powerParameterConfig.feedToGridLimitOnOff", const.STREAM_AC5000_FEED_IN_LIMIT,
                    lambda value: open_command(
                        target(), {"powerParameterConfig": {"feedToGridLimitOnOff": bool(value)}}
                    ),
                )
            )
        return switches

    def selects(self) -> list[SelectEntity]:
        c, d, target = self.client, self.device, self.target
        return [
            PowerDictSelectEntity(
                c, d, _KEY_WORK_MODE, const.STREAM_AC5000_WORK_MODE, const.STREAM_AC5000_WORK_MODE_OPTIONS,
                lambda value: work_mode_command(c, target(), value),
            ),
        ]


class StreamAC5000(BaseInternalDevice):
    """One STREAM 5000 / AC 5000 unit. Linked units also belong to a ``StreamPack``, which then
    carries the settings and figures they share, so each unit keeps only its own."""

    pack: Any = None

    def _system(self, client: EcoflowApiClient) -> StreamSystemControls | None:
        if self.pack is not None:
            return None
        return StreamSystemControls(client, self, lambda: self.device_info.sn)

    def sensors(self, client: EcoflowApiClient) -> list[SensorEntity]:
        unit: list[SensorEntity] = [
            # --- battery ------------------------------------------------
            LevelSensorEntity(client, self, "soc", const.STREAM_BATTERY_LEVEL),
            LevelSensorEntity(client, self, "f32ShowSoc", const.STREAM_POWER_BATTERY_SOC, False),
            LevelSensorEntity(client, self, "bmsBattSoc", const.STREAM_AC5000_BMS_BATTERY_LEVEL, False),
            LevelSensorEntity(client, self, _KEY_PACK_SOC, const.STREAM_AC5000_PACK_BATTERY_LEVEL, False),
            StoredEnergyFromSocSensorEntity(
                client, self, "cmsBattFullEnergy", "f32ShowSoc", const.STREAM_STORED_ENERGY
            ),
            EnergyStorageSensorEntity(client, self, "remainCap", const.STREAM_AC5000_REMAIN_ENERGY),
            EnergyStorageSensorEntity(client, self, "cmsBattFullEnergy", const.STREAM_AC5000_FULL_ENERGY, False),
            # cmsMaxChgSoc / cmsMinDsgSoc are writable, so they live in numbers().
            # RemainSensorEntity clamps the device's 5939 "unknown" sentinel to 0.
            RemainSensorEntity(client, self, "remainTime", const.REMAINING_TIME),
            RemainSensorEntity(client, self, "bmsChgRemTime", const.CHARGE_REMAINING_TIME, False),
            RemainSensorEntity(client, self, "bmsDsgRemTime", const.DISCHARGE_REMAINING_TIME, False),
            # --- power --------------------------------------------------
            # Signed: >0 charging, <0 discharging
            WattsSensorEntity(client, self, KEY_BATTERY_POWER, const.STREAM_AC5000_BATTERY_POWER),
            WattsSensorEntity(client, self, "bpPower", const.STREAM_AC5000_BATTERY_POWER_MAGNITUDE, False),
            WattsSensorEntity(client, self, "gridPortPower", const.STREAM_AC5000_GRID_PORT_POWER),
            WattsSensorEntity(client, self, "unitInverterPower", const.STREAM_AC5000_UNIT_INVERTER_POWER),
            WattsSensorEntity(client, self, "unitOnGridPower", const.STREAM_AC5000_UNIT_ON_GRID_POWER),
            WattsSensorEntity(client, self, "unitBackupPower", const.STREAM_AC5000_UNIT_BACKUP_POWER),
            WattsSensorEntity(client, self, "maxChgPow", const.STREAM_AC5000_CHARGE_POWER_LIMIT, False),
            WattsSensorEntity(client, self, "maxDsgPow", const.STREAM_AC5000_MAX_DISCHARGE_POWER, False),
            # --- pack health --------------------------------------------
            MilliVoltSensorEntity(client, self, "minCellVol", const.MIN_CELL_VOLT, False),
            MilliVoltSensorEntity(client, self, "maxCellVol", const.MAX_CELL_VOLT, False),
            StateOfHealthSensorEntity(client, self, "realSoh", const.REAL_SOH, False),
            StateOfHealthSensorEntity(client, self, "cycleSoh", const.SOH, False),
            # --- lifetime counters (Energy dashboard) -------------------
            CumulativeCapacitySensorEntity(client, self, "accuChgCap", const.ACCU_CHARGE_CAP, False),
            CumulativeCapacitySensorEntity(client, self, "accuDsgCap", const.ACCU_DISCHARGE_CAP, False),
            EnergySensorEntity(client, self, "accuChgEnergy", const.ACCU_CHARGE_ENERGY),
            EnergySensorEntity(client, self, "accuDsgEnergy", const.ACCU_DISCHARGE_ENERGY),
            RoleSensorEntity(client, self, KEY_SYSTEM_ROLE, const.STREAM_AC5000_ROLE),
            StatusSensorEntity(client, self),
        ]
        if self.has_solar_inputs:
            unit += [
                WattsSensorEntity(client, self, "unitPvPower", const.STREAM_AC5000_UNIT_PV_POWER),
                WattsSensorEntity(client, self, "pv1Power", const.STREAM_POWER_PV_1),
                WattsSensorEntity(client, self, "pv2Power", const.STREAM_POWER_PV_2),
                WattsSensorEntity(client, self, "pv3Power", const.STREAM_POWER_PV_3),
                WattsSensorEntity(client, self, "pv4Power", const.STREAM_POWER_PV_4),
            ]
        system = self._system(client)
        return unit + (system.sensors() if system else [])

    @property
    def has_solar_inputs(self) -> bool:
        """The STREAM 5000 (ES21) has four solar inputs; the AC 5000 (ES22) has none."""
        return self.device_info.sn.startswith(SOLAR_PREFIXES)

    def binary_sensors(self, client: EcoflowApiClient) -> list[BinarySensorEntity]:
        system = self._system(client)
        return system.binary_sensors() if system else []

    def numbers(self, client: EcoflowApiClient) -> list[NumberEntity]:
        system = self._system(client)
        return system.numbers() if system else []

    def switches(self, client: EcoflowApiClient) -> list[SwitchEntity]:
        sn = self.device_info.sn
        unit: list[SwitchEntity] = [
            EnabledEntity(
                client,
                self,
                _KEY_AC_OUT,
                const.STREAM_AC5000_AC_OUTPUT,
                (lambda value: open_command(sn, {"devSwitch": {"acSocketOnoff": bool(value)}}))
                if client.has_open_api
                else (
                    lambda value: private_command(
                        sn, propertyId=_PROP_AC_OUT, acOut=stream_ac_5000_pb2.StreamAC5000SetAcOut(enabled=value)
                    )
                ),
            ),
            EnabledEntity(
                client,
                self,
                _KEY_XBOOST,
                const.STREAM_AC5000_XBOOST,
                lambda value: private_command(
                    sn,
                    propertyId=_PROP_DEVICE_CFG,
                    deviceCfg=stream_ac_5000_pb2.StreamAC5000SetDeviceCfg(xboostEnabled=value),
                ),
            ),
            EnabledEntity(
                client,
                self,
                "upsEnabled",
                const.STREAM_AC5000_UPS,
                lambda value: private_command(
                    sn,
                    propertyId=_PROP_DEVICE_CFG,
                    deviceCfg=stream_ac_5000_pb2.StreamAC5000SetDeviceCfg(upsEnabled=value),
                ),
            ),
        ]
        system = self._system(client)
        return unit + (system.switches() if system else [])

    def selects(self, client: EcoflowApiClient) -> list[SelectEntity]:
        system = self._system(client)
        return system.selects() if system else []

    @override
    def open_quota_params(self, quota: dict[str, Any]) -> dict[str, Any]:
        params = flatten_open_quota(quota)
        mode = params.pop("workMode", None)
        if isinstance(mode, str) and mode in WORK_MODES:
            params[_KEY_WORK_MODE] = WORK_MODES[mode]
        socket = params.pop("devSwitch.acSocketOnoff", None)
        if socket is not None:
            params[_KEY_AC_OUT] = int(bool(socket))
        return params

    @override
    def _prepare_data(self, raw_data: bytes) -> dict[str, Any]:
        params: dict[str, Any] = {}

        for header in _iter_packets(raw_data):
            pdata = getattr(header, "pdata", b"")
            if not pdata:
                continue
            try:
                self._decode_pdata(header.cmd_id, pdata, params)
            except Exception as error:
                _LOGGER.debug(
                    "Failed to decode cmd_id %s pdata %s: %s",
                    header.cmd_id,
                    pdata.hex(),
                    error,
                )

        raw: dict[str, Any] = {"params": params}
        if params:
            raw["timestamp"] = utcnow()
        return raw

    def _decode_pdata(self, cmd_id: int, pdata: bytes, params: dict[str, Any]) -> None:
        if cmd_id == _CMD_ID_STATUS:
            status = stream_ac_5000_pb2.StreamAC5000StatusPack()
            status.ParseFromString(pdata)
            # This frame's SoC is the pack scale, not the app-facing one.
            self._copy(status.battery, params, "cmsMaxChgSoc", "bmsChgRemTime", "bmsDsgRemTime")
            self._copy(status.battery, params, ("f32ShowSoc", _KEY_PACK_SOC), "cmsMinDsgSoc")

        elif cmd_id == _CMD_ID_RUNTIME:
            runtime = stream_ac_5000_pb2.StreamAC5000Runtime()
            runtime.ParseFromString(pdata)
            self._decode_runtime(runtime, params)

        elif cmd_id == _CMD_ID_PACK:
            pack = stream_ac_5000_pb2.StreamAC5000Pack()
            pack.ParseFromString(pdata)
            self._copy(
                pack,
                params,
                ("f32ShowSoc", _KEY_PACK_SOC),
                "realSoh",
                "cycleSoh",
                "calendarSoh",
                "accuChgCap",
                "accuDsgCap",
                "accuChgEnergy",
                "accuDsgEnergy",
            )

    def _decode_runtime(self, message: Any, params: dict[str, Any]) -> None:
        if message.HasField("meter"):
            # An empty block means the meter is configured but not responding.
            params[_KEY_METER_LINK] = 1 if message.meter.ByteSize() > 0 else 0
        self._copy(
            message.meter,
            params,
            "meterPhaseAPower",
            "meterPhaseBPower",
            "meterPhaseCPower",
            "meterPhaseAVol",
            "meterPhaseBVol",
            "meterPhaseCVol",
            "meterFreq",
            "meterTotalPower",
        )
        self._copy(
            message.sysConfig,
            params,
            "maxChgPow",
            "maxDsgPow",
            "cmsBattFullEnergy",
            "f32ShowSoc",
            "cmsMaxChgSoc",
            "cmsMinDsgSoc",
            # feedGridModePowLimit deliberately absent: block 10 owns that key,
            # being the structure the app writes and the only unambiguous source.
            "feedGridModePowMax",
        )
        # The BMS SoC runs ~1% low and its max-charge field is a fixed ceiling,
        # so neither may share the app-facing key.
        self._copy(
            message.bmsPack.bms,
            params,
            ("soc", "bmsBattSoc"),
            ("cmsMaxChgSoc", "bmsMaxChgSoc"),
            "cmsBattFullEnergy",
            "bmsDsgRemTime",
            "bmsChgRemTime",
            "minCellVol",
            "maxCellVol",
        )
        # Block 44 is this unit's own report, and the only SoC a pack's slave sends itself
        self._copy(message.cms, params, "cmsBattFullEnergy", "remainTime", "soc")
        # Blocks 50 and 54 list every unit of a pack. This unit keeps its own entry; the
        # others' go under unit.<sn>.<key>, for the pack to hand to those units.
        own = self.device_info.sn
        for stat in message.statPack.stat:
            self._copy_unit_entry(stat, own, params, ("soc", "soc"))
        for power in message.powerPack.power:
            self._copy_unit_entry(power, own, params, *UNIT_FLOW_KEYS)
        self._copy(message.deviceCfg, params, "upsEnabled", ("xboostEnabled", _KEY_XBOOST))
        self._copy(message.powerLimits, params, "feedGridModePowLimit", "chgPowLimit")
        self._copy(message.acOut, params, ("enabled", _KEY_AC_OUT))
        self._copy(message, params, ("workMode", _KEY_WORK_MODE))
        self._copy(message.cms, params, "remainCap")

        # Signed watts of this unit's battery; the CMS copy is emitted more often than the BMS.
        for source in (message.cms, message.bmsPack.bms):
            if source.HasField("power"):
                params[KEY_BATTERY_POWER] = source.power
                params["bpPower"] = abs(source.power)
                break

        # Pack-wide values, under the names the open API gives them
        self._copy_prefixed(message.sysEnergyStreamReport, params, "sysEnergyStreamReport", *SYS_ENERGY_FIELDS)
        self._copy_prefixed(message.bpBackupConfig, params, "bpBackupConfig", "backupSocOnOff", "backupSoc")
        self._copy_prefixed(message.powerLimits, params, "powerParameterConfig", "feedToGridLimitOnOff")
        self._copy(
            message.systemConfig,
            params,
            ("distributedDeviceRole", KEY_SYSTEM_ROLE),
            ("systemGroupId", KEY_SYSTEM_GROUP),
            ("systemDevCnt", KEY_SYSTEM_UNITS),
        )

    def _copy_unit_entry(
        self, entry: Any, own_sn: str, params: dict[str, Any], *fields: tuple[str, str]
    ) -> None:
        if not entry.HasField("sn"):
            return
        prefix = "" if entry.sn == own_sn else f"{UNIT_PREFIX}{entry.sn}."
        # an entry is the unit's whole snapshot, and zero values are left off the wire
        for name, key in fields:
            params[f"{prefix}{key}"] = getattr(entry, name)

    @staticmethod
    def _copy_prefixed(source: Any, params: dict[str, Any], prefix: str, *fields: str) -> None:
        for field in fields:
            if source.HasField(field):
                params[f"{prefix}.{field}"] = getattr(source, field)

    @staticmethod
    def _copy(source: Any, params: dict[str, Any], *fields: str | tuple[str, str]) -> None:
        """Copy set protobuf fields onto parameter names.

        Fields are ``"name"`` or ``("name", "alias")``. The ``HasField`` guard
        matters: incremental uploads carry only what changed, so an absent field
        must not overwrite a good value with a proto3 default.
        """
        for field in fields:
            name, alias = field if isinstance(field, tuple) else (field, field)
            if source.HasField(name):
                params[alias] = getattr(source, name)
