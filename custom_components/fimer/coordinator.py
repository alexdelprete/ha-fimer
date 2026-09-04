"""Polling coordinator for the FIMER (ABB / Power-One) integration."""

from __future__ import annotations

from datetime import timedelta
import logging
from typing import TYPE_CHECKING, Any

from modbus_connection import ModbusError

from homeassistant.const import CONF_HOST, CONF_SCAN_INTERVAL
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .const import (
    DEFAULT_SCAN_INTERVAL,
    DOMAIN,
    ERROR_SCAN_INTERVAL,
    MANUFACTURER,
    MAX_FAILED_UPDATES,
)
from .pyfimer import FimerError
from .pyfimer.modbus import FimerModbusInverter, SunSpecError, SunSpecMapShiftError

if TYPE_CHECKING:
    from . import FimerConfigEntry

_LOGGER = logging.getLogger(__name__)

type FimerData = dict[str, Any]
"""Readings keyed by pyfimer point name."""


class FimerCoordinator(DataUpdateCoordinator[FimerData]):
    """Poll one inverter over its Modbus unit."""

    config_entry: FimerConfigEntry

    def __init__(
        self, hass: HomeAssistant, entry: FimerConfigEntry, inverter: FimerModbusInverter
    ) -> None:
        """Set up polling at the configured interval."""
        self._default_interval = timedelta(
            seconds=entry.options.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL)
        )
        super().__init__(
            hass,
            _LOGGER,
            config_entry=entry,
            name=f"{DOMAIN}_{entry.data[CONF_HOST]}",
            update_interval=self._default_interval,
        )
        self.inverter = inverter
        self._failed_update_count = 0

    @property
    def device_unique_id(self) -> str:
        """The identifier the inverter's device and entities are keyed by."""
        return self.config_entry.unique_id or self.config_entry.entry_id

    @property
    def device_info(self) -> DeviceInfo:
        """Describe the inverter from its common model."""
        identity = self.inverter.identity
        return DeviceInfo(
            identifiers={(DOMAIN, self.device_unique_id)},
            name=self.config_entry.title,
            manufacturer=identity.manufacturer or MANUFACTURER,
            model=identity.model or None,
            sw_version=identity.firmware_version or None,
            serial_number=identity.serial_number or None,
        )

    async def _async_update_data(self) -> FimerData:
        """Refresh every discovered model and return the readings."""
        try:
            await self._refresh()
        except (ModbusError, SunSpecError, FimerError) as err:
            self._failed_update_count += 1
            if self._failed_update_count == MAX_FAILED_UPDATES:
                # an inverter without grid power at night answers nothing:
                # poll gently until it comes back
                self.update_interval = timedelta(seconds=ERROR_SCAN_INTERVAL)
            raise UpdateFailed(
                translation_domain=DOMAIN,
                translation_key="update_failed",
                translation_placeholders={"error": str(err)},
            ) from err

        if self._failed_update_count:
            self._failed_update_count = 0
            self.update_interval = self._default_interval
        return self.inverter.values()

    async def _refresh(self) -> None:
        """Discover on first use, then refresh; re-discover once on a map shift."""
        if not self.inverter.discovered:
            await self.inverter.discover()
        try:
            await self.inverter.async_update()
        except SunSpecMapShiftError:
            # a firmware update or a changed datalogger setting moved the models
            await self.inverter.discover()
            await self.inverter.async_update()
