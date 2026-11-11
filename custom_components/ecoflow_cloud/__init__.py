import logging
from collections.abc import Mapping
from typing import Any, Final

import aiohttp
from homeassistant.components.diagnostics import async_redact_data
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed, ConfigEntryNotReady
from homeassistant.helpers import entity_registry as er

from custom_components.ecoflow_cloud.api import (
    EcoflowApiClient,
    EcoflowAuthException,
    EcoflowException,
)

from . import _preload_proto  # noqa: F401 # pyright: ignore[reportUnusedImport]
from .device_data import DeviceData, DeviceOptions

_LOGGER = logging.getLogger(__name__)

ECOFLOW_DOMAIN = "ecoflow_cloud"
CONFIG_VERSION = 13

_PLATFORMS = {
    Platform.BINARY_SENSOR,
    Platform.BUTTON,
    Platform.NUMBER,
    Platform.SELECT,
    Platform.SENSOR,
    Platform.SWITCH,
    Platform.CLIMATE,
}

ATTR_STATUS_SN = "SN"
ATTR_STATUS_UPDATES = "status_request_count"
ATTR_DATA_UPDATES = "data_update_count"
ATTR_STATUS_LAST_UPDATE = "status_last_update"
ATTR_STATUS_DATA_LAST_UPDATE = "data_last_update"
ATTR_MQTT_CONNECTED = "mqtt_connected"
ATTR_STATUS_RECONNECTS = "reconnects"
ATTR_STATUS_PHASE = "status_phase"
ATTR_QUOTA_REQUESTS = "quota_requests"

CONF_AUTH_TYPE: Final = "auth_type"

CONF_USERNAME: Final = "username"
CONF_PASSWORD: Final = "password"

CONF_API_HOST: Final = "api_host"
# Open-API host of a hybrid entry (app login plus developer keys); api_host stays the app API's
CONF_OPEN_API_HOST: Final = "open_api_host"
DEFAULT_OPEN_API_HOST: Final = "api-e.ecoflow.com"
CONF_ACCESS_KEY: Final = "access_key"
CONF_SECRET_KEY: Final = "secret_key"
CONF_GROUP: Final = "group"
CONF_TO_REDACT: Final = {CONF_USERNAME, CONF_PASSWORD, CONF_ACCESS_KEY, CONF_SECRET_KEY}
CONF_DEVICE_LIST: Final = "devices_list"
# Add the account's devices of a known type at each start, so a new device needs no reconfiguration
CONF_AUTO_ADD_DEVICES: Final = "auto_add_devices"
CONF_ENTRY_ID: Final = "entry_id"

CONF_SELECT_DEVICE_KEY: Final = "select_device"

CONF_DEVICE_TYPE: Final = "device_type"
CONF_DEVICE_NAME: Final = "device_name"
CONF_DEVICE_ID: Final = "device_id"
CONF_PARENT_SN: Final = "parent_sn"
OPTS_DIAGNOSTIC_MODE: Final = "diagnostic_mode"
OPTS_POWER_STEP: Final = "power_step"
OPTS_REFRESH_PERIOD_SEC: Final = "refresh_period_sec"
OPTS_ASSUME_OFFLINE_SEC: Final = "assume_offline_sec"
OPTS_VERBOSE_STATUS_MODE: Final = "verbose_status_mode"
OPTS_RESET_SENSORS_ON_OFFLINE: Final = "reset_sensors_on_offline"
OPTS_ENERGY_UPDATE_INTERVAL_SEC: Final = "energy_update_interval_sec"

DEFAULT_REFRESH_PERIOD_SEC: Final = 5
DEFAULT_ASSUME_OFFLINE_SEC: Final = 300  # 5 minutes
DEFAULT_RESET_SENSORS_ON_OFFLINE: Final = True
DEFAULT_ENERGY_UPDATE_INTERVAL_SEC: Final = 0  # 0 = write on every source update

_STATUS_COORDINATOR_KEY = "__status_coordinator"


def _migrate_entity_unique_id(
    hass: HomeAssistant,
    platform: Platform,
    old_unique_id: str,
    new_unique_id: str,
) -> bool:
    registry = er.async_get(hass)
    entity_id = registry.async_get_entity_id(platform, ECOFLOW_DOMAIN, old_unique_id)
    if entity_id is None:
        return False
    if registry.async_get_entity_id(platform, ECOFLOW_DOMAIN, new_unique_id) is not None:
        return False

    registry.async_update_entity(entity_id, new_unique_id=new_unique_id)
    return True


