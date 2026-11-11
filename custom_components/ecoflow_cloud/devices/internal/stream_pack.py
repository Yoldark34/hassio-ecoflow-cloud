"""Linked STREAM 5000 / AC 5000 units, seen as the one system the EcoFlow app shows.

Every unit of a pack reports the same system figures and applies a system setting to all units, so
the pack carries them once instead of each unit repeating them. Each unit keeps what is its own:
its battery level and power, capacity, remaining times, AC socket, X-Boost, UPS and its role.

The app API lists which units form a system (``/app/space/v3/all/device/list``) and names a main
unit; the units also elect a master among themselves and report their role in block 27. Writes go
to the master while it is online, otherwise to any unit that is, since any unit applies them to all.
"""

from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.binary_sensor import BinarySensorEntity
from homeassistant.components.number import NumberEntity
from homeassistant.components.select import SelectEntity
from homeassistant.components.sensor import SensorDeviceClass, SensorEntity
from homeassistant.components.switch import SwitchEntity
from homeassistant.helpers.entity import EntityCategory

from custom_components.ecoflow_cloud.api import EcoflowApiClient, EcoflowSystem
from custom_components.ecoflow_cloud.device_data import DeviceData
from custom_components.ecoflow_cloud.devices import BaseDevice, EcoflowDeviceInfo, const
from custom_components.ecoflow_cloud.devices.data_holder import EcoflowDataHolder, PreparedData
from custom_components.ecoflow_cloud.devices.internal.stream_ac_5000 import (
    KEY_SYSTEM_ROLE,
    KEY_SYSTEM_UNITS,
    UNIT_PREFIX,
    StreamAC5000,
    StreamSystemControls,
)
from custom_components.ecoflow_cloud.devices.status_tracker import OnlineStatus, StatusTracker
from custom_components.ecoflow_cloud.sensor import MiscSensorEntity, StatusSensorEntity

_LOGGER = logging.getLogger(__name__)

PACK_DEVICE_TYPE = "STREAM_PACK"
KEY_MASTER_SN = "masterSn"
KEY_METER_LINK = "meterLinkUp"

# What every unit reports for the whole system, and so belongs to the pack
_PACK_KEYS = frozenset(
    {
        "workMode",
        "feedGridModePowLimit",
        "feedGridModePowMax",
        "chgPowLimit",
        "cmsMaxChgSoc",
        "cmsMinDsgSoc",
        KEY_SYSTEM_UNITS,
        "meterTotalPower",
        "meterPhaseAPower",
        "meterPhaseBPower",
        "meterPhaseCPower",
        "meterPhaseAVol",
        "meterPhaseBVol",
        "meterPhaseCVol",
        "meterFreq",
    }
)
_PACK_PREFIXES = ("sysEnergyStreamReport.", "bpBackupConfig.", "powerParameterConfig.")

_MASTER = 1
_SLAVE = 2

PACK_STATES = ["ready", "degraded", "waiting", "offline"]


def is_pack_key(key: str) -> bool:
    return key in _PACK_KEYS or key.startswith(_PACK_PREFIXES)


class PackStatusTracker(StatusTracker):
    """Online while any unit is: the pack keeps reporting through whichever unit still does."""

    def __init__(self, pack: StreamPack, assume_offline_sec: int):
        super().__init__(assume_offline_sec)
        self._pack = pack

    @property
    def status(self) -> OnlineStatus:
        statuses = [member.status_tracker.status for member in self._pack.members]
        if OnlineStatus.ONLINE in statuses:
            return OnlineStatus.ONLINE
        if OnlineStatus.ASSUME_OFFLINE in statuses:
            return OnlineStatus.ASSUME_OFFLINE
        return OnlineStatus.OFFLINE

    @property
    def wants_status_poll(self) -> bool:
        # the units ask for their own polls
        return False


