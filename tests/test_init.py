"""Tests for FIMER (ABB / Power-One) integration setup."""

from __future__ import annotations

import logging
from unittest.mock import patch

from modbus_connection import ModbusConnectionError
from modbus_connection.mock import MockModbusUnit
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.fimer.const import DOMAIN
from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import device_registry as dr

from .conftest import SERIAL_NUMBER


async def test_setup_and_unload(hass: HomeAssistant, init_integration: MockConfigEntry) -> None:
    """The entry loads, exposes its runtime data and unloads cleanly."""
    entry = init_integration
    assert entry.state is ConfigEntryState.LOADED
    assert entry.runtime_data.inverter.discovered
    assert entry.runtime_data.coordinator.data["W"] == 1500

    assert await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()
    assert entry.state is ConfigEntryState.NOT_LOADED


async def test_setup_retries_when_offline(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_unit: MockModbusUnit,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """An inverter that does not answer leaves the entry in setup retry, without a stack dump."""
    caplog.set_level(logging.DEBUG, logger="custom_components.fimer")
    mock_unit.fail_requests(ModbusConnectionError("no route to host"))
    mock_config_entry.add_to_hass(hass)
    await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()
    assert mock_config_entry.state is ConfigEntryState.SETUP_RETRY
    assert "no route to host" in caplog.text
    assert "Traceback" not in caplog.text


async def test_setup_error_on_link_conflict(
    hass: HomeAssistant, mock_config_entry: MockConfigEntry
) -> None:
    """A host held by another integration with other link settings is a setup error."""
    mock_config_entry.add_to_hass(hass)
    with patch(
        "custom_components.fimer.async_get_unit",
        side_effect=HomeAssistantError("already in use"),
    ):
        await hass.config_entries.async_setup(mock_config_entry.entry_id)
        await hass.async_block_till_done()
    assert mock_config_entry.state is ConfigEntryState.SETUP_ERROR


async def test_device_registry(
    hass: HomeAssistant, init_integration: MockConfigEntry, device_registry: dr.DeviceRegistry
) -> None:
    """The inverter is registered from its common model, with the model from Opt."""
    device = device_registry.async_get_device_by_identifier(
        (DOMAIN, SERIAL_NUMBER), init_integration.entry_id
    )
    assert device is not None
    assert device.manufacturer == "ABB"
    assert device.model == "PVI-10.0-OUTD"
    assert device.sw_version == "1.9.2"
    assert device.serial_number == SERIAL_NUMBER
    assert device.name == "PVI-10.0-OUTD"