async def async_migrate_entry(hass: HomeAssistant, config_entry: ConfigEntry):
    updated: bool = False
    if config_entry.version in (5, 6):
        new_data = dict(config_entry.data)
        new_options = dict(config_entry.options)
        new_devices = dict[str, Any]()
        for sn, device_info in config_entry.data[CONF_DEVICE_LIST].items():
            new_devices[sn] = {
                CONF_DEVICE_NAME: device_info[CONF_DEVICE_NAME],
                CONF_DEVICE_TYPE: device_info[CONF_DEVICE_TYPE],
                "options": {
                    OPTS_REFRESH_PERIOD_SEC: config_entry.options[CONF_DEVICE_LIST][sn][OPTS_REFRESH_PERIOD_SEC],
                    OPTS_POWER_STEP: config_entry.options[CONF_DEVICE_LIST][sn][OPTS_POWER_STEP],
                    OPTS_DIAGNOSTIC_MODE: config_entry.options[CONF_DEVICE_LIST][sn][OPTS_DIAGNOSTIC_MODE],
                },
            }

        # remove options for the devices, because they are now part of the devices
        new_options.pop(CONF_DEVICE_LIST)
        # update the data with the class structured data
        new_data[CONF_DEVICE_LIST] = new_devices
        # update the entry in home assistant
        updated = hass.config_entries.async_update_entry(
            config_entry,
            version=7,
            data=new_data,
            options=new_options,
        )
        _LOGGER.info("Config entries updated to version %d", config_entry.version)

    if config_entry.version == 7:
        new_data = dict(config_entry.data)
        is_api = CONF_ACCESS_KEY in config_entry.data
        if is_api:
            new_data[CONF_API_HOST] = "api-e.ecoflow.com"
        else:
            new_data[CONF_API_HOST] = "api.ecoflow.com"

        updated = hass.config_entries.async_update_entry(config_entry, version=8, data=new_data)
        _LOGGER.info("Config entries updated to version %d", config_entry.version)

    if config_entry.version == 8:
        # fix fields and revert options
        new_data = dict(config_entry.data)
        new_options = {CONF_DEVICE_LIST: {}}
        new_data.pop("load_all_devices", None)

        for sn, device_info in new_data[CONF_DEVICE_LIST].items():
            if "name" in device_info:
                new_data[CONF_DEVICE_LIST][sn][CONF_DEVICE_NAME] = new_data[CONF_DEVICE_LIST][sn].pop("name")
                new_data[CONF_DEVICE_LIST][sn].pop("sn", None)

            new_options[CONF_DEVICE_LIST][sn] = new_data[CONF_DEVICE_LIST][sn].pop("options")

            if "refresh_period" in new_options[CONF_DEVICE_LIST][sn]:
                new_options[CONF_DEVICE_LIST][sn][OPTS_REFRESH_PERIOD_SEC] = new_options[CONF_DEVICE_LIST][sn].pop(
                    "refresh_period"
                )

        updated = hass.config_entries.async_update_entry(config_entry, version=9, data=new_data, options=new_options)
        _LOGGER.info("Config entries updated to version %d", config_entry.version)

    if config_entry.version == 9:
        new_options = dict(config_entry.options)
        for sn, device_options in new_options[CONF_DEVICE_LIST].items():
            device_options[OPTS_VERBOSE_STATUS_MODE] = False
            device_options[OPTS_ASSUME_OFFLINE_SEC] = DEFAULT_ASSUME_OFFLINE_SEC

        updated = hass.config_entries.async_update_entry(config_entry, version=10, options=new_options)
        _LOGGER.info("Config entries updated to version %d", config_entry.version)

    if config_entry.version == 10:
        if CONF_ACCESS_KEY in config_entry.data:
            for sn, device_info in config_entry.data[CONF_DEVICE_LIST].items():
                if device_info[CONF_DEVICE_TYPE] not in ("PowerStream", "Power Ocean"):
                    continue

                migrated = _migrate_entity_unique_id(
                    hass,
                    Platform.SENSOR,
                    f"ecoflow-api-{sn}-status-scheduled",
                    f"ecoflow-api-{sn}-status",
                )
                if migrated:
                    _LOGGER.info("Migrated scheduled status entity unique ID for %s", sn)

        updated = hass.config_entries.async_update_entry(config_entry, version=11)
        _LOGGER.info("Config entries updated to version %d", config_entry.version)

    if config_entry.version == 11:
        # River 2 / River 2 Max solar sensors moved off inv.dcIn*, which stays at 0
        # on these devices, onto the live mppt.* telemetry.
        if CONF_ACCESS_KEY not in config_entry.data:
            for sn, device_info in config_entry.data[CONF_DEVICE_LIST].items():
                if device_info[CONF_DEVICE_TYPE] not in ("RIVER_2", "RIVER_2_MAX"):
                    continue

                for old_key, new_key in (("inv-dcInAmp", "mppt-inAmp"), ("inv-dcInVol", "mppt-inVol")):
                    migrated = _migrate_entity_unique_id(
                        hass,
                        Platform.SENSOR,
                        f"ecoflow-{sn}-{old_key}",
                        f"ecoflow-{sn}-{new_key}",
                    )
                    if migrated:
                        _LOGGER.info("Migrated %s entity unique ID to %s for %s", old_key, new_key, sn)

        updated = hass.config_entries.async_update_entry(config_entry, version=12)
        _LOGGER.info("Config entries updated to version %d", config_entry.version)

    if config_entry.version == 12:
        new_options = dict(config_entry.options)
        for device_options in new_options[CONF_DEVICE_LIST].values():
            device_options[OPTS_RESET_SENSORS_ON_OFFLINE] = DEFAULT_RESET_SENSORS_ON_OFFLINE

        updated = hass.config_entries.async_update_entry(config_entry, version=13, options=new_options)
        _LOGGER.info("Config entries updated to version %d", config_entry.version)

    return updated


