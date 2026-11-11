"""An app-API entry that also holds open-API developer keys.

The open API is the documented, stable channel, so it is followed wherever it serves a device: its
quota pushes, its online/offline status pushes and its set commands. The app API fills in what the
open API does not publish, such as each battery's own power or its role in a pack. Devices keep
their app-API type and unique ids, so adding keys to an existing app-API entry keeps its entities.
"""

from __future__ import annotations

import logging
from typing import Any

from ..devices import EcoflowDeviceInfo
from ..devices.data_holder import PreparedData
from .message import Message, OpenAPICommand
from .private_api import EcoflowPrivateApiClient
from .public_api import EcoflowPublicApiClient

_LOGGER = logging.getLogger(__name__)


class EcoflowHybridApiClient(EcoflowPrivateApiClient):
    def __init__(
        self,
        api_domain: str,
        ecoflow_username: str,
        ecoflow_password: str,
        group: str,
        open_api_domain: str,
        access_key: str,
        secret_key: str,
    ):
        super().__init__(api_domain, ecoflow_username, ecoflow_password, group)
        self.open = EcoflowPublicApiClient(open_api_domain, access_key, secret_key, group)
        self.open_mqtt_client: Any = None

    async def login(self):
        await super().login()
        await self.open.login()

    def _create_device_info(
        self, device_sn: str, device_name: str, device_type: str, status: int = -1
    ) -> EcoflowDeviceInfo:
        info = super()._create_device_info(device_sn, device_name, device_type, status)
        account = self.open.mqtt_info.username
        info.open_data_topic = f"/open/{account}/{device_sn}/quota"
        info.open_status_topic = f"/open/{account}/{device_sn}/status"
        info.open_set_topic = f"/open/{account}/{device_sn}/set"
        info.open_set_reply_topic = f"/open/{account}/{device_sn}/set_reply"
        return info

    async def fetch_all_available_devices(self) -> list[EcoflowDeviceInfo]:
        devices = await super().fetch_all_available_devices()
        # The open API's online flag is the documented one: prefer it where it knows the device
        try:
            open_status = {d.sn: d.status for d in await self.open.fetch_all_available_devices()}
        except Exception as error:
            _LOGGER.debug("Open-API device list unavailable: %s", error)
            return devices
        for device in devices:
            if device.sn in open_status:
                device.status = open_status[device.sn]
        return devices

    async def quota_all(self, device_sn: str | None):
        await super().quota_all(device_sn)
        for sn in [device_sn] if device_sn else list(self.devices):
            device = self.devices.get(sn)
            if device is None or not device.device_info.open_data_topic:
                continue
            try:
                raw = await self.open.call_api("/device/quota/all", {"sn": sn})
            except Exception as error:
                # 1006: the open API does not serve this device; the app API still does
                _LOGGER.debug("No open-API quota for %s: %s", sn, error)
                continue
            params = device.open_quota_params(raw.get("data") or {})
            if params:
                device.data.add_data(PreparedData(None, {"params": params}, raw, False))

    def start(self):
        from .ecoflow_mqtt import EcoflowMQTTClient

        _LOGGER.debug("Starting app and open MQTT clients")
        self.mqtt_client = EcoflowMQTTClient(self.mqtt_info, self.devices, topic_prefix="/app/")
        self.mqtt_client.on_auth_failure = self.on_auth_failure
        self.open.mqtt_info.client_id = f"Hassio-{self.open.mqtt_info.username}-{self.group.replace(' ', '-')}"
        self.open_mqtt_client = EcoflowMQTTClient(self.open.mqtt_info, self.devices, topic_prefix="/open/")
        self.open_mqtt_client.on_auth_failure = self.on_auth_failure

    def stop(self):
        super().stop()
        if self.open_mqtt_client is not None:
            self.open_mqtt_client.stop()

    def _publish_set(self, target: Any, command: Message) -> None:
        if isinstance(command, OpenAPICommand):
            self.open_mqtt_client.publish(target.device_info.open_set_topic, command.to_mqtt_payload())
            return
        super()._publish_set(target, command)

    @property
    def has_open_api(self) -> bool:
        return True