class StreamPack(BaseDevice):
    def __init__(self, device_info: EcoflowDeviceInfo, device_data: DeviceData, system: EcoflowSystem):
        super().__init__(device_info, device_data)
        self.system = system
        self.members: list[StreamAC5000] = []
        self.status_tracker = PackStatusTracker(self, device_data.options.assume_offline_sec)
        self.data = EcoflowDataHolder(None, device_data.options.diagnostic_mode, status_callback=self.status_tracker)

    @staticmethod
    def create(system: EcoflowSystem, members: list[StreamAC5000]) -> StreamPack:
        sn = f"pack-{system.system_no}"
        info = EcoflowDeviceInfo(
            public_api=False,
            sn=sn,
            name=system.name,
            device_type=PACK_DEVICE_TYPE,
            status=-1,
            data_topic="",
            set_topic="",
            set_reply_topic="",
            get_topic=None,
            get_reply_topic=None,
        )
        data = DeviceData(sn, system.name, PACK_DEVICE_TYPE, members[0].device_data.options, None, None)
        pack = StreamPack(info, data, system)
        pack.suggested_area = members[0].suggested_area
        for member in members:
            pack.add_member(member)
        pack._assume_roles_from_app()
        return pack

    def _assume_roles_from_app(self) -> None:
        """Roles until the units report theirs: the app's main unit leads.

        A unit sends its role only in full uploads, minutes apart, so without this the
        role and master sensors would start unknown.
        """
        main_sn = self.system.main_sn
        if main_sn is None or self.member(main_sn) is None:
            return
        for member in self.members:
            if KEY_SYSTEM_ROLE not in member.data.params:
                role = _MASTER if member.device_info.sn == main_sn else _SLAVE
                member.data.add_data(PreparedData(None, {"params": {KEY_SYSTEM_ROLE: role}}, None, is_auto=False))

    def add_member(self, member: StreamAC5000) -> None:
        self.members.append(member)
        member.pack = self
        member.data.add_params_listener(lambda params: self._on_member_params(params))
        # what the unit already knows, e.g. from the quota read before the pack existed
        self._on_member_params(dict(member.data.params))

    def _on_member_params(self, params: dict[str, Any]) -> None:
        self._hand_out_unit_entries(params)
        shared = {key: value for key, value in params.items() if is_pack_key(key)}
        if KEY_METER_LINK in params:
            # only the unit wired to the meter has it; the others send an empty block
            shared[KEY_METER_LINK] = int(any(m.data.params.get(KEY_METER_LINK) == 1 for m in self.members))
        if KEY_SYSTEM_ROLE in params:
            shared[KEY_MASTER_SN] = self.master_sn()
        if shared:
            self.data.add_data(PreparedData(None, {"params": shared}, None))

    def _hand_out_unit_entries(self, params: dict[str, Any]) -> None:
        """The master lists every unit's SoC and power: give each unit its own entry."""
        per_unit: dict[str, dict[str, Any]] = {}
        for key, value in params.items():
            if key.startswith(UNIT_PREFIX):
                sn, _, name = key[len(UNIT_PREFIX) :].partition(".")
                per_unit.setdefault(sn, {})[name] = value
        for sn, values in per_unit.items():
            member = self.member(sn)
            if member is not None:
                # relayed, so it says nothing about whether that unit itself is reachable
                member.data.add_data(PreparedData(None, {"params": values}, None, is_auto=False))

    def master_sn(self) -> str | None:
        for member in self.members:
            if member.data.params.get(KEY_SYSTEM_ROLE) == _MASTER:
                return member.device_info.sn
        sns = {member.device_info.sn for member in self.members}
        return self.system.main_sn if self.system.main_sn in sns else None

    def member(self, sn: str | None) -> StreamAC5000 | None:
        return next((m for m in self.members if m.device_info.sn == sn), None)

    def target_sn(self) -> str:
        """The unit a pack setting is written to."""
        master = self.member(self.master_sn())
        if master is not None and master.status_tracker.is_online:
            return master.device_info.sn
        online = [m for m in self.members if m.status_tracker.is_online]
        if online:
            return online[0].device_info.sn
        return (master or self.members[0]).device_info.sn

    def pack_state(self) -> str:
        online = [m for m in self.members if m.status_tracker.is_online]
        if not online:
            return "offline"
        if len(online) < len(self.members) or len(self.members) < len(self.system.member_sns):
            return "degraded"
        if "sysEnergyStreamReport.bpSoc" not in self.data.params:
            return "waiting"
        return "ready"

    def _controls(self, client: EcoflowApiClient) -> StreamSystemControls:
        return StreamSystemControls(client, self, self.target_sn)

    def sensors(self, client: EcoflowApiClient) -> list[SensorEntity]:
        return [
            PackStatusSensorEntity(client, self),
            MasterSensorEntity(client, self, KEY_MASTER_SN, const.STREAM_PACK_MASTER),
            MiscSensorEntity(client, self, KEY_SYSTEM_UNITS, const.STREAM_PACK_UNITS, False),
            *self._controls(client).sensors(),
        ]

    def binary_sensors(self, client: EcoflowApiClient) -> list[BinarySensorEntity]:
        return self._controls(client).binary_sensors()

    def numbers(self, client: EcoflowApiClient) -> list[NumberEntity]:
        return self._controls(client).numbers()

    def switches(self, client: EcoflowApiClient) -> list[SwitchEntity]:
        return self._controls(client).switches()

    def selects(self, client: EcoflowApiClient) -> list[SelectEntity]:
        return self._controls(client).selects()


class MasterSensorEntity(MiscSensorEntity):
    """Which unit leads the pack, by name."""

    _attr_icon = "mdi:crown"

    def _update_value(self, val: Any) -> bool:
        pack: StreamPack = self._device  # type: ignore[assignment]
        member = pack.member(val)
        return super()._update_value(member.device_data.name if member else val)


class PackStatusSensorEntity(StatusSensorEntity):
    """Whether every unit of the pack reports: ready, degraded, waiting or offline.

    Stays available so automations can rely on it while the rest of the pack is not.
    """

    _attr_device_class = SensorDeviceClass.ENUM
    _attr_options = PACK_STATES
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_icon = "mdi:battery-sync"

    def __init__(self, client: EcoflowApiClient, device: StreamPack):
        super().__init__(client, device, const.STREAM_PACK_STATUS, "pack_status")
        self._pack = device

    def _handle_coordinator_update(self) -> None:
        state = self._pack.pack_state()
        master = self._pack.member(self._pack.master_sn())
        self._attrs["master"] = master.device_data.name if master else None
        self._attrs["units"] = {
            m.device_data.name: m.status_tracker.status.label for m in self._pack.members
        }
        if state != self._attr_native_value:
            self._attr_native_value = state
            self.schedule_update_ha_state()

    @property
    def available(self) -> bool:
        return True


def build_packs(
    systems: list[EcoflowSystem], devices: dict[str, BaseDevice]
) -> list[StreamPack]:
    """A pack for each system with at least two configured STREAM units."""
    packs = []
    for system in systems:
        members = [
            device
            for sn in system.member_sns
            if isinstance(device := devices.get(sn), StreamAC5000)
        ]
        if len(members) >= 2:
            packs.append(StreamPack.create(system, members))
    return packs

