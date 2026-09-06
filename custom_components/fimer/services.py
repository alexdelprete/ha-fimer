"""Actions of the FIMER (ABB / Power-One) integration.

Registered once at integration setup, they address a config entry and reach
the library directly: raw register reads and writes, writing a SunSpec
point by name, setting the power limit, and reading every point a device
currently reports.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any, Final

from modbus_connection import ModbusError, WordOrder
from modbus_connection.decode import (
    decode_float32,
    decode_int16,
    decode_int32,
    decode_string,
    decode_uint16,
    decode_uint32,
)
from modbus_connection.encode import (
    encode_float32,
    encode_int16,
    encode_int32,
    encode_string,
    encode_uint16,
    encode_uint32,
)
import voluptuous as vol

from homeassistant.core import (
    HomeAssistant,
    ServiceCall,
    ServiceResponse,
    SupportsResponse,
    callback,
)
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
from homeassistant.helpers import config_validation as cv

from .const import DOMAIN
from .pyfimer import FimerError
from .pyfimer.modbus import SunSpecError

if TYPE_CHECKING:
    from . import FimerConfigEntry, FimerRuntimeData

ATTR_CONFIG_ENTRY: Final = "config_entry"
ATTR_ADDRESS: Final = "address"
ATTR_COUNT: Final = "count"
ATTR_REGISTER_TYPE: Final = "register_type"
ATTR_DATA_TYPE: Final = "data_type"
ATTR_WORD_ORDER: Final = "word_order"
ATTR_VALUE: Final = "value"
ATTR_VALUES: Final = "values"
ATTR_POINT: Final = "point"
ATTR_PERCENT: Final = "percent"
ATTR_ENABLED: Final = "enabled"
ATTR_DEVICE: Final = "device"

_LOGGER = logging.getLogger(__name__)

SERVICE_READ_REGISTERS: Final = "read_registers"
SERVICE_WRITE_REGISTERS: Final = "write_registers"
SERVICE_WRITE_POINT: Final = "write_point"
SERVICE_SET_POWER_LIMIT: Final = "set_power_limit"
SERVICE_GET_READINGS: Final = "get_readings"
SERVICE_REDISCOVER: Final = "rediscover"

REGISTER_TYPES: Final = ["holding", "input"]
DATA_TYPES: Final = ["raw", "uint16", "int16", "uint32", "int32", "float32", "string"]
WORD_ORDERS: Final = ["big", "little"]
_WORDS_PER_TYPE: Final = {"uint16": 1, "int16": 1, "uint32": 2, "int32": 2, "float32": 2}

_ENTRY = {vol.Required(ATTR_CONFIG_ENTRY): cv.string}

READ_REGISTERS_SCHEMA = vol.Schema(
    {
        **_ENTRY,
        vol.Required(ATTR_ADDRESS): vol.All(vol.Coerce(int), vol.Range(min=0, max=0xFFFF)),
        vol.Optional(ATTR_COUNT, default=1): vol.All(vol.Coerce(int), vol.Range(min=1, max=125)),
        vol.Optional(ATTR_REGISTER_TYPE, default="holding"): vol.In(REGISTER_TYPES),
        vol.Optional(ATTR_DATA_TYPE, default="raw"): vol.In(DATA_TYPES),
        vol.Optional(ATTR_WORD_ORDER, default="big"): vol.In(WORD_ORDERS),
    }
)
WRITE_REGISTERS_SCHEMA = vol.Schema(
    {
        **_ENTRY,
        vol.Required(ATTR_ADDRESS): vol.All(vol.Coerce(int), vol.Range(min=0, max=0xFFFF)),
        vol.Exclusive(ATTR_VALUE, "value"): vol.Any(vol.Coerce(float), cv.string),
        vol.Exclusive(ATTR_VALUES, "value"): vol.All(
            cv.ensure_list, [vol.All(vol.Coerce(int), vol.Range(min=0, max=0xFFFF))]
        ),
        vol.Optional(ATTR_DATA_TYPE, default="uint16"): vol.In(DATA_TYPES),
        vol.Optional(ATTR_WORD_ORDER, default="big"): vol.In(WORD_ORDERS),
        vol.Optional(ATTR_COUNT): vol.All(vol.Coerce(int), vol.Range(min=1, max=123)),
    }
)
WRITE_POINT_SCHEMA = vol.Schema(
    {
        **_ENTRY,
        vol.Required(ATTR_POINT): cv.string,
        vol.Required(ATTR_VALUE): vol.Any(vol.Coerce(float), cv.string),
    }
)
SET_POWER_LIMIT_SCHEMA = vol.Schema(
    {
        **_ENTRY,
        vol.Optional(ATTR_PERCENT): vol.All(vol.Coerce(float), vol.Range(min=0, max=100)),
        vol.Optional(ATTR_ENABLED): cv.boolean,
    }
)
GET_READINGS_SCHEMA = vol.Schema({**_ENTRY, vol.Optional(ATTR_DEVICE): cv.string})
REDISCOVER_SCHEMA = vol.Schema(_ENTRY)


@callback
def async_setup_services(hass: HomeAssistant) -> None:
    """Register the integration's actions."""
    hass.services.async_register(
        DOMAIN,
        SERVICE_READ_REGISTERS,
        _async_read_registers,
        schema=READ_REGISTERS_SCHEMA,
        supports_response=SupportsResponse.ONLY,
    )
    hass.services.async_register(
        DOMAIN, SERVICE_WRITE_REGISTERS, _async_write_registers, schema=WRITE_REGISTERS_SCHEMA
    )
    hass.services.async_register(
        DOMAIN, SERVICE_WRITE_POINT, _async_write_point, schema=WRITE_POINT_SCHEMA
    )
    hass.services.async_register(
        DOMAIN, SERVICE_SET_POWER_LIMIT, _async_set_power_limit, schema=SET_POWER_LIMIT_SCHEMA
    )
    hass.services.async_register(
        DOMAIN,
        SERVICE_GET_READINGS,
        _async_get_readings,
        schema=GET_READINGS_SCHEMA,
        supports_response=SupportsResponse.ONLY,
    )
    hass.services.async_register(
        DOMAIN,
        SERVICE_REDISCOVER,
        _async_rediscover,
        schema=REDISCOVER_SCHEMA,
        supports_response=SupportsResponse.OPTIONAL,
    )


