from __future__ import annotations

import logging
from collections.abc import Mapping
from copy import deepcopy
from typing import Any

import voluptuous as vol
from homeassistant.components.diagnostics import async_redact_data
from homeassistant.config_entries import (
    ConfigEntry,
    ConfigFlow,
    OptionsFlow,
)
from homeassistant.core import callback
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers import selector
from homeassistant.helpers.device_registry import DeviceRegistry
from homeassistant.helpers.entity_registry import EntityRegistry

from custom_components.ecoflow_cloud import (
    CONF_ACCESS_KEY,
    CONF_API_HOST,
    CONF_AUTO_ADD_DEVICES,
    CONF_DEVICE_ID,
    CONF_DEVICE_LIST,
    CONF_DEVICE_NAME,
    CONF_DEVICE_TYPE,
    CONF_GROUP,
    CONF_OPEN_API_HOST,
    CONF_PARENT_SN,
    CONF_PASSWORD,
    CONF_SECRET_KEY,
    CONF_SELECT_DEVICE_KEY,
    CONF_TO_REDACT,
    CONF_USERNAME,
    CONFIG_VERSION,
    DEFAULT_ASSUME_OFFLINE_SEC,
    DEFAULT_ENERGY_UPDATE_INTERVAL_SEC,
    DEFAULT_OPEN_API_HOST,
    DEFAULT_REFRESH_PERIOD_SEC,
    DEFAULT_RESET_SENSORS_ON_OFFLINE,
    ECOFLOW_DOMAIN,
    OPTS_ASSUME_OFFLINE_SEC,
    OPTS_DIAGNOSTIC_MODE,
    OPTS_ENERGY_UPDATE_INTERVAL_SEC,
    OPTS_POWER_STEP,
    OPTS_REFRESH_PERIOD_SEC,
    OPTS_RESET_SENSORS_ON_OFFLINE,
    OPTS_VERBOSE_STATUS_MODE,
    DeviceData,
    DeviceOptions,
    default_device_options,
    extract_devices,
    is_hybrid_entry,
    is_public_entry,
)

from .api import EcoflowAuthException, EcoflowException
from .devices import EcoflowDeviceInfo

_LOGGER = logging.getLogger(__name__)

API_SELECT_DEVICE_SCHEMA = vol.Schema({vol.Required(CONF_SELECT_DEVICE_KEY): str})

CONF_DISCOVERED: str = "devices"
DEFAULT_GROUP = "EcoFlow"
_CREDENTIAL_KEYS = frozenset(
    {CONF_API_HOST, CONF_USERNAME, CONF_PASSWORD, CONF_OPEN_API_HOST, CONF_ACCESS_KEY, CONF_SECRET_KEY}
)

# Region -> host, shown with the host so the choice is explicit
APP_API_HOSTS = {"api-e.ecoflow.com": "EU", "api.ecoflow.com": "US"}
OPEN_API_HOSTS = {"api-e.ecoflow.com": "EU", "api-a.ecoflow.com": "US"}


def _host_selector(hosts: dict[str, str]) -> selector.SelectSelector:
    return selector.SelectSelector(
        selector.SelectSelectorConfig(
            options=[selector.SelectOptionDict(value=host, label=f"{region} - {host}") for host, region in hosts.items()],
            mode=selector.SelectSelectorMode.DROPDOWN,
            # an entry made before the selector may hold another host
            custom_value=True,
        )
    )


