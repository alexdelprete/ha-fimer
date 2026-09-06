"""Diagnostics for the FIMER (ABB / Power-One) integration."""

from __future__ import annotations

from dataclasses import asdict
from typing import Any

from modbus_connection import ModbusError

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.const import CONF_HOST
from homeassistant.core import HomeAssistant

from . import FimerConfigEntry
from .pyfimer import FimerError
from .pyfimer.modbus import SunSpecError

TO_REDACT = {
    CONF_HOST,
    "SN",
    "sn",
    "serial_number",
    "unique_id",
    "title",
    "username",
    "password",
    "hostname",
    "logger.sn",
    "mfg.serial_number",
    "logger.hostname",
}


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: FimerConfigEntry
) -> dict[str, Any]:
    """Return the entry, the discovered chain, the readings and the raw registers."""
    runtime = entry.runtime_data
    inverter = runtime.inverter
    coordinator = runtime.coordinator

    diag: dict[str, Any] = {
        "config_entry": entry.as_dict(),
        "devices": [
            {
                "unique_id": device.unique_id,
                "type": device.device_type,
                "keys": sorted(device.keys()),
            }
            for device in runtime.devices
        ],
        "settings": (settings.data if (settings := runtime.settings_coordinator) else None),
    }
    if inverter is not None and coordinator is not None:
        diag["modbus"] = {
            "discovered": inverter.discovered,
            "identity": asdict(inverter.identity) if inverter.discovered else None,
            "phases": inverter.phases,
            "float_models": inverter.float_models,
            "model_chain": [
                {"model_id": model.model_id, "address": model.address, "length": model.length}
                for model in inverter.model_chain
            ],
            "vendor_model_length": inverter.vendor_model_length,
            "data": coordinator.data,
        }
    if (rest := runtime.rest_logger) is not None and runtime.rest_coordinator is not None:
        diag["rest"] = {
            "discovered": rest.discovered,
            "identity": asdict(rest.identity) if rest.discovered else None,
            "devices": {
                device_id: {
                    "type": readings.device_type,
                    "model": readings.model,
                    "unmapped": readings.unmapped,
                }
                for device_id, readings in rest.devices.items()
            },
            "status": rest.status,
            "data": runtime.rest_coordinator.data,
        }

    if inverter is not None and inverter.discovered:
        try:
            raw = await inverter.async_read_raw()
        except (ModbusError, SunSpecError, FimerError, TimeoutError, OSError) as err:
            diag["modbus"]["registers"] = {"error": str(err)}
        else:
            diag["modbus"]["registers"] = {
                space: {str(address): value for address, value in sorted(registers.items())}
                for space, registers in raw.items()
            }

    return async_redact_data(diag, TO_REDACT)
