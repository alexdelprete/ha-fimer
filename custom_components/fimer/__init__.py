"""The FIMER (ABB / Power-One) integration."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final

from modbus_connection import ModbusTcpParams

from homeassistant.components.modbus import async_get_unit
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_HOST, CONF_PORT, Platform
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryError, HomeAssistantError

from .const import CONF_BASE_ADDRESS, CONF_UNIT_ID, DOMAIN
from .coordinator import FimerCoordinator
from .pyfimer.modbus import FimerModbusInverter

PLATFORMS: Final = [Platform.SENSOR]


@dataclass
class FimerRuntimeData:
    """Runtime data of a FIMER config entry."""

    inverter: FimerModbusInverter
    coordinator: FimerCoordinator


type FimerConfigEntry = ConfigEntry[FimerRuntimeData]


async def async_setup_entry(hass: HomeAssistant, entry: FimerConfigEntry) -> bool:
    """Set up an inverter from a config entry."""
    params = ModbusTcpParams(host=entry.data[CONF_HOST], port=entry.data[CONF_PORT])
    try:
        unit = async_get_unit(hass, entry, params, entry.data[CONF_UNIT_ID])
    except HomeAssistantError as err:
        # another integration holds this device with different link settings
        raise ConfigEntryError(
            translation_domain=DOMAIN,
            translation_key="modbus_link_conflict",
            translation_placeholders={"host": entry.data[CONF_HOST], "error": str(err)},
        ) from err

    inverter = FimerModbusInverter(unit, base_address=entry.data[CONF_BASE_ADDRESS])
    coordinator = FimerCoordinator(hass, entry, inverter)
    await coordinator.async_config_entry_first_refresh()

    entry.runtime_data = FimerRuntimeData(inverter=inverter, coordinator=coordinator)
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: FimerConfigEntry) -> bool:
    """Unload a config entry; the shared Modbus connection closes with its last holder."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
