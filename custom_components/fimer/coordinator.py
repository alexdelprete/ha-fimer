"""Polling coordinator for the FIMER (ABB / Power-One) integration."""

from __future__ import annotations

from datetime import timedelta
import logging
from typing import TYPE_CHECKING, Any

from modbus_connection import ModbusError

from homeassistant.const import CONF_HOST, CONF_SCAN_INTERVAL
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import ConfigEntryAuthFailed, HomeAssistantError
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.dispatcher import async_dispatcher_send
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .const import (
    DEFAULT_SCAN_INTERVAL,
    DOMAIN,
    ERROR_SCAN_INTERVAL,
    MANUFACTURER,
    MAX_FAILED_UPDATES,
    SETTINGS_SCAN_INTERVAL,
)
from .pyfimer import FimerAuthenticationError, FimerError
from .pyfimer.modbus import Controls, FimerModbusInverter, SunSpecError, SunSpecMapShiftError
from .pyfimer.rest import FimerRestLogger

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


class FimerSettingsCoordinator(DataUpdateCoordinator[FimerData]):
    """Poll the immediate controls model and write the power limit.

    Only created when the experimental power control option is on and the
    inverter serves model 123. It reads the live component off the inverter
    on every use, so a re-discovery by the readings coordinator after a map
    shift is picked up without any bookkeeping here.
    """

    config_entry: FimerConfigEntry

    def __init__(
        self,
        hass: HomeAssistant,
        entry: FimerConfigEntry,
        inverter: FimerModbusInverter,
        readings: FimerCoordinator,
    ) -> None:
        """Set up polling of the controls model."""
        super().__init__(
            hass,
            _LOGGER,
            config_entry=entry,
            name=f"{DOMAIN}_{entry.data[CONF_HOST]}_settings",
            update_interval=timedelta(seconds=SETTINGS_SCAN_INTERVAL),
        )
        self.inverter = inverter
        self.readings = readings

    @property
    def device_unique_id(self) -> str:
        """The identifier the inverter's device and entities are keyed by."""
        return self.readings.device_unique_id

    @property
    def device_info(self) -> DeviceInfo:
        """Describe the inverter, the same device the readings belong to."""
        return self.readings.device_info

    def _controls(self) -> Controls:
        if (controls := self.inverter.controls) is None:
            raise FimerError("The inverter does not serve the immediate controls model")
        return controls

    async def _async_update_data(self) -> FimerData:
        """Refresh the controls model and return its readings."""
        try:
            controls = self._controls()
            await controls.async_update()
        except (ModbusError, SunSpecError, FimerError) as err:
            raise UpdateFailed(
                translation_domain=DOMAIN,
                translation_key="update_failed",
                translation_placeholders={"error": str(err)},
            ) from err
        return controls.values()

    async def async_apply_power_limit(
        self, *, percent: float | None = None, enabled: bool | None = None
    ) -> None:
        """Write the power limit and/or its enable flag, then refresh the entities."""
        try:
            await self._controls().apply_power_limit(percent=percent, enabled=enabled)
        except (ModbusError, SunSpecError, FimerError, ValueError) as err:
            raise HomeAssistantError(
                translation_domain=DOMAIN,
                translation_key="write_failed",
                translation_placeholders={"error": str(err)},
            ) from err
        await self.async_refresh()


type FimerRestData = dict[str, dict[str, Any]]
"""Readings keyed by REST device ID, then by pyfimer point name."""


class FimerRestCoordinator(DataUpdateCoordinator[FimerRestData]):
    """Poll a VSN datalogger over its REST API."""

    config_entry: FimerConfigEntry

    def __init__(
        self, hass: HomeAssistant, entry: FimerConfigEntry, logger: FimerRestLogger
    ) -> None:
        """Set up polling at the configured interval."""
        self._default_interval = timedelta(
            seconds=entry.options.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL)
        )
        super().__init__(
            hass,
            _LOGGER,
            config_entry=entry,
            name=f"{DOMAIN}_{entry.data[CONF_HOST]}_rest",
            update_interval=self._default_interval,
        )
        self.rest_logger = logger
        self._failed_update_count = 0
        self.known_device_ids: set[str] = set()
        """REST device IDs that already have a Home Assistant device; set after setup."""

    async def _async_update_data(self) -> FimerRestData:
        """Discover on first use, then refresh every device's readings.

        A device the card reports for the first time after setup, such as a
        battery or meter added later, gets its Home Assistant device and
        entities right away.
        """
        try:
            if not self.rest_logger.discovered:
                await self.rest_logger.discover()
            else:
                await self.rest_logger.async_update()
        except FimerAuthenticationError as err:
            raise ConfigEntryAuthFailed(
                translation_domain=DOMAIN,
                translation_key="invalid_auth",
                translation_placeholders={"error": str(err)},
            ) from err
        except FimerError as err:
            self._failed_update_count += 1
            if self._failed_update_count == MAX_FAILED_UPDATES:
                self.update_interval = timedelta(seconds=ERROR_SCAN_INTERVAL)
            raise UpdateFailed(
                translation_domain=DOMAIN,
                translation_key="update_failed",
                translation_placeholders={"error": str(err)},
            ) from err

        if self._failed_update_count:
            self._failed_update_count = 0
            self.update_interval = self._default_interval
        values = self.rest_logger.values()
        if self.known_device_ids and (new_ids := set(values) - self.known_device_ids):
            self.known_device_ids |= new_ids
            self._async_add_devices(new_ids)
        return values

    @callback
    def _async_add_devices(self, device_ids: set[str]) -> None:
        """Create devices for newly reported REST device IDs and announce them."""
        from .devices import SIGNAL_NEW_DEVICES, build_rest_devices  # noqa: PLC0415 - cycle

        runtime = self.config_entry.runtime_data
        new_devices = build_rest_devices(self, device_ids)
        if not new_devices:
            return
        registry = dr.async_get(self.hass)
        datalogger = next(
            (device for device in runtime.devices if device.device_type == "datalogger"), None
        )
        if datalogger is not None:
            logger_entry = registry.async_get_device(
                identifiers=datalogger.device_info["identifiers"]
            )
            if logger_entry is not None:
                for device in new_devices:
                    device.device_info["via_device_id"] = logger_entry.id
        runtime.devices.extend(new_devices)
        _LOGGER.info(
            "New devices reported by the datalogger: %s",
            ", ".join(device.unique_id for device in new_devices),
        )
        async_dispatcher_send(
            self.hass, f"{SIGNAL_NEW_DEVICES}_{self.config_entry.entry_id}", new_devices
        )