def _runtime(call: ServiceCall) -> FimerRuntimeData:
    """Return the runtime data of the entry a call addresses."""
    entry_id = call.data[ATTR_CONFIG_ENTRY]
    entry: FimerConfigEntry | None = call.hass.config_entries.async_get_entry(entry_id)
    if entry is None or entry.domain != DOMAIN:
        raise ServiceValidationError(
            translation_domain=DOMAIN,
            translation_key="entry_not_found",
            translation_placeholders={"entry_id": entry_id},
        )
    if not entry.state.recoverable or not hasattr(entry, "runtime_data"):
        raise ServiceValidationError(
            translation_domain=DOMAIN,
            translation_key="entry_not_loaded",
            translation_placeholders={"title": entry.title},
        )
    return entry.runtime_data


def _modbus(call: ServiceCall) -> tuple[FimerRuntimeData, Any]:
    """Return the runtime data and the Modbus inverter, or refuse without Modbus."""
    runtime = _runtime(call)
    if runtime.inverter is None:
        raise ServiceValidationError(
            translation_domain=DOMAIN, translation_key="modbus_not_enabled"
        )
    return runtime, runtime.inverter


def _device_error(err: Exception) -> HomeAssistantError:
    return HomeAssistantError(
        translation_domain=DOMAIN,
        translation_key="write_failed",
        translation_placeholders={"error": str(err)},
    )