class EcoflowConfigFlow(ConfigFlow, domain=ECOFLOW_DOMAIN):
    VERSION = CONFIG_VERSION

    def __init__(self) -> None:
        self.auth = None
        self.config_entry: ConfigEntry | None = None
        self.new_data = {}
        self.new_options = {}

        self.cloud_device = None
        self.cloud_devices: dict[str, EcoflowDeviceInfo] = {}
        self.local_devices: dict[str, DeviceData] = {}
        self.discovered: dict[str, EcoflowDeviceInfo] = {}
        self.entry_title: str | None = None

    def set_current_config_entry(self, config_entry: ConfigEntry) -> None:
        self.config_entry = config_entry
        self.new_data = deepcopy(dict(config_entry.data))
        self.new_options = deepcopy(dict(config_entry.options))

    def set_device_list(self, device_list: list[EcoflowDeviceInfo]) -> None:
        for device in device_list:
            self.cloud_devices[f"{device.name} ({device.device_type})"] = device

    def set_local_device_list(self, devices: list[DeviceData]) -> None:
        for device in devices:
            self.local_devices[f"{device.name} ({device.sn})"] = device

    async def update_or_create(self):
        if self.config_entry:
            _LOGGER.info(
                ".. reconfigure: entry = %s, data = %s, options = %s ",
                str(self.config_entry),
                async_redact_data(self.new_data, CONF_TO_REDACT),
                str(self.new_options),
            )
            if self.hass.config_entries.async_update_entry(
                entry=self.config_entry, data=self.new_data, options=self.new_options
            ):
                # reload if changed
                self.hass.config_entries.async_schedule_reload(self.config_entry.entry_id)

            return self.async_abort(reason="reconfigure_successful")

        else:
            _LOGGER.info(
                ".. create: entry = %s, data = %s, options = %s ",
                str(self.config_entry),
                async_redact_data(self.new_data, CONF_TO_REDACT),
                str(self.new_options),
            )

            from .devices.registry import device_support_sub_devices

            # iterate over a snapshot: the loop mutates new_data[CONF_DEVICE_LIST]
            for sn, device_data in list(self.new_data[CONF_DEVICE_LIST].items()):
                if device_data[CONF_DEVICE_TYPE] not in device_support_sub_devices:
                    # skip here all devices that do not support sub devices
                    continue
                from .api.public_api import EcoflowPublicApiClient

                if not isinstance(self.auth, EcoflowPublicApiClient):
                    raise TypeError("Only public api is supported for devices with sub devices")
                all_device_info = await self.auth.call_api("/device/quota/all", {"sn": sn})

                # The "/device/quota/all" response for a Power Kit is a FLAT dict whose
                # keys look like "<moduleType>.<moduleSn>.<field>"
                # (e.g. "bp5000.M101Z3B4ZE5A0737.soc"), with scalar values. Aggregate
                # keys such as "bmsTotal.<field>" carry no module serial. Older
                # firmware/API returned a nested dict ({type: {sn: {...}}}); support both.
                discovered: dict[str, str] = {}  # sub_device_sn -> sub_device_type
                for key, value in all_device_info["data"].items():
                    parts = key.split(".")
                    if len(parts) >= 3:
                        sub_device_type, sub_device_sn = parts[0], parts[1]
                        discovered.setdefault(sub_device_sn, sub_device_type)
                    elif isinstance(value, dict):
                        # legacy nested shape: {sub_device_type: {sub_device_sn: {...}}}
                        for sub_device_sn, item in value.items():
                            if isinstance(item, (dict, list)):
                                discovered.setdefault(sub_device_sn, key)

                for sub_device_sn, sub_device_type in discovered.items():
                    if sub_device_sn == sn:
                        # some modules (e.g. "wireless") report under the parent's
                        # serial; skip to avoid overwriting the parent device entry
                        continue
                    self.new_data[CONF_DEVICE_LIST][sub_device_sn] = {
                        CONF_DEVICE_NAME: f"{device_data[CONF_DEVICE_NAME]}.{sub_device_type}.{sub_device_sn}",
                        CONF_DEVICE_TYPE: sub_device_type,
                        CONF_PARENT_SN: sn,
                    }
                    self.new_options[CONF_DEVICE_LIST][sub_device_sn] = self.new_options[CONF_DEVICE_LIST][sn]

            return self.async_create_entry(
                title=self._entry_title(),
                data=self.new_data,
                options=self.new_options,
            )

    def remove_device(self, sn: str):
        # Get the device registry
        device_reg: DeviceRegistry = dr.async_get(self.hass)

        if is_public_entry(self.config_entry.data):
            identifiers = {(ECOFLOW_DOMAIN, f"api-{sn}")}
        else:
            identifiers = {(ECOFLOW_DOMAIN, f"{sn}")}

        device = device_reg.async_get_device(identifiers=identifiers)
        _LOGGER.debug(".. getting device by %s: %s", str(identifiers), str(device))

        # Remove all entities for this device
        if getattr(device, "id", None) is not None:
            ent_reg: EntityRegistry = er.async_get(self.hass)
            entities = er.async_entries_for_device(ent_reg, device.id)

            for entity in entities:
                ent_reg.async_remove(entity.entity_id)

            # Remove the device from the device registry
            device_reg.async_remove_device(device.id)

    async def async_step_user(self, user_input: dict[str, Any] | None = None):
        if not self.config_entry:
            # One entry per EcoFlow account: what it groups (homes, rooms, packs) comes from
            # the account once logged in. The group only names the open-API MQTT client.
            self.new_data.setdefault(CONF_GROUP, DEFAULT_GROUP)
        return await self.async_step_choose_type()

    async def _adopt_existing_account(self) -> bool:
        """After the login of a new entry: when this account already has one, carry on as its reconfiguration."""
        if self.config_entry:
            return False
        if CONF_USERNAME in self.new_data:
            unique_id = f"account-{self.auth.user_id}"
            username = self.new_data[CONF_USERNAME].lower()

            def same(entry: ConfigEntry) -> bool:
                return str(entry.data.get(CONF_USERNAME, "")).lower() == username
        else:
            unique_id = f"open-{self.new_data[CONF_ACCESS_KEY]}"
            access_key = self.new_data[CONF_ACCESS_KEY]

            def same(entry: ConfigEntry) -> bool:
                return entry.data.get(CONF_ACCESS_KEY) == access_key and CONF_USERNAME not in entry.data

        existing = await self.async_set_unique_id(unique_id, raise_on_progress=False)
        if existing is None:
            # entries made before accounts were the key are found by their credentials
            existing = next((e for e in self.hass.config_entries.async_entries(ECOFLOW_DOMAIN) if same(e)), None)
        if existing is None:
            return False

        credentials = {k: v for k, v in self.new_data.items() if k in _CREDENTIAL_KEYS}
        self.set_current_config_entry(existing)
        # the credentials just entered win, e.g. developer keys added to an app-API entry
        self.new_data.update(credentials)
        self.set_local_device_list(list(extract_devices(existing).values()))
        return True

    def _account_menu(self):
        options = ["discover_devices", "manual_add_device", "remove_device", "finish"]
        if not is_hybrid_entry(self.new_data):
            options.insert(2, "open_api_keys")
        return self.async_show_menu(step_id="manual", menu_options=options)

    def _entry_title(self) -> str:
        return self.entry_title or self.new_data.get(CONF_USERNAME) or "EcoFlow"

    async def async_step_reconfigure(self, user_input: dict[str, Any] | None = None):
        self.set_current_config_entry(self.hass.config_entries.async_get_entry(self.context["entry_id"]))
        return await self.async_step_user()

    async def async_step_reauth(self, entry_data: Mapping[str, Any] | None = None):
        self.set_current_config_entry(self.hass.config_entries.async_get_entry(self.context["entry_id"]))
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(self, user_input: dict[str, Any] | None = None):
        public_api = is_public_entry(self.new_data)

        # HA fills "name" from the entry title on newer cores; set it so older ones match
        placeholders = {"name": self.config_entry.title if self.config_entry else ""}

        if not user_input:
            return self.async_show_form(
                step_id="reauth_confirm",
                data_schema=self._schema_for(public_api),
                description_placeholders=placeholders,
            )

        if public_api:
            self._set_api_credentials(user_input)
            self.auth = self._create_api_client()
        else:
            self._set_manual_credentials(user_input)
            self.auth = self._create_manual_client()

        errors: dict[str, str] = {}
        try:
            await self.auth.login()
        except EcoflowAuthException as e:
            errors["base"] = "invalid_access_key" if public_api else str(e)
        except EcoflowException as e:
            errors["base"] = str(e)
        except Exception:  # pylint: disable=broad-except
            _LOGGER.exception("Unexpected exception in reauth login action")
            return self.async_abort(reason="unknown")

        if errors:
            return self.async_show_form(
                step_id="reauth_confirm",
                data_schema=self._schema_for(public_api),
                errors=errors,
                description_placeholders=placeholders,
            )

        # credentials only: the device list and its options stay as they were
        self.hass.config_entries.async_update_entry(entry=self.config_entry, data=self.new_data)
        # unconditional: the entry is in a failed state even when the data did not change
        self.hass.config_entries.async_schedule_reload(self.config_entry.entry_id)
        return self.async_abort(reason="reauth_successful")

    async def async_step_choose_type(self, user_input: dict[str, Any] | None = None):
        if self.config_entry:  # reconfig flow
            if is_public_entry(self.config_entry.data):
                return await self.async_step_api()
            else:
                return await self.async_step_manual()

        if not user_input:
            return self.async_show_menu(step_id="choose_type", menu_options=["hybrid", "api", "manual"])

    def _manual_schema(self) -> vol.Schema:
        return vol.Schema(
            {
                vol.Required(
                    CONF_API_HOST, default=self.new_data.get(CONF_API_HOST, "api.ecoflow.com")
                ): _host_selector(APP_API_HOSTS),
                vol.Required(CONF_USERNAME, default=self.new_data.get(CONF_USERNAME, "")): str,
                vol.Required(CONF_PASSWORD, default=self.new_data.get(CONF_PASSWORD, "")): str,
            }
        )

    def _api_schema(self) -> vol.Schema:
        return vol.Schema(
            {
                vol.Required(
                    CONF_API_HOST, default=self.new_data.get(CONF_API_HOST, "api-e.ecoflow.com")
                ): _host_selector(OPEN_API_HOSTS),
                vol.Required(CONF_ACCESS_KEY, default=self.new_data.get(CONF_ACCESS_KEY, "")): str,
                vol.Required(CONF_SECRET_KEY, default=self.new_data.get(CONF_SECRET_KEY, "")): str,
            }
        )

    def _open_keys_fields(self) -> dict:
        return {
            vol.Required(
                CONF_OPEN_API_HOST, default=self.new_data.get(CONF_OPEN_API_HOST, DEFAULT_OPEN_API_HOST)
            ): _host_selector(OPEN_API_HOSTS),
            vol.Required(CONF_ACCESS_KEY, default=self.new_data.get(CONF_ACCESS_KEY, "")): str,
            vol.Required(CONF_SECRET_KEY, default=self.new_data.get(CONF_SECRET_KEY, "")): str,
        }

    def _hybrid_schema(self) -> vol.Schema:
        return vol.Schema(
            {
                vol.Required(
                    CONF_API_HOST, default=self.new_data.get(CONF_API_HOST, "api-e.ecoflow.com")
                ): _host_selector(APP_API_HOSTS),
                vol.Required(CONF_USERNAME, default=self.new_data.get(CONF_USERNAME, "")): str,
                vol.Required(CONF_PASSWORD, default=self.new_data.get(CONF_PASSWORD, "")): str,
                **self._open_keys_fields(),
            }
        )

    def _set_open_keys(self, user_input: dict[str, Any]) -> None:
        self.new_data[CONF_OPEN_API_HOST] = user_input.get(CONF_OPEN_API_HOST, DEFAULT_OPEN_API_HOST)
        self.new_data[CONF_ACCESS_KEY] = user_input.get(CONF_ACCESS_KEY, "").strip()
        self.new_data[CONF_SECRET_KEY] = user_input.get(CONF_SECRET_KEY, "").strip()

    def _create_hybrid_client(self):
        from .api.hybrid_api import EcoflowHybridApiClient

        return EcoflowHybridApiClient(
            self.new_data[CONF_API_HOST],
            self.new_data[CONF_USERNAME],
            self.new_data[CONF_PASSWORD],
            self.new_data[CONF_GROUP],
            self.new_data[CONF_OPEN_API_HOST],
            self.new_data[CONF_ACCESS_KEY],
            self.new_data[CONF_SECRET_KEY],
        )

    async def _login(self, client, open_keys: bool) -> dict[str, str]:
        errors: dict[str, str] = {}
        try:
            await client.login()
        except EcoflowAuthException as e:
            # 8513 is the open API's answer to a bad key; the app API names its own errors
            errors["base"] = "invalid_access_key" if open_keys and e.code == "8513" else str(e)
        except EcoflowException as e:
            errors["base"] = str(e)
        return errors

    async def async_step_hybrid(self, user_input: dict[str, Any] | None = None):
        """App login and developer keys: the open API wherever it serves a device, the app API for the rest."""
        if not user_input:
            return self.async_show_form(step_id="hybrid", data_schema=self._hybrid_schema())

        self._set_manual_credentials(user_input)
        self._set_open_keys(user_input)
        self.auth = self._create_hybrid_client()
        try:
            errors = await self._login(self.auth, open_keys=True)
        except Exception:  # pylint: disable=broad-except
            _LOGGER.exception("Unexpected exception in login action")
            return self.async_abort(reason="unknown")
        if errors:
            return self.async_show_form(step_id="hybrid", data_schema=self._hybrid_schema(), errors=errors)
        if await self._adopt_existing_account():
            return self._account_menu()
        return await self.async_step_discover_devices()

    async def async_step_open_api_keys(self, user_input: dict[str, Any] | None = None):
        """Add developer keys to an app-API entry, which then follows the open API too."""
        schema = vol.Schema(self._open_keys_fields())
        if not user_input:
            return self.async_show_form(step_id="open_api_keys", data_schema=schema)

        self._set_open_keys(user_input)
        from .api.public_api import EcoflowPublicApiClient

        client = EcoflowPublicApiClient(
            self.new_data[CONF_OPEN_API_HOST],
            self.new_data[CONF_ACCESS_KEY],
            self.new_data[CONF_SECRET_KEY],
            self.new_data[CONF_GROUP],
        )
        try:
            errors = await self._login(client, open_keys=True)
        except Exception:  # pylint: disable=broad-except
            _LOGGER.exception("Unexpected exception in login action")
            return self.async_abort(reason="unknown")
        if errors:
            return self.async_show_form(step_id="open_api_keys", data_schema=schema, errors=errors)
        return await self.update_or_create()

    async def async_step_discover_devices(self, user_input: dict[str, Any] | None = None):
        """Every device of the account, typed from its serial number, the supported ones preselected."""
        from .devices.sn_prefixes import is_unsupported

        if user_input is None:
            try:
                found = await self.auth.fetch_all_available_devices()
            except Exception:  # pylint: disable=broad-except
                _LOGGER.exception("Unexpected exception in fetch device action")
                return self.async_abort(reason="unknown")

            configured = self.new_data.get(CONF_DEVICE_LIST, {})
            self.discovered = {d.sn: d for d in found if not is_unsupported(d.sn)}
            labels = {}
            preselected = []
            for sn, device in self.discovered.items():
                known = device.device_type != "DIAGNOSTIC"
                current = configured.get(sn, {}).get(CONF_DEVICE_TYPE)
                note = "" if current is None else f", configured as {current}"
                labels[sn] = f"{device.name} ({device.device_type if known else 'type unknown'}{note})"
                if known and current != device.device_type:
                    preselected.append(sn)
            if not labels:
                return self.async_abort(reason="no_device_to_add")

            return self.async_show_form(
                step_id="discover_devices",
                data_schema=vol.Schema(
                    {
                        vol.Optional(CONF_DISCOVERED, default=preselected): cv.multi_select(labels),
                        vol.Optional(
                            CONF_AUTO_ADD_DEVICES, default=self.new_data.get(CONF_AUTO_ADD_DEVICES, True)
                        ): bool,
                    }
                ),
            )

        if CONF_DEVICE_LIST not in self.new_data:
            self.new_data[CONF_DEVICE_LIST] = {}
            self.new_options[CONF_DEVICE_LIST] = {}
        self.new_data[CONF_AUTO_ADD_DEVICES] = user_input.get(CONF_AUTO_ADD_DEVICES, True)
        for sn in user_input.get(CONF_DISCOVERED, []):
            device = self.discovered[sn]
            existing = self.new_data[CONF_DEVICE_LIST].get(sn, {})
            self.new_data[CONF_DEVICE_LIST][sn] = {
                # keep a name the user gave; the type follows the serial
                CONF_DEVICE_NAME: existing.get(CONF_DEVICE_NAME, device.name),
                CONF_DEVICE_TYPE: device.device_type,
            }
            self.new_options[CONF_DEVICE_LIST].setdefault(sn, default_device_options(device.device_type))
        if not self.new_data[CONF_DEVICE_LIST]:
            return self.async_abort(reason="no_device_to_add")
        if not self.config_entry:
            self.entry_title = await self._home_name(list(self.new_data[CONF_DEVICE_LIST]))
        return await self.update_or_create()

    async def _home_name(self, sns: list[str]) -> str | None:
        """The name of the app's home holding these devices, to title the entry."""
        fetch = getattr(self.auth, "fetch_device_spaces", None)
        if fetch is None:
            return None
        try:
            spaces = await fetch(sns)
        except Exception as e:  # pylint: disable=broad-except
            _LOGGER.debug("No space names: %s", e)
            return None
        return next((space.name for space in spaces.values() if space.is_root and space.name), None)

    def _schema_for(self, public_api: bool) -> vol.Schema:
        return self._api_schema() if public_api else self._manual_schema()

    def _set_manual_credentials(self, user_input: dict[str, Any]) -> None:
        self.new_data[CONF_API_HOST] = user_input.get(CONF_API_HOST)
        self.new_data[CONF_USERNAME] = user_input.get(CONF_USERNAME)
        self.new_data[CONF_PASSWORD] = user_input.get(CONF_PASSWORD)

    def _set_api_credentials(self, user_input: dict[str, Any]) -> None:
        self.new_data[CONF_API_HOST] = user_input.get(CONF_API_HOST)
        # keys get pasted from the developer portal, often with stray whitespace that breaks the signature
        self.new_data[CONF_ACCESS_KEY] = user_input.get(CONF_ACCESS_KEY, "").strip()
        self.new_data[CONF_SECRET_KEY] = user_input.get(CONF_SECRET_KEY, "").strip()

    def _create_manual_client(self):
        from .api.private_api import EcoflowPrivateApiClient

        return EcoflowPrivateApiClient(
            self.new_data[CONF_API_HOST],
            self.new_data[CONF_USERNAME],
            self.new_data[CONF_PASSWORD],
            self.new_data[CONF_GROUP],
        )

    def _create_api_client(self):
        from .api.public_api import EcoflowPublicApiClient

        return EcoflowPublicApiClient(
            self.new_data[CONF_API_HOST],
            self.new_data[CONF_ACCESS_KEY],
            self.new_data[CONF_SECRET_KEY],
            self.new_data[CONF_GROUP],
        )

    async def async_step_manual(self, user_input: dict[str, Any] | None = None):
        if not user_input:
            return self.async_show_form(step_id="manual", data_schema=self._manual_schema())

        self._set_manual_credentials(user_input)
        self.auth = self._create_manual_client()

        errors: dict[str, str] = {}
        try:
            await self.auth.login()
        except EcoflowException as e:  # pylint: disable=broad-except
            errors["base"] = str(e)
        except Exception:  # pylint: disable=broad-except
            _LOGGER.exception("Unexpected exception in login action")
            return self.async_abort(reason="unknown")

        if errors:
            return self.async_show_form(step_id="manual", data_schema=self._manual_schema(), errors=errors)

        if self.config_entry:  # reconfig flow
            devices = extract_devices(self.config_entry)
            self.set_local_device_list(list(devices.values()))
            if is_hybrid_entry(self.new_data):
                # validate with the stored keys too, so discovery reports open-API status
                self.auth = self._create_hybrid_client()
                try:
                    await self.auth.login()
                except Exception as e:  # pylint: disable=broad-except
                    _LOGGER.warning("Open-API login failed, using the app API alone: %s", e)
                    self.auth = self._create_manual_client()
                    await self.auth.login()

            return self._account_menu()
        if await self._adopt_existing_account():
            return self._account_menu()
        return await self.async_step_discover_devices()

    async def async_step_manual_add_device(self, user_input: dict[str, Any] | None = None):
        return await self.async_step_manual_device_input()

    async def async_step_manual_device_input(self, user_input: dict[str, Any] | None = None):
        from .devices.registry import devices

        if not user_input:
            device_list = list(devices.keys())
            device_list.remove("DIAGNOSTIC")
            return self.async_show_form(
                step_id="manual_device_input",
                data_schema=vol.Schema(
                    {
                        vol.Required(CONF_DEVICE_TYPE): selector.SelectSelector(
                            selector.SelectSelectorConfig(
                                options=device_list,
                                mode=selector.SelectSelectorMode.DROPDOWN,
                            ),
                        ),
                        vol.Required(CONF_DEVICE_NAME): str,
                        vol.Required(CONF_DEVICE_ID): str,
                    }
                ),
            )

        device = devices[user_input[CONF_DEVICE_TYPE]]

        sn = user_input[CONF_DEVICE_ID]
        if CONF_DEVICE_LIST not in self.new_data:
            self.new_data[CONF_DEVICE_LIST] = {}
            self.new_options[CONF_DEVICE_LIST] = {}

        self.new_data[CONF_DEVICE_LIST][sn] = {
            CONF_DEVICE_NAME: user_input[CONF_DEVICE_NAME],
            CONF_DEVICE_TYPE: user_input[CONF_DEVICE_TYPE],
        }
        self.new_options[CONF_DEVICE_LIST][sn] = {
            OPTS_REFRESH_PERIOD_SEC: DEFAULT_REFRESH_PERIOD_SEC,
            OPTS_POWER_STEP: device.default_charging_power_step(),
            OPTS_DIAGNOSTIC_MODE: False,
            OPTS_VERBOSE_STATUS_MODE: False,
            OPTS_ASSUME_OFFLINE_SEC: DEFAULT_ASSUME_OFFLINE_SEC,
            OPTS_RESET_SENSORS_ON_OFFLINE: DEFAULT_RESET_SENSORS_ON_OFFLINE,
            OPTS_ENERGY_UPDATE_INTERVAL_SEC: DEFAULT_ENERGY_UPDATE_INTERVAL_SEC,
        }

        return await self.update_or_create()

    async def async_step_api(self, user_input: dict[str, Any] | None = None):
        if not user_input:
            return self.async_show_form(step_id="api", data_schema=self._api_schema())

        self._set_api_credentials(user_input)
        self.auth = self._create_api_client()

        errors: dict[str, str] = {}
        try:
            await self.auth.login()
        except EcoflowAuthException:
            errors["base"] = "invalid_access_key"
        except EcoflowException as e:  # pylint: disable=broad-except
            errors["base"] = str(e)
        except Exception:  # pylint: disable=broad-except
            _LOGGER.exception("Unexpected exception in login action")
            return self.async_abort(reason="unknown")

        if errors:
            # rebuilt, not reused: the schema defaults now carry the credentials just entered
            return self.async_show_form(step_id="api", data_schema=self._api_schema(), errors=errors)

        if self.config_entry:  # reconfig flow
            devices = extract_devices(self.config_entry)
            self.set_local_device_list(list(devices.values()))

            return self.async_show_menu(
                step_id="api",
                menu_options=["api_add_device", "remove_device", "finish"],
            )
        if await self._adopt_existing_account():
            return self.async_show_menu(step_id="api", menu_options=["api_add_device", "remove_device", "finish"])
        return await self.async_step_select_device()

    async def async_step_api_add_device(self, user_input: dict[str, Any] | None = None):
        return await self.async_step_select_device()

    async def async_step_finish(self, user_input: dict[str, Any] | None = None):
        return await self.update_or_create()

    async def async_step_remove_device(self, user_input: dict[str, Any] | None = None):
        if len(self.local_devices) == 1:
            return self.async_abort(reason="remove_last_device")

        if not user_input:
            return self.async_show_form(
                step_id="remove_device",
                last_step=True,
                data_schema=vol.Schema({vol.Required(CONF_SELECT_DEVICE_KEY): vol.In(list(self.local_devices))}),
            )
        target_device = self.local_devices[user_input[CONF_SELECT_DEVICE_KEY]]
        if target_device.sn in self.new_data[CONF_DEVICE_LIST]:
            self.new_data[CONF_DEVICE_LIST].pop(target_device.sn)

        self.remove_device(target_device.sn)
        return await self.update_or_create()

    async def async_step_select_device(self, user_input: dict[str, Any] | None = None):
        if not user_input:
            try:
                devices = await self.auth.fetch_all_available_devices()
                self.set_device_list(devices)
            except Exception:  # pylint: disable=broad-except
                _LOGGER.exception("Unexpected exception in fetch device action")
                return self.async_abort(reason="unknown")

            target_devices = [k for k, v in self.cloud_devices.items() if k not in self.local_devices]
            if len(target_devices) < 1:
                return self.async_abort(reason="no_device_to_add")

            return self.async_show_form(
                step_id="select_device",
                data_schema=vol.Schema({vol.Required(CONF_SELECT_DEVICE_KEY): vol.In(list(target_devices))}),
            )

        self.cloud_device = self.cloud_devices[user_input[CONF_SELECT_DEVICE_KEY]]

        return await self.async_step_confirm_cloud_device()

    async def async_step_confirm_cloud_device(self, user_input: dict[str, Any] | None = None):
        from .devices.registry import device_by_product

        if not user_input:
            device_list = list(device_by_product.keys())
            return self.async_show_form(
                step_id="confirm_cloud_device",
                data_schema=vol.Schema(
                    {
                        vol.Required(CONF_DEVICE_TYPE, default=self.cloud_device.device_type): selector.SelectSelector(
                            selector.SelectSelectorConfig(
                                options=device_list,
                                mode=selector.SelectSelectorMode.DROPDOWN,
                            ),
                        ),
                        vol.Required(CONF_DEVICE_NAME, default=self.cloud_device.name): str,
                        vol.Required(CONF_DEVICE_ID, default=self.cloud_device.sn): str,
                    }
                ),
            )

        device = device_by_product[user_input[CONF_DEVICE_TYPE]]

        sn = user_input[CONF_DEVICE_ID]

        if CONF_DEVICE_LIST not in self.new_data:
            self.new_data[CONF_DEVICE_LIST] = {}
            self.new_options[CONF_DEVICE_LIST] = {}

        self.new_data[CONF_DEVICE_LIST][sn] = {
            CONF_DEVICE_NAME: user_input[CONF_DEVICE_NAME],
            CONF_DEVICE_TYPE: user_input[CONF_DEVICE_TYPE],
        }
        self.new_options[CONF_DEVICE_LIST][sn] = {
            OPTS_REFRESH_PERIOD_SEC: DEFAULT_REFRESH_PERIOD_SEC,
            OPTS_POWER_STEP: device.default_charging_power_step(),
            OPTS_DIAGNOSTIC_MODE: ("Diagnostic".lower() == user_input[CONF_DEVICE_TYPE].lower()),
            OPTS_VERBOSE_STATUS_MODE: False,
            OPTS_ASSUME_OFFLINE_SEC: DEFAULT_ASSUME_OFFLINE_SEC,
            OPTS_RESET_SENSORS_ON_OFFLINE: DEFAULT_RESET_SENSORS_ON_OFFLINE,
            OPTS_ENERGY_UPDATE_INTERVAL_SEC: DEFAULT_ENERGY_UPDATE_INTERVAL_SEC,
        }

        return await self.update_or_create()

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> EcoflowOptionsFlow:
        return EcoflowOptionsFlow()