def is_hybrid_entry(data: Mapping[str, Any]) -> bool:
    return CONF_USERNAME in data and CONF_ACCESS_KEY in data


def is_public_entry(data: Mapping[str, Any]) -> bool:
    """Open-API only. Hybrid entries keep the app API's device identifiers, so they are not."""
    return CONF_ACCESS_KEY in data and CONF_USERNAME not in data


def extract_devices(entry: ConfigEntry) -> dict[str, DeviceData]:
    result = dict[str, DeviceData]()
    for sn, data in entry.data[CONF_DEVICE_LIST].items():
        result[sn] = DeviceData(
            sn,
            data[CONF_DEVICE_NAME],
            data[CONF_DEVICE_TYPE],
            DeviceOptions(
                entry.options[CONF_DEVICE_LIST][sn][OPTS_REFRESH_PERIOD_SEC],
                entry.options[CONF_DEVICE_LIST][sn][OPTS_POWER_STEP],
                entry.options[CONF_DEVICE_LIST][sn][OPTS_DIAGNOSTIC_MODE],
                entry.options[CONF_DEVICE_LIST][sn][OPTS_VERBOSE_STATUS_MODE],
                entry.options[CONF_DEVICE_LIST][sn][OPTS_ASSUME_OFFLINE_SEC],
                entry.options[CONF_DEVICE_LIST][sn][OPTS_RESET_SENSORS_ON_OFFLINE],
                # Read with a default instead of a VERSION bump + migration: an absent key simply means
                # "off", and keeping the entry version unchanged lets a user roll back to an older
                # release without "migration failed".
                entry.options[CONF_DEVICE_LIST][sn].get(
                    OPTS_ENERGY_UPDATE_INTERVAL_SEC, DEFAULT_ENERGY_UPDATE_INTERVAL_SEC
                ),
            ),
            None,
            None,
        )

    for sn, data in entry.data[CONF_DEVICE_LIST].items():
        if CONF_PARENT_SN in data:
            result[sn].parent = result[data[CONF_PARENT_SN]]

    return result


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry):
    if entry.version != CONFIG_VERSION:
        return False

    _LOGGER.info("Setup entry %s (data = %s)", str(entry), async_redact_data(entry.data, CONF_TO_REDACT))
    api_client: EcoflowApiClient
    if ECOFLOW_DOMAIN not in hass.data:
        hass.data[ECOFLOW_DOMAIN] = {}
    if is_hybrid_entry(entry.data):
        from .api.hybrid_api import EcoflowHybridApiClient

        api_client = EcoflowHybridApiClient(
            entry.data[CONF_API_HOST],
            entry.data[CONF_USERNAME],
            entry.data[CONF_PASSWORD],
            entry.data[CONF_GROUP],
            entry.data.get(CONF_OPEN_API_HOST, DEFAULT_OPEN_API_HOST),
            entry.data[CONF_ACCESS_KEY],
            entry.data[CONF_SECRET_KEY],
        )
    elif CONF_USERNAME in entry.data and CONF_PASSWORD in entry.data:
        from .api.private_api import EcoflowPrivateApiClient

        api_client = EcoflowPrivateApiClient(
            entry.data[CONF_API_HOST],
            entry.data[CONF_USERNAME],
            entry.data[CONF_PASSWORD],
            entry.data[CONF_GROUP],
        )

    elif CONF_ACCESS_KEY in entry.data and CONF_SECRET_KEY in entry.data:
        from .api.public_api import EcoflowPublicApiClient

        api_client = EcoflowPublicApiClient(
            entry.data[CONF_API_HOST],
            entry.data[CONF_ACCESS_KEY],
            entry.data[CONF_SECRET_KEY],
            entry.data[CONF_GROUP],
        )
    else:
        return False

    devices_list: dict[str, DeviceData] = extract_devices(entry)
    # Try to connect and authenticate
    try:
        await api_client.login()
    except (ConnectionError, TimeoutError, aiohttp.ClientError) as ex:
        # Transient network issues - retry later. aiohttp's connector errors are not
        # ConnectionError subclasses, so they need naming separately
        _LOGGER.warning("Failed to connect to EcoFlow API: %s", ex)
        raise ConfigEntryNotReady(f"Connection failed: {ex}") from ex
    except EcoflowAuthException as ex:
        # Ask the user for new credentials instead of retrying with the rejected ones
        raise ConfigEntryAuthFailed(str(ex)) from ex
    except EcoflowException as ex:
        # Any other API error may well be transient - let HA retry with backoff
        _LOGGER.warning("EcoFlow API login failed: %s", ex)
        raise ConfigEntryNotReady(f"Login failed: {ex}") from ex

    # Fetch current device statuses from API
    try:
        api_devices = await api_client.fetch_all_available_devices()
        api_devices_map = {d.sn: d for d in api_devices}
    except Exception as ex:
        _LOGGER.warning("Failed to fetch device statuses: %s", ex)
        api_devices_map = None

    if entry.data.get(CONF_AUTO_ADD_DEVICES) and api_devices_map:
        devices_list.update(_add_new_account_devices(hass, entry, api_devices_map.values()))

    for device_data in devices_list.values():
        device = api_client.configure_device(device_data, api_devices_map)
        device.configure(hass)

    spaces = await _fetch_spaces(api_client)
    for sn, space in spaces.items():
        if not space.is_root and sn in api_client.devices:
            # a room of the app's home becomes the device's suggested area
            api_client.devices[sn].suggested_area = space.name

    packs = await _discover_packs(api_client, spaces)
    if packs:
        # packs first, so their device is registered before the units that point at it
        units = list(api_client.devices.items())
        api_client.devices.clear()
        for pack in packs:
            api_client.add_device(pack)
            pack.configure(hass)
        api_client.devices.update(units)

    def request_reauth() -> None:
        # called from the paho thread once EcoFlow rejects the MQTT credentials
        hass.loop.call_soon_threadsafe(entry.async_start_reauth, hass)

    api_client.on_auth_failure = request_reauth
    await hass.async_add_executor_job(api_client.start)
    hass.data[ECOFLOW_DOMAIN][entry.entry_id] = api_client

    # Must load all device data before configuring devices because the data
    # is used for entity setup.
    await api_client.quota_all(None)

    for device in api_client.devices.values():
        await device.async_restore_state()

    # Forward entry setup to the platforms to set up the entities
    await hass.config_entries.async_forward_entry_setups(entry, _PLATFORMS)

    # Register with the global status coordinator
    from .devices.status_coordinator import DeviceStatusCoordinator

    if _STATUS_COORDINATOR_KEY not in hass.data[ECOFLOW_DOMAIN]:
        hass.data[ECOFLOW_DOMAIN][_STATUS_COORDINATOR_KEY] = DeviceStatusCoordinator(hass)

    coordinator: DeviceStatusCoordinator = hass.data[ECOFLOW_DOMAIN][_STATUS_COORDINATOR_KEY]
    coordinator.register(entry.entry_id, api_client)
    await coordinator.async_request_refresh()

    entry.async_on_unload(entry.add_update_listener(update_listener))

    return True