async def _async_read_registers(call: ServiceCall) -> ServiceResponse:
    """Read registers at an absolute address and decode them."""
    _LOGGER.debug("Action %s: %s", call.service, dict(call.data))
    _, inverter = _modbus(call)
    address: int = call.data[ATTR_ADDRESS]
    data_type: str = call.data[ATTR_DATA_TYPE]
    count: int = _WORDS_PER_TYPE.get(data_type, call.data[ATTR_COUNT])
    word_order: WordOrder = call.data[ATTR_WORD_ORDER]
    input_registers = call.data[ATTR_REGISTER_TYPE] == "input"
    try:
        if input_registers:
            words = await inverter.registers.read_input(address, count)
        else:
            words = await inverter.registers.read_holding(address, count)
    except (ModbusError, TimeoutError, OSError) as err:
        raise HomeAssistantError(
            translation_domain=DOMAIN,
            translation_key="update_failed",
            translation_placeholders={"error": str(err)},
        ) from err
    value: Any
    match data_type:
        case "uint16":
            value = decode_uint16(words)
        case "int16":
            value = decode_int16(words)
        case "uint32":
            value = decode_uint32(words, word_order=word_order)
        case "int32":
            value = decode_int32(words, word_order=word_order)
        case "float32":
            value = decode_float32(words, word_order=word_order)
        case "string":
            value = decode_string(words).strip("\x00 ")
        case _:
            value = None
    return {
        ATTR_ADDRESS: address,
        ATTR_COUNT: count,
        ATTR_REGISTER_TYPE: call.data[ATTR_REGISTER_TYPE],
        "registers": list(words),
        ATTR_VALUE: value,
    }


async def _async_write_registers(call: ServiceCall) -> None:
    """Write raw registers, or one value encoded as the given type."""
    _LOGGER.debug("Action %s: %s", call.service, dict(call.data))
    _, inverter = _modbus(call)
    address: int = call.data[ATTR_ADDRESS]
    word_order: WordOrder = call.data[ATTR_WORD_ORDER]
    if ATTR_VALUES in call.data:
        words = list(call.data[ATTR_VALUES])
    elif ATTR_VALUE in call.data:
        value = call.data[ATTR_VALUE]
        data_type: str = call.data[ATTR_DATA_TYPE]
        try:
            match data_type:
                case "string":
                    length = call.data.get(ATTR_COUNT) or (len(str(value)) + 1) // 2
                    words = encode_string(str(value), length=length)
                case "float32":
                    words = encode_float32(float(value), word_order=word_order)
                case "uint32":
                    words = encode_uint32(int(value), word_order=word_order)
                case "int32":
                    words = encode_int32(int(value), word_order=word_order)
                case "int16":
                    words = encode_int16(int(value))
                case _:
                    words = encode_uint16(int(value))
        except (OverflowError, ValueError) as err:
            raise ServiceValidationError(
                translation_domain=DOMAIN,
                translation_key="invalid_value",
                translation_placeholders={"error": str(err)},
            ) from err
    else:
        raise ServiceValidationError(translation_domain=DOMAIN, translation_key="value_required")
    try:
        await inverter.registers.write_registers(address, words)
    except (ModbusError, TimeoutError, OSError) as err:
        raise _device_error(err) from err


async def _async_write_point(call: ServiceCall) -> None:
    """Write a writable SunSpec point by name, then refresh the readings."""
    _LOGGER.debug("Action %s: %s", call.service, dict(call.data))
    runtime, inverter = _modbus(call)
    point: str = call.data[ATTR_POINT]
    value = call.data[ATTR_VALUE]
    try:
        await inverter.async_write(point, value)
    except AttributeError as err:
        raise ServiceValidationError(
            translation_domain=DOMAIN,
            translation_key="unknown_point",
            translation_placeholders={"point": point, "error": str(err)},
        ) from err
    except ValueError as err:
        raise ServiceValidationError(
            translation_domain=DOMAIN,
            translation_key="invalid_value",
            translation_placeholders={"error": str(err)},
        ) from err
    except (ModbusError, SunSpecError, FimerError, TimeoutError, OSError) as err:
        raise _device_error(err) from err
    if runtime.coordinator is not None:
        await runtime.coordinator.async_request_refresh()


