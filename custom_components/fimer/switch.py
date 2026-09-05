"""Switch platform: enabling the SunSpec power limit, experimental."""

from __future__ import annotations

from typing import Any

from homeassistant.components.switch import SwitchDeviceClass, SwitchEntity
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import FimerConfigEntry
from .coordinator import FimerSettingsCoordinator
from .entity import FimerControlEntity
from .pyfimer.modbus import Enabled

PARALLEL_UPDATES = 1


async def async_setup_entry(
    hass: HomeAssistant,
    entry: FimerConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Add the power limit switch when power control is enabled."""
    if (coordinator := entry.runtime_data.settings_coordinator) is None:
        return
    async_add_entities([FimerPowerLimitSwitch(coordinator)])


class FimerPowerLimitSwitch(FimerControlEntity, SwitchEntity):
    """Whether the active power limit is applied (``WMaxLim_Ena``)."""

    _attr_translation_key = "power_limit_enabled"
    _attr_entity_category = EntityCategory.CONFIG
    _attr_device_class = SwitchDeviceClass.SWITCH

    def __init__(self, coordinator: FimerSettingsCoordinator) -> None:
        """Set up the switch on the settings coordinator."""
        super().__init__(coordinator, "power_limit_enabled")

    @property
    def is_on(self) -> bool | None:
        """Return whether the limit is enabled."""
        if (value := self.coordinator.data.get("WMaxLim_Ena")) is None:
            return None
        return value == Enabled.ENABLED

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Apply the current limit value."""
        await self.coordinator.async_apply_power_limit(
            percent=self.coordinator.data.get("WMaxLimPct"), enabled=True
        )

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Lift the limit."""
        await self.coordinator.async_apply_power_limit(enabled=False)