def default_device_options(device_type: str) -> dict[str, Any]:
    from .devices.registry import devices

    device_class = devices.get(device_type, devices["DIAGNOSTIC"])
    return {
        OPTS_REFRESH_PERIOD_SEC: DEFAULT_REFRESH_PERIOD_SEC,
        OPTS_POWER_STEP: device_class.default_charging_power_step(),
        OPTS_DIAGNOSTIC_MODE: device_type.lower() == "diagnostic",
        OPTS_VERBOSE_STATUS_MODE: False,
        OPTS_ASSUME_OFFLINE_SEC: DEFAULT_ASSUME_OFFLINE_SEC,
        OPTS_RESET_SENSORS_ON_OFFLINE: DEFAULT_RESET_SENSORS_ON_OFFLINE,
        OPTS_ENERGY_UPDATE_INTERVAL_SEC: DEFAULT_ENERGY_UPDATE_INTERVAL_SEC,
    }


def _add_new_account_devices(hass: HomeAssistant, entry: ConfigEntry, found) -> dict[str, DeviceData]:
    """Store the account's devices this entry does not have yet, when their type is known."""
    from .devices.sn_prefixes import is_unsupported

    data = {**entry.data, CONF_DEVICE_LIST: dict(entry.data[CONF_DEVICE_LIST])}
    options = {**entry.options, CONF_DEVICE_LIST: dict(entry.options[CONF_DEVICE_LIST])}
    added = []
    for info in found:
        if info.sn in data[CONF_DEVICE_LIST] or info.device_type == "DIAGNOSTIC" or is_unsupported(info.sn):
            continue
        data[CONF_DEVICE_LIST][info.sn] = {CONF_DEVICE_NAME: info.name, CONF_DEVICE_TYPE: info.device_type}
        options[CONF_DEVICE_LIST][info.sn] = default_device_options(info.device_type)
        added.append(info.sn)
    if not added:
        return {}
    _LOGGER.info("Adding %d new device(s) found in the account", len(added))
    # before the update listener is registered, so this does not reload the entry
    hass.config_entries.async_update_entry(entry, data=data, options=options)
    new_devices = extract_devices(entry)
    return {sn: new_devices[sn] for sn in added}


