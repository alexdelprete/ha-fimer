"""The FIMER (ABB / Power-One) integration."""

from __future__ import annotations

from dataclasses import dataclass
import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr

from .const import DOMAIN, MANUFACTURER, MODEL, VERSION

_LOGGER = logging.getLogger(__name__)

PLATFORMS: list[str] = ["sensor"]


@dataclass
class FimerData:
    """Runtime data for the FIMER (ABB / Power-One) integration."""

    device_name: str


type FimerConfigEntry = ConfigEntry[FimerData]


async def async_setup_entry(hass: HomeAssistant, entry: FimerConfigEntry) -> bool:
    """Set up FIMER (ABB / Power-One) from a config entry."""
    entry.runtime_data = FimerData(device_name=entry.title)

    # Register the device
    device_registry = dr.async_get(hass)
    device_registry.async_get_or_create(
        config_entry_id=entry.entry_id,
        identifiers={(DOMAIN, entry.unique_id or entry.entry_id)},
        manufacturer=MANUFACTURER,
        model=MODEL,
        name=entry.title,
        sw_version=VERSION,
    )

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: FimerConfigEntry) -> bool:
    """Unload a config entry."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
