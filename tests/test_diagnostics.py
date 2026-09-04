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
    assert diag["identity"]["serial_number"] == REDACTED
    assert diag["identity"]["inverter_model"] == "PVI-10.0-OUTD"
    assert diag["phases"] == 3
    assert [model["model_id"] for model in diag["model_chain"]] == [1, 103, 160, 64061]
    assert diag["vendor_model_length"] == 124
    assert diag["data"]["W"] == 1500
    assert diag["data"]["SN"] == REDACTED
    assert diag["registers"]["holding"]["2"] == 1
    assert diag["registers"]["holding"]["172"] == 64061


async def test_diagnostics_offline(
    hass: HomeAssistant,
    hass_client: ClientSessionGenerator,
    init_integration: MockConfigEntry,
    mock_unit: MockModbusUnit,
) -> None:
    """When the inverter does not answer, the register dump reports the error."""
    mock_unit.fail_requests(ModbusConnectionError("asleep"))
    diag = await get_diagnostics_for_config_entry(hass, hass_client, init_integration)
    assert diag["registers"] == {"error": "asleep"}
    assert diag["data"]["W"] == 1500