async def _fetch_spaces(api_client: EcoflowApiClient) -> dict:
    fetch = getattr(api_client, "fetch_device_spaces", None)
    if fetch is None or not api_client.devices:
        return {}
    try:
        return await fetch(list(api_client.devices))
    except Exception as ex:
        _LOGGER.warning("Could not read the EcoFlow spaces of the devices: %s", ex)
        return {}


async def _discover_packs(api_client: EcoflowApiClient, spaces: dict | None = None) -> list:
    """Group linked STREAM units into the systems the app shows, when the API can list them."""
    fetch_systems = getattr(api_client, "fetch_systems", None)
    if fetch_systems is None:
        return []
    from .devices.internal.stream_ac_5000 import StreamAC5000
    from .devices.internal.stream_pack import build_packs

    sns = [sn for sn, device in api_client.devices.items() if isinstance(device, StreamAC5000)]
    if len(sns) < 2:
        return []
    try:
        systems = await fetch_systems(sns, spaces)
    except Exception as ex:
        # without the system list each unit still works on its own
        _LOGGER.warning("Could not list EcoFlow systems, STREAM units stay ungrouped: %s", ex)
        return []
    return build_packs(systems, api_client.devices)


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry):
    if not await hass.config_entries.async_unload_platforms(entry, _PLATFORMS):
        return False

    # Unregister from the global status coordinator
    coordinator = hass.data[ECOFLOW_DOMAIN].get(_STATUS_COORDINATOR_KEY)
    if coordinator is not None:
        coordinator.unregister(entry.entry_id)
        if coordinator.empty:
            hass.data[ECOFLOW_DOMAIN].pop(_STATUS_COORDINATOR_KEY)

    client = hass.data[ECOFLOW_DOMAIN].pop(entry.entry_id)
    client.stop()
    return True


async def update_listener(hass: HomeAssistant, entry: ConfigEntry) -> None:
    await hass.config_entries.async_reload(entry.entry_id)
