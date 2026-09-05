"""The FIMER (ABB / Power-One) integration."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Final

from modbus_connection import ModbusTcpParams

from homeassistant.components.modbus import async_get_unit
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_HOST, CONF_PASSWORD, CONF_PORT, CONF_USERNAME, Platform
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryError, HomeAssistantError
from homeassistant.helpers import config_validation as cv, device_registry as dr
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.typing import ConfigType

from .const import (
    CONF_BASE_ADDRESS,
    CONF_MIGRATE_FROM,
    CONF_POWER_CONTROL,
    CONF_REST_MODEL,
    CONF_REST_REQUIRES_AUTH,
    CONF_UNIT_ID,
    CONF_USE_MODBUS,
    CONF_USE_REST,
    DEFAULT_REST_USERNAME,
    DOMAIN,
)
from .coordinator import FimerCoordinator, FimerRestCoordinator, FimerSettingsCoordinator
from .devices import FimerDevice, build_devices
from .migration import async_take_over_legacy_entities
from .pyfimer.modbus import FimerModbusInverter
from .pyfimer.rest import FimerRestLogger, VsnModel
from .services import async_setup_services

PLATFORMS: Final = [Platform.NUMBER, Platform.SENSOR, Platform.SWITCH]
CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)


@dataclass
class FimerRuntimeData:
    """Runtime data of a FIMER config entry."""

    devices: list[FimerDevice] = field(default_factory=list)
    inverter: FimerModbusInverter | None = None
    coordinator: FimerCoordinator | None = None
    rest_logger: FimerRestLogger | None = None
    rest_coordinator: FimerRestCoordinator | None = None
    settings_coordinator: FimerSettingsCoordinator | None = None
    """Present only with the experimental power control option on model 123."""


type FimerConfigEntry = ConfigEntry[FimerRuntimeData]


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Register the integration's actions; entries are set up separately."""
    async_setup_services(hass)
    return True


async def async_setup_entry(hass: HomeAssistant, entry: FimerConfigEntry) -> bool:
    """Set up an inverter, over Modbus and/or its datalogger's REST API."""
    data = entry.data
    runtime = FimerRuntimeData()

    if data.get(CONF_USE_MODBUS, True):
        params = ModbusTcpParams(host=data[CONF_HOST], port=data[CONF_PORT])
        try:
            unit = async_get_unit(hass, entry, params, data[CONF_UNIT_ID])
        except HomeAssistantError as err:
            # another integration holds this device with different link settings
            raise ConfigEntryError(
                translation_domain=DOMAIN,
                translation_key="modbus_link_conflict",
                translation_placeholders={"host": data[CONF_HOST], "error": str(err)},
            ) from err
        runtime.inverter = FimerModbusInverter(unit, base_address=data[CONF_BASE_ADDRESS])
        runtime.coordinator = FimerCoordinator(hass, entry, runtime.inverter)
        await runtime.coordinator.async_config_entry_first_refresh()

    if data.get(CONF_USE_REST, False):
        model = data.get(CONF_REST_MODEL)
        runtime.rest_logger = FimerRestLogger(
            async_get_clientsession(hass),
            data[CONF_HOST],
            username=data.get(CONF_USERNAME, DEFAULT_REST_USERNAME),
            password=data.get(CONF_PASSWORD, ""),
            model=VsnModel(model) if model else None,
            requires_auth=data.get(CONF_REST_REQUIRES_AUTH, True),
        )
        runtime.rest_coordinator = FimerRestCoordinator(hass, entry, runtime.rest_logger)
        await runtime.rest_coordinator.async_config_entry_first_refresh()

    runtime.devices = build_devices(
        entry.title,
        entry.unique_id or entry.entry_id,
        runtime.coordinator,
        runtime.rest_coordinator,
    )
    _async_link_devices(hass, entry, runtime.devices)
    if runtime.rest_coordinator is not None:
        runtime.rest_coordinator.known_device_ids = set(runtime.rest_coordinator.data)

    if (
        entry.options.get(CONF_POWER_CONTROL)
        and runtime.inverter is not None
        and runtime.coordinator is not None
        and runtime.inverter.controls is not None
    ):
        runtime.settings_coordinator = FimerSettingsCoordinator(
            hass, entry, runtime.inverter, runtime.coordinator
        )
        await runtime.settings_coordinator.async_config_entry_first_refresh()

    entry.runtime_data = runtime
    if data.get(CONF_MIGRATE_FROM):
        await async_take_over_legacy_entities(hass, entry)
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


def _async_link_devices(
    hass: HomeAssistant, entry: FimerConfigEntry, devices: list[FimerDevice]
) -> None:
    """Register the datalogger first so the other devices can hang off it."""
    registry = dr.async_get(hass)
    datalogger = next((device for device in devices if device.device_type == "datalogger"), None)
    if datalogger is None:
        return
    logger_entry = registry.async_get_or_create(
        config_entry_id=entry.entry_id, **datalogger.device_info
    )
    for device in devices:
        if device is not datalogger:
            device.device_info["via_device_id"] = logger_entry.id


async def async_unload_entry(hass: HomeAssistant, entry: FimerConfigEntry) -> bool:
    """Unload a config entry; the shared Modbus connection closes with its last holder."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
