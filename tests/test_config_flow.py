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

from custom_components.fimer.const import (
    CONF_BASE_ADDRESS,
    CONF_CONNECTION_ISSUES,
    CONF_FAILURES_THRESHOLD,
    CONF_MIGRATE_FROM,
    CONF_MODBUS_SECTION,
    CONF_NOTIFY_RECOVERY,
    CONF_POWER_CONTROL,
    CONF_REST_MODEL,
    CONF_REST_REQUIRES_AUTH,
    CONF_REST_SECTION,
    CONF_UNIT_ID,
    CONF_USE_MODBUS,
    CONF_USE_REST,
    DOMAIN,
    LEGACY_REST_DOMAIN,
)
from homeassistant import config_entries
from homeassistant.const import (
    CONF_HOST,
    CONF_PASSWORD,
    CONF_PORT,
    CONF_SCAN_INTERVAL,
    CONF_USERNAME,
)
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.exceptions import HomeAssistantError

from .conftest import HOST, REST_PASSWORD, SERIAL_NUMBER, default_register_map, fake_vsn300

USER_INPUT = {
    CONF_HOST: HOST,
    CONF_PORT: 502,
    CONF_MODBUS_SECTION: {CONF_USE_MODBUS: True, CONF_UNIT_ID: 2, CONF_BASE_ADDRESS: 0},
    CONF_REST_SECTION: {CONF_USE_REST: False, CONF_USERNAME: "guest", CONF_PASSWORD: ""},
}
ENTRY_DATA = {
    CONF_HOST: HOST,
    CONF_PORT: 502,
    CONF_USE_MODBUS: True,
    CONF_UNIT_ID: 2,
    CONF_BASE_ADDRESS: 0,
    CONF_USE_REST: False,
    CONF_USERNAME: "guest",
    CONF_PASSWORD: "",
}


def with_rest(host: str, user_input: dict = USER_INPUT, *, modbus: bool = True) -> dict:
    """The form input with the REST section enabled against a fake card."""
    return {
        **user_input,
        CONF_HOST: host,
        CONF_MODBUS_SECTION: {**user_input[CONF_MODBUS_SECTION], CONF_USE_MODBUS: modbus},
        CONF_REST_SECTION: {
            CONF_USE_REST: True,
            CONF_USERNAME: "guest",
            CONF_PASSWORD: REST_PASSWORD,
        },
    }


async def test_user_flow(hass: HomeAssistant) -> None:
    """The user flow discovers the inverter and names the entry after its model."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "manual"
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
        **USER_INPUT,
        CONF_HOST: "192.0.2.20",
        CONF_PORT: 1502,
        CONF_MODBUS_SECTION: {CONF_USE_MODBUS: True, CONF_UNIT_ID: 247, CONF_BASE_ADDRESS: 0},
    }
    result = await hass.config_entries.flow.async_configure(result["flow_id"], new_input)
    await hass.async_block_till_done()
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "reconfigure_successful"
    assert init_integration.data == {
        **ENTRY_DATA,
        CONF_HOST: "192.0.2.20",
        CONF_PORT: 1502,
        CONF_UNIT_ID: 247,
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
    # a PVI-10.0-OUTD cannot act on a power limit, so that option is not offered
    assert result["step_id"] == "no_power_control"

    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {CONF_SCAN_INTERVAL: 60}
    )
    await hass.async_block_till_done()
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert init_integration.options == {
        CONF_SCAN_INTERVAL: 60,
        CONF_POWER_CONTROL: False,
        CONF_CONNECTION_ISSUES: True,
        CONF_FAILURES_THRESHOLD: 3,
        CONF_NOTIFY_RECOVERY: True,
    }
    assert init_integration.runtime_data.coordinator.update_interval.total_seconds() == 60


async def test_no_source_selected(hass: HomeAssistant) -> None:
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {
            **USER_INPUT,
            CONF_MODBUS_SECTION: {**USER_INPUT[CONF_MODBUS_SECTION], CONF_USE_MODBUS: False},
        },
    )
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": "no_source"}


async def test_user_flow_with_rest(hass: HomeAssistant, serve_rest: Any) -> None:
    """Both sources: the Modbus serial keys the entry, the REST detection is cached."""
    host = await serve_rest(fake_vsn300())
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    with patch("custom_components.fimer.async_setup_entry", return_value=True):
        result = await hass.config_entries.flow.async_configure(result["flow_id"], with_rest(host))
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["result"].unique_id == SERIAL_NUMBER
    assert result["data"][CONF_USE_REST] is True
    assert result["data"][CONF_REST_MODEL] == "VSN300"
    assert result["data"][CONF_REST_REQUIRES_AUTH] is True
    assert result["data"][CONF_PASSWORD] == REST_PASSWORD


async def test_user_flow_rest_only(hass: HomeAssistant, serve_rest: Any) -> None:
    """REST only: the inverter's serial from livedata keys the entry, its model titles it."""
    host = await serve_rest(fake_vsn300())
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    with patch("custom_components.fimer.async_setup_entry", return_value=True):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], with_rest(host, modbus=False)
        )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["result"].unique_id == "YYYYYY-3G82-XXXX"
    assert result["title"] == "PVI-10.0-OUTD"


@pytest.mark.parametrize(
    ("password", "error"),
    [("wrong", "invalid_auth")],
)
async def test_user_flow_rest_errors(
    hass: HomeAssistant, serve_rest: Any, password: str, error: str
) -> None:
    host = await serve_rest(fake_vsn300())
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    user_input = with_rest(host, modbus=False)
    user_input[CONF_REST_SECTION][CONF_PASSWORD] = password
    result = await hass.config_entries.flow.async_configure(result["flow_id"], user_input)
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": error}


async def test_user_flow_rest_unreachable(hass: HomeAssistant, socket_enabled: None) -> None:
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], with_rest("127.0.0.1:1", modbus=False)
    )
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": "cannot_connect"}


async def test_legacy_takeover_menu(hass: HomeAssistant, serve_rest: Any) -> None:
    """With a legacy REST entry present, the flow offers to take it over."""
    host = await serve_rest(fake_vsn300())
    legacy = MockConfigEntry(
        domain=LEGACY_REST_DOMAIN,
        title="VSN300 (LLLLLL-3N16-BBBB)",
        data={CONF_HOST: host, CONF_USERNAME: "guest", CONF_PASSWORD: REST_PASSWORD},
    )
    legacy.add_to_hass(hass)

    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    assert result["type"] is FlowResultType.MENU
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"next_step_id": "legacy"}
    )
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "legacy"
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"legacy_entry": legacy.entry_id}
    )
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "manual"

    with patch("custom_components.fimer.async_setup_entry", return_value=True):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], with_rest(host, modbus=False)
        )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["data"][CONF_MIGRATE_FROM] == legacy.entry_id

    # the manual path is still offered
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"next_step_id": "manual"}
    )
    assert result["step_id"] == "manual"
