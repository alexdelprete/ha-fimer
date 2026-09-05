"""Tests for the FIMER (ABB / Power-One) diagnostics."""

from __future__ import annotations

from modbus_connection import ModbusConnectionError
from modbus_connection.mock import MockModbusUnit
from pytest_homeassistant_custom_component.common import MockConfigEntry
from pytest_homeassistant_custom_component.components.diagnostics import (
    get_diagnostics_for_config_entry,
)
from pytest_homeassistant_custom_component.typing import ClientSessionGenerator

from homeassistant.components.diagnostics import REDACTED
from homeassistant.core import HomeAssistant


async def test_diagnostics(
    hass: HomeAssistant,
    hass_client: ClientSessionGenerator,
    init_integration: MockConfigEntry,
) -> None:
    """Diagnostics carry the chain, the readings and the raw registers, redacted."""
    diag = await get_diagnostics_for_config_entry(hass, hass_client, init_integration)

    assert diag["config_entry"]["data"]["host"] == REDACTED
    modbus = diag["modbus"]
    assert modbus["identity"]["serial_number"] == REDACTED
    assert modbus["identity"]["inverter_model"] == "PVI-10.0-OUTD"
    assert modbus["phases"] == 3
    assert [model["model_id"] for model in modbus["model_chain"]] == [
        1,
        103,
        160,
        120,
        121,
        123,
        64061,
    ]
    assert modbus["vendor_model_length"] == 124
    assert modbus["data"]["W"] == 1500
    assert modbus["data"]["SN"] == REDACTED
    assert modbus["registers"]["holding"]["2"] == 1
    assert modbus["registers"]["holding"]["258"] == 64061
    assert diag["devices"][0]["type"] == "inverter"
    assert "rest" not in diag


async def test_diagnostics_offline(
    hass: HomeAssistant,
    hass_client: ClientSessionGenerator,
    init_integration: MockConfigEntry,
    mock_unit: MockModbusUnit,
) -> None:
    """When the inverter does not answer, the register dump reports the error."""
    mock_unit.fail_requests(ModbusConnectionError("asleep"))
    diag = await get_diagnostics_for_config_entry(hass, hass_client, init_integration)
    assert diag["modbus"]["registers"] == {"error": "asleep"}
    assert diag["modbus"]["data"]["W"] == 1500
