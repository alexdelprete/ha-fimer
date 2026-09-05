"""Config flow for the FIMER (ABB / Power-One) integration."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
import logging
from typing import Any

from modbus_connection import ModbusError, ModbusTcpParams
import voluptuous as vol

from homeassistant.components.modbus import async_get_temporary_unit
from homeassistant.config_entries import (
    ConfigEntry,
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlowWithReload,
)
from homeassistant.const import (
    CONF_HOST,
    CONF_PASSWORD,
    CONF_PORT,
    CONF_SCAN_INTERVAL,
    CONF_USERNAME,
)
from homeassistant.core import callback
from homeassistant.data_entry_flow import section
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.selector import (
    BooleanSelector,
    NumberSelector,
    NumberSelectorConfig,
    NumberSelectorMode,
    SelectOptionDict,
    SelectSelector,
    SelectSelectorConfig,
    TextSelector,
    TextSelectorConfig,
    TextSelectorType,
)

from .const import (
    CONF_BASE_ADDRESS,
    CONF_MIGRATE_FROM,
    CONF_MODBUS_SECTION,
    CONF_POWER_CONTROL,
    CONF_REST_MODEL,
    CONF_REST_REQUIRES_AUTH,
    CONF_REST_SECTION,
    CONF_UNIT_ID,
    CONF_USE_MODBUS,
    CONF_USE_REST,
    DEFAULT_BASE_ADDRESS,
    DEFAULT_PORT,
    DEFAULT_POWER_CONTROL,
    DEFAULT_REST_USERNAME,
    DEFAULT_SCAN_INTERVAL,
    DEFAULT_UNIT_ID,
    DOMAIN,
    LEGACY_REST_DOMAIN,
    MAX_BASE_ADDRESS,
    MAX_SCAN_INTERVAL,
    MAX_UNIT_ID,
    MIN_SCAN_INTERVAL,
    MIN_UNIT_ID,
)
from .pyfimer import (
    FimerAuthenticationError,
    FimerConnectionError,
    FimerDetectionError,
    FimerError,
    FimerUnsupportedDeviceError,
    FimerUnsupportedFirmwareError,
)
from .pyfimer.modbus import FimerModbusInverter, SunSpecError
from .pyfimer.rest import FimerRestLogger

_LOGGER = logging.getLogger(__name__)

CONF_LEGACY_ENTRY = "legacy_entry"

STEP_USER_DATA_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_HOST): str,
        vol.Required(CONF_PORT, default=DEFAULT_PORT): cv.port,
        vol.Required(CONF_MODBUS_SECTION): section(
            vol.Schema(
                {
                    vol.Required(CONF_USE_MODBUS, default=True): BooleanSelector(),
                    vol.Required(CONF_UNIT_ID, default=DEFAULT_UNIT_ID): vol.All(
                        vol.Coerce(int), vol.Range(min=MIN_UNIT_ID, max=MAX_UNIT_ID)
                    ),
                    vol.Required(CONF_BASE_ADDRESS, default=DEFAULT_BASE_ADDRESS): vol.All(
                        vol.Coerce(int), vol.Range(min=0, max=MAX_BASE_ADDRESS)
                    ),
                }
            ),
            {"collapsed": False},
        ),
        vol.Required(CONF_REST_SECTION): section(
            vol.Schema(
                {
                    vol.Required(CONF_USE_REST, default=False): BooleanSelector(),
                    vol.Optional(CONF_USERNAME, default=DEFAULT_REST_USERNAME): str,
                    vol.Optional(CONF_PASSWORD, default=""): TextSelector(
                        TextSelectorConfig(type=TextSelectorType.PASSWORD)
                    ),
                }
            ),
            {"collapsed": True},
        ),
    }
)

OPTIONS_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_SCAN_INTERVAL, default=DEFAULT_SCAN_INTERVAL): vol.All(
            NumberSelector(
                NumberSelectorConfig(
                    min=MIN_SCAN_INTERVAL,
                    max=MAX_SCAN_INTERVAL,
                    step=1,
                    mode=NumberSelectorMode.BOX,
                    unit_of_measurement="s",
                )
            ),
            vol.Coerce(int),
        ),
        vol.Required(CONF_POWER_CONTROL, default=DEFAULT_POWER_CONTROL): BooleanSelector(),
    }
)


@dataclass
class Validated:
    """What validating the connection settings found out."""

    unique_id: str | None
    title: str
    rest_model: str | None = None
    rest_requires_auth: bool = True


def _flatten(user_input: Mapping[str, Any]) -> dict[str, Any]:
    """Merge the sections into one flat mapping of connection settings."""
    modbus = user_input[CONF_MODBUS_SECTION]
    rest = user_input[CONF_REST_SECTION]
    return {
        CONF_HOST: user_input[CONF_HOST].strip(),
        CONF_PORT: user_input[CONF_PORT],
        CONF_USE_MODBUS: modbus[CONF_USE_MODBUS],
        CONF_UNIT_ID: modbus[CONF_UNIT_ID],
        CONF_BASE_ADDRESS: modbus[CONF_BASE_ADDRESS],
        CONF_USE_REST: rest[CONF_USE_REST],
        CONF_USERNAME: rest.get(CONF_USERNAME) or DEFAULT_REST_USERNAME,
        CONF_PASSWORD: rest.get(CONF_PASSWORD, ""),
    }


def _nest(data: Mapping[str, Any]) -> dict[str, Any]:
    """Shape stored connection settings as suggested values for the form."""
    return {
        CONF_HOST: data.get(CONF_HOST, ""),
        CONF_PORT: data.get(CONF_PORT, DEFAULT_PORT),
        CONF_MODBUS_SECTION: {
            CONF_USE_MODBUS: data.get(CONF_USE_MODBUS, True),
            CONF_UNIT_ID: data.get(CONF_UNIT_ID, DEFAULT_UNIT_ID),
            CONF_BASE_ADDRESS: data.get(CONF_BASE_ADDRESS, DEFAULT_BASE_ADDRESS),
        },
        CONF_REST_SECTION: {
            CONF_USE_REST: data.get(CONF_USE_REST, False),
            CONF_USERNAME: data.get(CONF_USERNAME, DEFAULT_REST_USERNAME),
            CONF_PASSWORD: data.get(CONF_PASSWORD, ""),
        },
    }


class FimerConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle the config flow: connect over the chosen sources and identify."""

    VERSION = 1

    def __init__(self) -> None:
        """Start without a legacy entry to migrate."""
        self._legacy_entry_id: str | None = None

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> FimerOptionsFlow:
        """Return the options flow."""
        return FimerOptionsFlow()

    async def _async_validate(
        self, data: Mapping[str, Any], errors: dict[str, str]
    ) -> Validated | None:
        """Discover the device over each enabled source, filling ``errors`` on failure."""
        if not data[CONF_USE_MODBUS] and not data[CONF_USE_REST]:
            errors["base"] = "no_source"
            return None
        validated = Validated(unique_id=None, title=data[CONF_HOST])
        if data[CONF_USE_MODBUS] and not await self._async_validate_modbus(data, errors, validated):
            return None
        if data[CONF_USE_REST] and not await self._async_validate_rest(data, errors, validated):
            return None
        return validated

    async def _async_validate_modbus(
        self, data: Mapping[str, Any], errors: dict[str, str], validated: Validated
    ) -> bool:
        params = ModbusTcpParams(host=data[CONF_HOST], port=data[CONF_PORT])
        try:
            async with async_get_temporary_unit(self.hass, params, data[CONF_UNIT_ID]) as unit:
                inverter = FimerModbusInverter(unit, base_address=data[CONF_BASE_ADDRESS])
                await inverter.discover()
                identity = inverter.identity
        except HomeAssistantError:
            # another integration holds this device with different link settings
            errors["base"] = "link_conflict"
        except ModbusError:
            errors["base"] = "cannot_connect"
        except SunSpecError:
            errors["base"] = "no_sunspec"
        except FimerError:
            errors["base"] = "unsupported_device"
        except Exception:
            _LOGGER.exception("Unexpected error validating Modbus on %s", data[CONF_HOST])
            errors["base"] = "unknown"
        else:
            validated.unique_id = identity.serial_number or None
            validated.title = identity.model or validated.title
            return True
        return False

    async def _async_validate_rest(
        self, data: Mapping[str, Any], errors: dict[str, str], validated: Validated
    ) -> bool:
        logger = FimerRestLogger(
            async_get_clientsession(self.hass),
            data[CONF_HOST],
            username=data[CONF_USERNAME],
            password=data[CONF_PASSWORD],
        )
        try:
            await logger.discover()
        except FimerAuthenticationError:
            errors["base"] = "invalid_auth"
        except FimerUnsupportedFirmwareError:
            errors["base"] = "unsupported_firmware"
        except FimerUnsupportedDeviceError, FimerDetectionError:
            errors["base"] = "no_rest_api"
        except FimerConnectionError:
            errors["base"] = "cannot_connect"
        except Exception:
            _LOGGER.exception("Unexpected error validating REST on %s", data[CONF_HOST])
            errors["base"] = "unknown"
        else:
            identity = logger.identity
            validated.rest_model = str(identity.model)
            validated.rest_requires_auth = logger.requires_auth
            inverter = next(
                (
                    (device_id, readings)
                    for device_id, readings in logger.devices.items()
                    if readings.device_type.startswith("inverter")
                ),
                None,
            )
            if validated.unique_id is None:
                validated.unique_id = inverter[0] if inverter else identity.unique_id
                if inverter and inverter[1].model:
                    validated.title = inverter[1].model
                elif not inverter:
                    validated.title = str(identity.model)
            return True
        return False

    def _entry_data(self, data: dict[str, Any], validated: Validated) -> dict[str, Any]:
        entry_data = dict(data)
        if data[CONF_USE_REST]:
            entry_data[CONF_REST_MODEL] = validated.rest_model
            entry_data[CONF_REST_REQUIRES_AUTH] = validated.rest_requires_auth
        if self._legacy_entry_id:
            entry_data[CONF_MIGRATE_FROM] = self._legacy_entry_id
        return entry_data

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Offer to take over a legacy REST entry, or go straight to the form."""
        if self._legacy_entries():
            return self.async_show_menu(step_id="user", menu_options=["manual", "legacy"])
        return await self.async_step_manual()

    def _legacy_entries(self) -> list[ConfigEntry]:
        return [
            entry
            for entry in self.hass.config_entries.async_entries(LEGACY_REST_DOMAIN)
            if entry.data.get(CONF_HOST)
        ]

    async def async_step_legacy(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Pick the legacy REST entry whose settings and entities to take over."""
        entries = {entry.entry_id: entry for entry in self._legacy_entries()}
        if user_input is not None:
            legacy = entries[user_input[CONF_LEGACY_ENTRY]]
            self._legacy_entry_id = legacy.entry_id
            suggested = _nest(
                {
                    CONF_HOST: legacy.data.get(CONF_HOST, ""),
                    CONF_USE_REST: True,
                    CONF_USERNAME: legacy.data.get(CONF_USERNAME, DEFAULT_REST_USERNAME),
                    CONF_PASSWORD: legacy.data.get(CONF_PASSWORD, ""),
                }
            )
            return await self.async_step_manual(suggested_values=suggested)
        return self.async_show_form(
            step_id="legacy",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_LEGACY_ENTRY): SelectSelector(
                        SelectSelectorConfig(
                            options=[
                                SelectOptionDict(value=entry_id, label=entry.title)
                                for entry_id, entry in entries.items()
                            ]
                        )
                    )
                }
            ),
        )

    async def async_step_manual(
        self,
        user_input: dict[str, Any] | None = None,
        suggested_values: dict[str, Any] | None = None,
    ) -> ConfigFlowResult:
        """Handle the connection settings form."""
        errors: dict[str, str] = {}
        if user_input is not None:
            data = _flatten(user_input)
            if (validated := await self._async_validate(data, errors)) is not None:
                await self.async_set_unique_id(validated.unique_id)
                self._abort_if_unique_id_configured()
                return self.async_create_entry(
                    title=validated.title, data=self._entry_data(data, validated)
                )

        return self.async_show_form(
            step_id="manual",
            data_schema=self.add_suggested_values_to_schema(
                STEP_USER_DATA_SCHEMA, user_input or suggested_values
            ),
            errors=errors,
        )

    async def async_step_reconfigure(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Change the connection settings of an existing entry."""
        entry = self._get_reconfigure_entry()
        errors: dict[str, str] = {}
        if user_input is not None:
            data = _flatten(user_input)
            if (validated := await self._async_validate(data, errors)) is not None:
                await self.async_set_unique_id(validated.unique_id)
                self._abort_if_unique_id_mismatch()
                return self.async_update_reload_and_abort(
                    entry, data_updates=self._entry_data(data, validated)
                )

        return self.async_show_form(
            step_id="reconfigure",
            data_schema=self.add_suggested_values_to_schema(
                STEP_USER_DATA_SCHEMA, user_input or _nest(entry.data)
            ),
            errors=errors,
        )


class FimerOptionsFlow(OptionsFlowWithReload):
    """Tune the polling interval and the experimental power control; the entry reloads on save."""

    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Show and store the options."""
        if user_input is not None:
            return self.async_create_entry(data=user_input)
        return self.async_show_form(
            step_id="init",
            data_schema=self.add_suggested_values_to_schema(
                OPTIONS_SCHEMA, self.config_entry.options
            ),
        )
