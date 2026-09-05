"""Config flow for the FIMER (ABB / Power-One) integration."""

from __future__ import annotations

from collections.abc import Mapping
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
from homeassistant.const import CONF_HOST, CONF_PORT, CONF_SCAN_INTERVAL
from homeassistant.core import callback
from homeassistant.data_entry_flow import section
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.selector import (
    BooleanSelector,
    NumberSelector,
    NumberSelectorConfig,
    NumberSelectorMode,
)

from .const import (
    CONF_ADVANCED,
    CONF_BASE_ADDRESS,
    CONF_POWER_CONTROL,
    CONF_UNIT_ID,
    DEFAULT_BASE_ADDRESS,
    DEFAULT_PORT,
    DEFAULT_POWER_CONTROL,
    DEFAULT_SCAN_INTERVAL,
    DEFAULT_UNIT_ID,
    DOMAIN,
    MAX_BASE_ADDRESS,
    MAX_SCAN_INTERVAL,
    MAX_UNIT_ID,
    MIN_SCAN_INTERVAL,
    MIN_UNIT_ID,
)
from .pyfimer import FimerError
from .pyfimer.modbus import DeviceIdentity, FimerModbusInverter, SunSpecError

_LOGGER = logging.getLogger(__name__)

STEP_USER_DATA_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_HOST): str,
        vol.Required(CONF_PORT, default=DEFAULT_PORT): cv.port,
        vol.Required(CONF_ADVANCED): section(
            vol.Schema(
                {
                    vol.Required(CONF_UNIT_ID, default=DEFAULT_UNIT_ID): vol.All(
                        vol.Coerce(int), vol.Range(min=MIN_UNIT_ID, max=MAX_UNIT_ID)
                    ),
                    vol.Required(CONF_BASE_ADDRESS, default=DEFAULT_BASE_ADDRESS): vol.All(
                        vol.Coerce(int), vol.Range(min=0, max=MAX_BASE_ADDRESS)
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


def _flatten(user_input: Mapping[str, Any]) -> dict[str, Any]:
    """Merge the advanced section into one flat mapping of connection settings."""
    return {
        CONF_HOST: user_input[CONF_HOST],
        CONF_PORT: user_input[CONF_PORT],
        **user_input[CONF_ADVANCED],
    }


def _nest(data: Mapping[str, Any]) -> dict[str, Any]:
    """Shape stored connection settings as suggested values for the form."""
    return {
        CONF_HOST: data[CONF_HOST],
        CONF_PORT: data[CONF_PORT],
        CONF_ADVANCED: {
            CONF_UNIT_ID: data[CONF_UNIT_ID],
            CONF_BASE_ADDRESS: data[CONF_BASE_ADDRESS],
        },
    }


class FimerConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle the config flow: connect, discover the SunSpec chain, identify."""

    VERSION = 1

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> FimerOptionsFlow:
        """Return the options flow."""
        return FimerOptionsFlow()

    async def _async_validate(
        self, data: Mapping[str, Any], errors: dict[str, str]
    ) -> DeviceIdentity | None:
        """Discover the inverter with the given settings, filling ``errors`` on failure."""
        params = ModbusTcpParams(host=data[CONF_HOST], port=data[CONF_PORT])
        try:
            async with async_get_temporary_unit(self.hass, params, data[CONF_UNIT_ID]) as unit:
                inverter = FimerModbusInverter(unit, base_address=data[CONF_BASE_ADDRESS])
                await inverter.discover()
                return inverter.identity
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
            _LOGGER.exception("Unexpected error validating %s", data[CONF_HOST])
            errors["base"] = "unknown"
        return None

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Handle the initial step."""
        errors: dict[str, str] = {}
        if user_input is not None:
            data = _flatten(user_input)
            if (identity := await self._async_validate(data, errors)) is not None:
                await self.async_set_unique_id(identity.serial_number or None)
                self._abort_if_unique_id_configured()
                return self.async_create_entry(title=identity.model or data[CONF_HOST], data=data)

        return self.async_show_form(
            step_id="user",
            data_schema=self.add_suggested_values_to_schema(STEP_USER_DATA_SCHEMA, user_input),
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
            if (identity := await self._async_validate(data, errors)) is not None:
                await self.async_set_unique_id(identity.serial_number or None)
                self._abort_if_unique_id_mismatch()
                return self.async_update_reload_and_abort(entry, data_updates=data)

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