async def _async_set_power_limit(call: ServiceCall) -> None:
    """Set the active power limit and/or its enable flag, verified by readback."""
    _LOGGER.debug("Action %s: %s", call.service, dict(call.data))
    runtime, inverter = _modbus(call)
    if inverter.controls is None:
        raise ServiceValidationError(translation_domain=DOMAIN, translation_key="no_controls")
    try:
        await inverter.controls.apply_power_limit(
            percent=call.data.get(ATTR_PERCENT), enabled=call.data.get(ATTR_ENABLED)
        )
    except ValueError as err:
        raise ServiceValidationError(
            translation_domain=DOMAIN,
            translation_key="invalid_value",
            translation_placeholders={"error": str(err)},
        ) from err
    except (ModbusError, SunSpecError, FimerError, TimeoutError, OSError) as err:
        raise _device_error(err) from err
    if runtime.settings_coordinator is not None:
        await runtime.settings_coordinator.async_refresh()
    if runtime.coordinator is not None:
        await runtime.coordinator.async_request_refresh()


async def _async_get_readings(call: ServiceCall) -> ServiceResponse:
    """Return every point each device currently reports, keyed by device."""
    _LOGGER.debug("Action %s: %s", call.service, dict(call.data))
    runtime = _runtime(call)
    wanted: str | None = call.data.get(ATTR_DEVICE)
    readings: dict[str, Any] = {}
    for device in runtime.devices:
        if wanted is not None and device.unique_id != wanted:
            continue
        readings[device.unique_id] = {
            "type": device.device_type,
            "available": device.available,
            "values": {key: _jsonable(device.value(key)) for key in sorted(device.keys())},
        }
    if wanted is not None and not readings:
        raise ServiceValidationError(
            translation_domain=DOMAIN,
            translation_key="device_not_found",
            translation_placeholders={"device": wanted},
        )
    return {"devices": readings}


async def _async_rediscover(call: ServiceCall) -> ServiceResponse:
    _LOGGER.debug("Action %s: %s", call.service, dict(call.data))
    """Walk the SunSpec chain and the datalogger's devices again, in place.

    Both sources are refreshed afterwards; devices the datalogger reports for
    the first time get their entities through that refresh.
    """
    runtime = _runtime(call)
    response: dict[str, Any] = {}
    try:
        if (inverter := runtime.inverter) is not None:
            await inverter.discover()
            response["modbus"] = {
                "model_chain": [model.model_id for model in inverter.model_chain],
                "phases": inverter.phases,
                "model": inverter.identity.model,
            }
        if (rest := runtime.rest_logger) is not None:
            await rest.discover()
            response["rest"] = {
                "model": str(rest.identity.model),
                "devices": sorted(rest.devices),
            }
    except (ModbusError, SunSpecError, FimerError, TimeoutError, OSError) as err:
        raise HomeAssistantError(
            translation_domain=DOMAIN,
            translation_key="update_failed",
            translation_placeholders={"error": str(err)},
        ) from err
    for coordinator in (
        runtime.coordinator,
        runtime.rest_coordinator,
        runtime.settings_coordinator,
    ):
        if coordinator is not None:
            await coordinator.async_refresh()
    response["reloaded"] = False
    return response


def _jsonable(value: Any) -> Any:
    if isinstance(value, bool | int | float | str) or value is None:
        return int(value) if isinstance(value, int) and not isinstance(value, bool) else value
    if isinstance(value, list | tuple):
        return [_jsonable(item) for item in value]
    return str(value)
