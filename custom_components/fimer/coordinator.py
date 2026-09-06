"""Polling coordinator for the FIMER (ABB / Power-One) integration.

Every failure is reported on one line with its cause; the exception chain is
kept for diagnostics, and :func:`helpers.install_log_filters` keeps Home
Assistant from dumping it into the log at DEBUG.
"""

from __future__ import annotations

from datetime import datetime, timedelta
import logging
from typing import TYPE_CHECKING, Any

from modbus_connection import ModbusError

from homeassistant.const import CONF_HOST, CONF_SCAN_INTERVAL
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import ConfigEntryAuthFailed, ConfigEntryError, HomeAssistantError
from homeassistant.helpers import device_registry as dr, issue_registry as ir
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.dispatcher import async_dispatcher_send
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util

from .const import (
    CONF_KNOWN_DEVICES,
    DATALOGGER_SILENT_THRESHOLD,
    DEFAULT_SCAN_INTERVAL,
    DOMAIN,
    ERROR_SCAN_INTERVAL,
    MANUFACTURER,
    MAX_FAILED_UPDATES,
    SETTINGS_SCAN_INTERVAL,
)
from .issues import (
    ISSUE_DATALOGGER_SILENT,
    ISSUE_PARTIAL_DISCOVERY,
    ISSUE_UNSUPPORTED_FIRMWARE,
    SOURCE_MODBUS,
    SOURCE_REST,
    OutageMonitor,
    async_create_entry_issue,
    async_delete_entry_issue,
    format_device_list,
)
from .pyfimer import FimerAuthenticationError, FimerError, FimerUnsupportedFirmwareError
from .pyfimer.modbus import Controls, FimerModbusInverter, SunSpecError, SunSpecMapShiftError
from .pyfimer.rest import DEVICE_TYPE_DATALOGGER as REST_DATALOGGER, FimerRestLogger

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
        self.outage = OutageMonitor(hass, entry, SOURCE_MODBUS)

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
        except (ModbusError, SunSpecError, FimerError, TimeoutError, OSError) as err:
            await self._async_failed(str(err), err)
        except Exception as err:
            _LOGGER.debug("Unexpected error polling %s", self.config_entry.title, exc_info=True)
            await self._async_failed(f"unexpected {type(err).__name__}: {err}", err)

        if self._failed_update_count:
            _LOGGER.debug(
                "Modbus poll of %s succeeded after %d failures; back to the %s interval",
                self.config_entry.title,
                self._failed_update_count,
                self._default_interval,
            )
            self._failed_update_count = 0
            self.update_interval = self._default_interval
        await self.outage.async_success()
        return self.inverter.values()

    async def _async_failed(self, error: str, cause: BaseException) -> None:
        """Count a failed poll, stretch the interval for a sleeping inverter, raise."""
        self._failed_update_count += 1
        _LOGGER.debug(
            "Modbus poll of %s failed (%d in a row): %s",
            self.config_entry.title,
            self._failed_update_count,
            error,
        )
        if self._failed_update_count == MAX_FAILED_UPDATES:
            # an inverter without grid power at night answers nothing:
            # poll gently until it comes back
            _LOGGER.info(
                "%s has not answered over Modbus %d times in a row; polling every %d s "
                "until it does",
                self.config_entry.title,
                MAX_FAILED_UPDATES,
                ERROR_SCAN_INTERVAL,
            )
            self.update_interval = timedelta(seconds=ERROR_SCAN_INTERVAL)
        await self.outage.async_failure(error)
        raise UpdateFailed(
            translation_domain=DOMAIN,
            translation_key="update_failed",
            translation_placeholders={"error": error},
        ) from cause

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
        except (ModbusError, SunSpecError, FimerError, TimeoutError, OSError) as err:
            raise UpdateFailed(
                translation_domain=DOMAIN,
                translation_key="update_failed",
                translation_placeholders={"error": str(err)},
            ) from err
        except Exception as err:
            _LOGGER.debug("Unexpected error reading the controls", exc_info=True)
            raise UpdateFailed(
                translation_domain=DOMAIN,
                translation_key="update_failed",
                translation_placeholders={"error": f"unexpected {type(err).__name__}: {err}"},
            ) from err
        return controls.values()

    async def async_apply_power_limit(
        self, *, percent: float | None = None, enabled: bool | None = None
    ) -> None:
        """Write the power limit and/or its enable flag, then refresh the entities."""
        try:
            await self._controls().apply_power_limit(percent=percent, enabled=enabled)
        except (ModbusError, SunSpecError, FimerError, ValueError, TimeoutError, OSError) as err:
            raise HomeAssistantError(
                translation_domain=DOMAIN,
                translation_key="write_failed",
                translation_placeholders={"error": str(err)},
            ) from err
        except Exception as err:
            _LOGGER.debug("Unexpected error writing the power limit", exc_info=True)
            raise HomeAssistantError(
                translation_domain=DOMAIN,
                translation_key="write_failed",
                translation_placeholders={"error": f"unexpected {type(err).__name__}: {err}"},
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
        self.outage = OutageMonitor(hass, entry, SOURCE_REST)
        self.known_device_ids: set[str] = set()
        """REST device IDs that already have a Home Assistant device; set after setup."""
        self.datalogger_device_id: str | None = None
        """The datalogger's own REST device ID, once it has reported itself."""
        self._silent_since: datetime | None = None

    async def _async_update_data(self) -> FimerRestData:
        """Discover on first use, then refresh every device's readings.

        A device the card reports for the first time after setup, such as a
        battery or meter added later, gets its Home Assistant device and
        entities right away.
        """
        entry = self.config_entry
        try:
            if not self.rest_logger.discovered:
                await self.rest_logger.discover()
                async_delete_entry_issue(self.hass, entry.entry_id, ISSUE_UNSUPPORTED_FIRMWARE)
            else:
                await self.rest_logger.async_update()
        except FimerAuthenticationError as err:
            raise ConfigEntryAuthFailed(
                translation_domain=DOMAIN,
                translation_key="invalid_auth",
                translation_placeholders={"error": str(err)},
            ) from err
        except FimerUnsupportedFirmwareError as err:
            # the card needs a firmware update; retrying will not help
            async_create_entry_issue(
                self.hass,
                entry,
                ISSUE_UNSUPPORTED_FIRMWARE,
                severity=ir.IssueSeverity.ERROR,
                placeholders={"firmware_version": err.firmware_version or "?"},
            )
            raise ConfigEntryError(
                translation_domain=DOMAIN,
                translation_key="unsupported_firmware",
                translation_placeholders={"firmware_version": err.firmware_version or "?"},
            ) from err
        except (FimerError, TimeoutError, OSError) as err:
            await self._async_failed(str(err), err)
        except Exception as err:
            _LOGGER.debug(
                "Unexpected error polling the datalogger of %s", entry.title, exc_info=True
            )
            await self._async_failed(f"unexpected {type(err).__name__}: {err}", err)

        if self._failed_update_count:
            _LOGGER.debug(
                "REST poll of %s succeeded after %d failures; back to the %s interval",
                self.config_entry.title,
                self._failed_update_count,
                self._default_interval,
            )
            self._failed_update_count = 0
            self.update_interval = self._default_interval
        await self.outage.async_success()
        values = self.rest_logger.values()
        self._async_check_datalogger(values)
        if self.known_device_ids:
            if new_ids := set(values) - self.known_device_ids - {self.datalogger_device_id}:
                self.known_device_ids |= new_ids
                self._async_persist_known_devices()
                self._async_add_devices(new_ids)
            self._async_check_known_devices(values)
        return values

    async def _async_failed(self, error: str, cause: BaseException) -> None:
        """Count a failed poll, stretch the interval for a dark card, raise."""
        self._failed_update_count += 1
        _LOGGER.debug(
            "REST poll of %s failed (%d in a row): %s",
            self.config_entry.title,
            self._failed_update_count,
            error,
        )
        if self._failed_update_count == MAX_FAILED_UPDATES:
            _LOGGER.info(
                "The datalogger of %s has not answered %d times in a row; polling every "
                "%d s until it does",
                self.config_entry.title,
                MAX_FAILED_UPDATES,
                ERROR_SCAN_INTERVAL,
            )
            self.update_interval = timedelta(seconds=ERROR_SCAN_INTERVAL)
        await self.outage.async_failure(error)
        raise UpdateFailed(
            translation_domain=DOMAIN,
            translation_key="update_failed",
            translation_placeholders={"error": error},
        ) from cause

    @callback
    def async_seed_known_devices(self) -> None:
        """After setup, remember the devices seen now and before; report any missing."""
        entry = self.config_entry
        self.datalogger_device_id = next(
            (
                device_id
                for device_id, readings in self.rest_logger.devices.items()
                if readings.device_type == REST_DATALOGGER
            ),
            None,
        )
        stored = set(entry.data.get(CONF_KNOWN_DEVICES, []))
        self.known_device_ids = (stored | set(self.data or {})) - {self.datalogger_device_id}
        if self.known_device_ids != stored:
            self._async_persist_known_devices()
        self._async_check_known_devices(self.data or {})

    @callback
    def _async_persist_known_devices(self) -> None:
        entry = self.config_entry
        self.hass.config_entries.async_update_entry(
            entry, data={**entry.data, CONF_KNOWN_DEVICES: sorted(self.known_device_ids)}
        )

    @callback
    def _async_check_known_devices(self, values: FimerRestData) -> None:
        """Raise the partial discovery issue while a known device is not reported."""
        entry = self.config_entry
        missing = sorted(self.known_device_ids - set(values))
        if not missing:
            async_delete_entry_issue(self.hass, entry.entry_id, ISSUE_PARTIAL_DISCOVERY)
            return
        async_create_entry_issue(
            self.hass,
            entry,
            ISSUE_PARTIAL_DISCOVERY,
            severity=ir.IssueSeverity.WARNING,
            is_fixable=True,
            placeholders={
                "missing_devices": format_device_list(self.hass, entry.entry_id, missing)
            },
            data={"missing": missing},
        )

    @callback
    def _async_check_datalogger(self, values: FimerRestData) -> None:
        """Raise the silent datalogger issue when the card stops reporting on itself."""
        entry = self.config_entry
        reported = any(
            readings.device_type == REST_DATALOGGER
            for readings in self.rest_logger.devices.values()
        )
        if reported:
            self._silent_since = None
            async_delete_entry_issue(self.hass, entry.entry_id, ISSUE_DATALOGGER_SILENT)
            return
        now = dt_util.utcnow()
        if self._silent_since is None:
            self._silent_since = now
            return
        if (now - self._silent_since).total_seconds() < DATALOGGER_SILENT_THRESHOLD:
            return
        async_create_entry_issue(
            self.hass,
            entry,
            ISSUE_DATALOGGER_SILENT,
            severity=ir.IssueSeverity.WARNING,
            placeholders={"minutes": str(DATALOGGER_SILENT_THRESHOLD // 60)},
        )

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
            logger_entry = registry.async_get_device_by_identifier(
                next(iter(datalogger.device_info["identifiers"])), self.config_entry.entry_id
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
