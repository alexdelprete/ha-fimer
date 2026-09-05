"""Number platform: the SunSpec power limit, experimental."""

from __future__ import annotations

from homeassistant.components.number import NumberEntity, NumberMode
from homeassistant.const import EntityCategory, UnitOfRatio
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
    """Add the power limit number when power control is enabled."""
    if (coordinator := entry.runtime_data.settings_coordinator) is None:
        return
    async_add_entities([FimerPowerLimitNumber(coordinator)])


class FimerPowerLimitNumber(FimerControlEntity, NumberEntity):
    """The active power limit as a percentage of the rated power (``WMaxLimPct``).

    Writing it while the limit is enabled re-asserts the enable flag, since
    some inverters only apply a new value on that write.
    """

    _attr_translation_key = "power_limit"
    _attr_entity_category = EntityCategory.CONFIG
    _attr_native_min_value = 0
    _attr_native_max_value = 100
    _attr_native_step = 1
    _attr_native_unit_of_measurement = UnitOfRatio.PERCENTAGE
    _attr_mode = NumberMode.BOX

    def __init__(self, coordinator: FimerSettingsCoordinator) -> None:
        """Set up the number on the settings coordinator."""
        super().__init__(coordinator, "power_limit")

    @property
    def native_value(self) -> float | None:
        """Return the limit the inverter reports."""
        return self.coordinator.data.get("WMaxLimPct")

    async def async_set_native_value(self, value: float) -> None:
        """Write the limit, re-enabling it when it is currently active."""
        enabled = self.coordinator.data.get("WMaxLim_Ena") == Enabled.ENABLED
        await self.coordinator.async_apply_power_limit(
            percent=int(value), enabled=True if enabled else None
        )