class EcoflowOptionsFlow(OptionsFlow):
    def __init__(self) -> None:
        # HA 2024.12+: config_entry is auto-injected by the framework after __init__.
        # Device extraction is deferred to async_step_init.
        self.devices: dict[str, DeviceData] = {}
        self.device_selector = {}
        self.selected_device = None

    def _ensure_devices_loaded(self) -> None:
        if not self.device_selector:
            self.devices = extract_devices(self.config_entry)
            for device in self.devices.values():
                self.device_selector[f"{device.name} ({device.sn})"] = device

    async def async_step_init(self, user_input: dict[str, Any] | None = None):
        self._ensure_devices_loaded()
        if user_input is None:
            return self.async_show_form(
                step_id="init",
                data_schema=vol.Schema(
                    {vol.Required(CONF_SELECT_DEVICE_KEY): vol.In(list(self.device_selector.keys()))}
                ),
            )

        self.selected_device = self.device_selector[user_input[CONF_SELECT_DEVICE_KEY]]
        return await self.async_step_options()

    async def async_step_options(self, user_input: dict[str, Any] | None = None):
        if user_input is None:
            device_options: DeviceOptions = self.devices[self.selected_device.sn].options

            return self.async_show_form(
                step_id="options",
                last_step=True,
                data_schema=vol.Schema(
                    {
                        vol.Required(OPTS_POWER_STEP, default=device_options.power_step): int,
                        vol.Required(
                            OPTS_REFRESH_PERIOD_SEC,
                            default=device_options.refresh_period,
                        ): int,
                        vol.Required(OPTS_DIAGNOSTIC_MODE, default=device_options.diagnostic_mode): bool,
                        vol.Required(OPTS_VERBOSE_STATUS_MODE, default=device_options.verbose_status_mode): bool,
                        vol.Required(OPTS_ASSUME_OFFLINE_SEC, default=device_options.assume_offline_sec): int,
                        vol.Required(
                            OPTS_RESET_SENSORS_ON_OFFLINE,
                            default=device_options.reset_sensors_on_offline,
                        ): bool,
                        vol.Required(
                            OPTS_ENERGY_UPDATE_INTERVAL_SEC,
                            default=device_options.energy_update_interval,
                        ): vol.All(int, vol.Range(min=0)),
                    }
                ),
            )

        # Copy the nested device list too. A shallow copy edits the entry's live options in place, so HA
        # compares the result to itself, sees no change, and neither saves the options nor reloads.
        new_options = {**self.config_entry.options}
        new_options[CONF_DEVICE_LIST] = {**self.config_entry.options[CONF_DEVICE_LIST]}
        new_options[CONF_DEVICE_LIST][self.selected_device.sn] = {
            OPTS_POWER_STEP: user_input[OPTS_POWER_STEP],
            OPTS_REFRESH_PERIOD_SEC: user_input[OPTS_REFRESH_PERIOD_SEC],
            OPTS_DIAGNOSTIC_MODE: user_input[OPTS_DIAGNOSTIC_MODE],
            OPTS_VERBOSE_STATUS_MODE: user_input[OPTS_VERBOSE_STATUS_MODE],
            OPTS_ASSUME_OFFLINE_SEC: user_input[OPTS_ASSUME_OFFLINE_SEC],
            OPTS_RESET_SENSORS_ON_OFFLINE: user_input[OPTS_RESET_SENSORS_ON_OFFLINE],
            OPTS_ENERGY_UPDATE_INTERVAL_SEC: user_input[OPTS_ENERGY_UPDATE_INTERVAL_SEC],
        }

        return self.async_create_entry(title="", data=new_options)
