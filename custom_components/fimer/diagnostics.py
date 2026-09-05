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

TO_REDACT = {CONF_HOST, "SN", "serial_number", "unique_id", "title"}


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: FimerConfigEntry
) -> dict[str, Any]:
    """Return the entry, the discovered chain, the readings and the raw registers."""
    inverter = entry.runtime_data.inverter
    coordinator = entry.runtime_data.coordinator

    diag: dict[str, Any] = {
        "config_entry": entry.as_dict(),
        "discovered": inverter.discovered,
        "identity": asdict(inverter.identity) if inverter.discovered else None,
        "phases": inverter.phases,
        "model_chain": [
            {"model_id": model.model_id, "address": model.address, "length": model.length}
            for model in inverter.model_chain
        ],
        "vendor_model_length": inverter.vendor_model_length,
        "data": coordinator.data,
        "settings": (
            settings.data if (settings := entry.runtime_data.settings_coordinator) else None
        ),
    }

    if inverter.discovered:
        try:
            raw = await inverter.async_read_raw()
        except (ModbusError, SunSpecError, FimerError) as err:
            diag["registers"] = {"error": str(err)}
        else:
            diag["registers"] = {
                space: {str(address): value for address, value in sorted(registers.items())}
                for space, registers in raw.items()
            }

    return async_redact_data(diag, TO_REDACT)
