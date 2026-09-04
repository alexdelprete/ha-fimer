"""Tests for the FIMER (ABB / Power-One) config flow."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any
from unittest.mock import patch

from modbus_connection import ModbusConnectionError
from modbus_connection.mock import MockModbusUnit
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.fimer.const import CONF_ADVANCED, CONF_BASE_ADDRESS, CONF_UNIT_ID, DOMAIN
from homeassistant import config_entries
from homeassistant.const import CONF_HOST, CONF_PORT, CONF_SCAN_INTERVAL
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.exceptions import HomeAssistantError

from .conftest import HOST, SERIAL_NUMBER, default_register_map

USER_INPUT = {
    CONF_HOST: HOST,
    CONF_PORT: 502,
    CONF_ADVANCED: {CONF_UNIT_ID: 2, CONF_BASE_ADDRESS: 0},
}
ENTRY_DATA = {CONF_HOST: HOST, CONF_PORT: 502, CONF_UNIT_ID: 2, CONF_BASE_ADDRESS: 0}


async def test_user_flow(hass: HomeAssistant) -> None:
    """The user flow discovers the inverter and names the entry after its model."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "user"
    assert result["errors"] == {}

    with patch("custom_components.fimer.async_setup_entry", return_value=True) as mock_setup:
        result = await hass.config_entries.flow.async_configure(result["flow_id"], USER_INPUT)
        await hass.async_block_till_done()

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "PVI-10.0-OUTD"
    assert result["data"] == ENTRY_DATA
    assert result["result"].unique_id == SERIAL_NUMBER
    assert len(mock_setup.mock_calls) == 1


async def test_user_flow_unknown_model_uses_host_as_title(
    hass: HomeAssistant, mock_unit: MockModbusUnit
) -> None:
    """An unknown Opt code falls back to the device model, then the host."""
    mock_unit.holding.clear()
    mock_unit.holding.update(default_register_map(options="?", device_model=""))
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    with patch("custom_components.fimer.async_setup_entry", return_value=True):
        result = await hass.config_entries.flow.async_configure(result["flow_id"], USER_INPUT)
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == HOST


@pytest.mark.parametrize(
    ("failure", "error"),
    [
        ("offline", "cannot_connect"),
        ("no_sunspec", "no_sunspec"),
        ("no_inverter", "unsupported_device"),
        ("link_conflict", "link_conflict"),
        ("unexpected", "unknown"),
    ],
)
async def test_user_flow_errors(
    hass: HomeAssistant, mock_unit: MockModbusUnit, failure: str, error: str
) -> None:
    """Each failure maps to an error, and the flow recovers once it is fixed."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )

    if failure == "offline":
        mock_unit.fail_requests(ModbusConnectionError("no route to host"))
    elif failure == "no_sunspec":
        mock_unit.holding.clear()
    elif failure == "no_inverter":
        mock_unit.holding.clear()
        mock_unit.holding.update(
            default_register_map(
                include_inverter_model=False,
                include_mppt_model=False,
                include_vendor_model=False,
            )
        )

    patch_target = "custom_components.fimer.config_flow.async_get_temporary_unit"
    if failure == "link_conflict":

        @asynccontextmanager
        async def conflict(*args: Any, **kwargs: Any) -> AsyncIterator[MockModbusUnit]:
            raise HomeAssistantError("already in use")
            yield mock_unit  # pragma: no cover

        context = patch(patch_target, conflict)
    elif failure == "unexpected":

        @asynccontextmanager
        async def boom(*args: Any, **kwargs: Any) -> AsyncIterator[MockModbusUnit]:
            raise RuntimeError("boom")
            yield mock_unit  # pragma: no cover

        context = patch(patch_target, boom)
    else:
        context = patch("custom_components.fimer.config_flow._LOGGER")  # no-op patch

    with context:
        result = await hass.config_entries.flow.async_configure(result["flow_id"], USER_INPUT)
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": error}

    # fix the failure and finish
    mock_unit.fail_requests(None)
    mock_unit.holding.clear()
    mock_unit.holding.update(default_register_map())
    with patch("custom_components.fimer.async_setup_entry", return_value=True):
        result = await hass.config_entries.flow.async_configure(result["flow_id"], USER_INPUT)
    assert result["type"] is FlowResultType.CREATE_ENTRY


async def test_user_flow_already_configured(
    hass: HomeAssistant, mock_config_entry: MockConfigEntry
) -> None:
    """An inverter already set up cannot be added twice."""
    mock_config_entry.add_to_hass(hass)
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(result["flow_id"], USER_INPUT)
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "already_configured"


async def test_reconfigure_flow(hass: HomeAssistant, init_integration: MockConfigEntry) -> None:
    """The connection settings can be changed for the same inverter."""
    result = await init_integration.start_reconfigure_flow(hass)
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "reconfigure"

    new_input = {
        CONF_HOST: "192.0.2.20",
        CONF_PORT: 1502,
        CONF_ADVANCED: {CONF_UNIT_ID: 247, CONF_BASE_ADDRESS: 0},
    }
    result = await hass.config_entries.flow.async_configure(result["flow_id"], new_input)
    await hass.async_block_till_done()
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "reconfigure_successful"
    assert init_integration.data == {
        CONF_HOST: "192.0.2.20",
        CONF_PORT: 1502,
        CONF_UNIT_ID: 247,
        CONF_BASE_ADDRESS: 0,
    }


async def test_reconfigure_flow_other_inverter(
    hass: HomeAssistant, init_integration: MockConfigEntry, mock_unit: MockModbusUnit
) -> None:
    """Pointing the entry at a different inverter is refused."""
    mock_unit.holding.clear()
    mock_unit.holding.update(default_register_map(serial_number="OTHER-SERIAL"))
    result = await init_integration.start_reconfigure_flow(hass)
    result = await hass.config_entries.flow.async_configure(result["flow_id"], USER_INPUT)
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "unique_id_mismatch"


async def test_reconfigure_flow_error(
    hass: HomeAssistant, init_integration: MockConfigEntry, mock_unit: MockModbusUnit
) -> None:
    """A failed validation shows the form again with the error."""
    mock_unit.fail_requests(ModbusConnectionError("no route to host"))
    result = await init_integration.start_reconfigure_flow(hass)
    result = await hass.config_entries.flow.async_configure(result["flow_id"], USER_INPUT)
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": "cannot_connect"}


async def test_options_flow(hass: HomeAssistant, init_integration: MockConfigEntry) -> None:
    """The polling interval is stored as an option and the entry reloads."""
    result = await hass.config_entries.options.async_init(init_integration.entry_id)
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "init"

    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {CONF_SCAN_INTERVAL: 60}
    )
    await hass.async_block_till_done()
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert init_integration.options == {CONF_SCAN_INTERVAL: 60}
    assert init_integration.runtime_data.coordinator.update_interval.total_seconds() == 60
