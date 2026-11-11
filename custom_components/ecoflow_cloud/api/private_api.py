import base64
import hashlib
import logging
from time import time
from typing import Any

import aiohttp
from homeassistant.components.diagnostics import async_redact_data
from homeassistant.util import uuid

from ..devices import EcoflowDeviceInfo
from . import API_RESPONSE_TO_REDACT, EcoflowApiClient, EcoflowAuthException, EcoflowException, EcoflowSpace, EcoflowSystem

_LOGGER = logging.getLogger(__name__)


class EcoflowPrivateApiClient(EcoflowApiClient):
    def __init__(self, api_domain: str, ecoflow_username: str, ecoflow_password: str, group: str):
        super().__init__()
        self.api_domain = api_domain
        self.ecoflow_password = ecoflow_password
        self.ecoflow_username = ecoflow_username
        self.group = group
        self.user_id = None
        self.token = None
        self.user_name = None

    async def login(self):
        async with aiohttp.ClientSession() as session:
            url = f"https://{self.api_domain}/auth/login"
            headers = {"lang": "en_US", "content-type": "application/json"}
            data = {
                "email": self.ecoflow_username,
                "password": base64.b64encode(self.ecoflow_password.encode()).decode(),
                "scene": "IOT_APP",
                "userType": "ECOFLOW",
            }

            _LOGGER.info(f"Login to EcoFlow API {url}")

            resp = await session.post(url, headers=headers, json=data)
            try:
                response = await self._get_json_response(resp)
            except EcoflowException as error:
                # an error code from /auth/login means the credentials were rejected;
                # transport and parse failures carry no code and stay retryable
                if error.code is None:
                    raise
                raise EcoflowAuthException(str(error), code=error.code) from error

            try:
                self.token = response["data"]["token"]
                self.user_id = response["data"]["user"]["userId"]
                self.user_name = response["data"]["user"].get("name", "<no user name>")
            except KeyError as key:
                _LOGGER.debug("Login response: %s", async_redact_data(response, API_RESPONSE_TO_REDACT))
                raise EcoflowException(f"Failed to extract key {key} from login response")

            _LOGGER.info(f"Successfully logged in: {self.user_name}")

            _LOGGER.info("Requesting IoT MQTT credentials")
            response = await self.__call_api("/iot-auth/app/certification")
            self._accept_mqqt_certification(response)

            # Should be ANDROID_..str.._user_id !!!
            self.mqtt_info.client_id = f"ANDROID_{str(uuid.random_uuid_hex()).upper()}_{self.user_id}"

    # Failed to connect to MQTT: not authorised
    def gen_client_id(self):
        base = f"ANDROID_{str(uuid.random_uuid_hex()).upper()}_{self.user_id}"
        millis = int(time() * 1000)
        verify_info = "0000000000000000000000000000000000000000000000000000000000000000"
        pub = verify_info[:32]
        priv = verify_info[32:]
        k = priv + base + str(millis)
        res = base + "_" + pub + "_" + str(millis) + "_" + hashlib.md5(k.encode("utf-8")).hexdigest()
        return res

    async def fetch_all_available_devices(self) -> list[EcoflowDeviceInfo]:
        """Devices bound to the account, with their online flag, as the app lists them."""
        from ..devices.sn_prefixes import device_type_for

        response = await self.__call_api("/iot-devices/user/device")
        data = response.get("data") or {}
        # devices shared with this account are as usable as its own
        listed = {**(data.get("share") or {}), **(data.get("bound") or {})}
        result = []
        for sn, device in listed.items():
            device_type = device_type_for(sn) or "DIAGNOSTIC"
            name = device.get("deviceName") or f"{device_type}-{sn}"
            result.append(self._create_device_info(sn, name, device_type, int(device.get("online", -1))))
        return result

    async def fetch_device_spaces(self, sns: list[str]) -> dict[str, EcoflowSpace]:
        """The app space of each device: its home, or a room of it."""
        spaces: dict[str, EcoflowSpace] = {}
        for sn in sns:
            info = (await self.__call_api("/app/space/getSpaceInfoBySn", {"sn": sn})).get("data") or {}
            if info.get("spaceId"):
                spaces[sn] = EcoflowSpace(
                    space_id=str(info["spaceId"]),
                    name=info.get("spaceName") or "",
                    is_root=int(info.get("isRootSpace", 0)) == 1 or info.get("spaceId") == info.get("rootSpaceId"),
                )
        return spaces

    async def fetch_systems(
        self, sns: list[str], known_spaces: dict[str, EcoflowSpace] | None = None
    ) -> list[EcoflowSystem]:
        """The systems (packs) the app groups the given devices into, with their master unit."""
        systems: dict[str, EcoflowSystem] = {}
        spaces = known_spaces if known_spaces is not None else await self.fetch_device_spaces(sns)
        for space_id in {spaces[sn].space_id for sn in sns if sn in spaces}:
            listing = await self.__call_api("/app/space/v3/all/device/list", {"spaceId": space_id})
            for system in (listing.get("data") or {}).get("systemList") or []:
                parsed = EcoflowSystem.from_api(system)
                if parsed is not None:
                    systems[parsed.system_no] = parsed
        return list(systems.values())

    async def quota_all(self, device_sn: str | None):
        if not device_sn:
            target_devices = self.devices
        else:
            target_devices = {device_sn: self.devices[device_sn]}

        for sn, device in target_devices.items():
            # a pack has no topic of its own: its units answer for it
            if device.device_info.get_topic:
                self.send_get_message(sn, device.get_quota_message())

    def _device_registry(self) -> dict[str, Any]:
        from ..devices.registry import devices
        return devices

    def _create_device_info(
        self, device_sn: str, device_name: str, device_type: str, status: int = -1
    ) -> EcoflowDeviceInfo:
        return EcoflowDeviceInfo(
            public_api=False,
            sn=device_sn,
            name=device_name,
            device_type=device_type,
            status=status,
            data_topic=f"/app/device/property/{device_sn}",
            set_topic=f"/app/{self.user_id}/{device_sn}/thing/property/set",
            set_reply_topic=f"/app/{self.user_id}/{device_sn}/thing/property/set_reply",
            get_topic=f"/app/{self.user_id}/{device_sn}/thing/property/get",
            get_reply_topic=f"/app/{self.user_id}/{device_sn}/thing/property/get_reply",
        )

    async def __call_api(self, endpoint: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        async with aiohttp.ClientSession() as session:
            headers = {
                "lang": "en_US",
                "authorization": f"Bearer {self.token}",
                "content-type": "application/json",
            }
            user_data = {"userId": self.user_id}
            req_params = {}
            if params is not None:
                req_params.update(params)

            resp = await session.get(
                f"https://{self.api_domain}{endpoint}",
                data=user_data,
                params=req_params,
                headers=headers,
            )
            _LOGGER.info(f"Request: {endpoint} {req_params}: got {resp}")
            return await self._get_json_response(resp)
