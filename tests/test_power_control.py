"""Tests for the experimental power limit control."""

from __future__ import annotations

from modbus_connection import ModbusExceptionError
from modbus_connection.mock import MockModbusUnit
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry
from pytest_homeassistant_custom_component.typing import ClientSessionGenerator

from custom_components.fimer.const import CONF_POWER_CONTROL, DOMAIN
from custom_components.fimer.issues import ISSUE_POWER_CONTROL_UNSUPPORTED, issue_id
from homeassistant.components.number import ATTR_VALUE, DOMAIN as NUMBER_DOMAIN, SERVICE_SET_VALUE
from homeassistant.components.switch import DOMAIN as SWITCH_DOMAIN
from homeassistant.config_entries import ConfigEntryState
from homeassistant.const import (
    ATTR_ENTITY_ID,
    CONF_SCAN_INTERVAL,
    SERVICE_TURN_OFF,
    SERVICE_TURN_ON,
    STATE_OFF,
    STATE_ON,
    STATE_UNAVAILABLE,
)
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import issue_registry as ir
from homeassistant.setup import async_setup_component

from .conftest import default_register_map

NUMBER = "number.pvi_10_0_outd_power_limit_active_power"
SWITCH = "switch.pvi_10_0_outd_power_limit_enabled"
PCT, ENA = 232 + 5, 232 + 9


SUPPORTED_OPTIONS = "R"  # code 82: TRIO-8.5-TL-OUTD-S, a family the card can set parameters on


@pytest.fixture(autouse=True)
def supported_inverter(mock_unit: MockModbusUnit) -> None:
    """Serve an inverter that honours the limit; the default PVI-10.0 does not."""
    mock_unit.holding.update(default_register_map(options=SUPPORTED_OPTIONS))


async def _setup(hass: HomeAssistant, entry: MockConfigEntry, *, power_control: bool) -> None:
    entry.add_to_hass(hass)
    hass.config_entries.async_update_entry(entry, options={CONF_POWER_CONTROL: power_control})
    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()


async def test_entities_only_with_option(
    hass: HomeAssistant, mock_config_entry: MockConfigEntry
) -> None:
    await _setup(hass, mock_config_entry, power_control=False)
    assert mock_config_entry.runtime_data.settings_coordinator is None
    assert hass.states.get(NUMBER) is None
    assert hass.states.get(SWITCH) is None


async def test_no_entities_without_controls_model(
    hass: HomeAssistant, mock_config_entry: MockConfigEntry, mock_unit: MockModbusUnit
) -> None:
    mock_unit.holding.clear()
    mock_unit.holding.update(
        default_register_map(include_controls_model=False, options=SUPPORTED_OPTIONS)
    )
    await _setup(hass, mock_config_entry, power_control=True)
    assert mock_config_entry.state is ConfigEntryState.LOADED
    assert mock_config_entry.runtime_data.settings_coordinator is None
    assert hass.states.get(NUMBER) is None


async def test_number_and_switch(
    hass: HomeAssistant, mock_config_entry: MockConfigEntry, mock_unit: MockModbusUnit
) -> None:
    await _setup(hass, mock_config_entry, power_control=True)
    assert hass.states.get(NUMBER).state == "100"
    assert hass.states.get(SWITCH).state == STATE_OFF

    # a new value while disabled only stores the value
    await hass.services.async_call(
        NUMBER_DOMAIN, SERVICE_SET_VALUE, {ATTR_ENTITY_ID: NUMBER, ATTR_VALUE: 70}, blocking=True
    )
    assert mock_unit.holding[PCT] == 70
    assert mock_unit.holding[ENA] == 0
    assert hass.states.get(NUMBER).state == "70"

    # switching on applies the stored value
    await hass.services.async_call(
        SWITCH_DOMAIN, SERVICE_TURN_ON, {ATTR_ENTITY_ID: SWITCH}, blocking=True
    )
    assert mock_unit.holding[ENA] == 1
    assert hass.states.get(SWITCH).state == STATE_ON

    # a new value while enabled re-asserts the flag
    mock_unit.holding[ENA] = 0
    await hass.services.async_call(
        NUMBER_DOMAIN, SERVICE_SET_VALUE, {ATTR_ENTITY_ID: NUMBER, ATTR_VALUE: 50}, blocking=True
    )
    assert (mock_unit.holding[PCT], mock_unit.holding[ENA]) == (50, 1)

    await hass.services.async_call(
        SWITCH_DOMAIN, SERVICE_TURN_OFF, {ATTR_ENTITY_ID: SWITCH}, blocking=True
    )
    assert mock_unit.holding[ENA] == 0
    assert hass.states.get(SWITCH).state == STATE_OFF


async def test_negative_acknowledge_is_verified_by_readback(
    hass: HomeAssistant, mock_config_entry: MockConfigEntry, mock_unit: MockModbusUnit
) -> None:
    """The datalogger answers exception 7 but applies the flag: the entity follows."""
    await _setup(hass, mock_config_entry, power_control=True)
    mock_unit.fail_write(ENA, ModbusExceptionError.from_code(7, "negative acknowledge"))
    mock_unit.holding[ENA] = 1  # what the card really did
    await hass.services.async_call(
        SWITCH_DOMAIN, SERVICE_TURN_ON, {ATTR_ENTITY_ID: SWITCH}, blocking=True
    )
    assert hass.states.get(SWITCH).state == STATE_ON


async def test_refused_write_raises(
    hass: HomeAssistant, mock_config_entry: MockConfigEntry, mock_unit: MockModbusUnit
) -> None:
    await _setup(hass, mock_config_entry, power_control=True)
    mock_unit.fail_write(PCT, ModbusExceptionError.from_code(2, "illegal data address"))
    with pytest.raises(HomeAssistantError, match="illegal data address"):
        await hass.services.async_call(
            NUMBER_DOMAIN,
            SERVICE_SET_VALUE,
            {ATTR_ENTITY_ID: NUMBER, ATTR_VALUE: 30},
            blocking=True,
        )
    # the flag did not change although the card said it did not: a write error
    mock_unit.fail_write(PCT, None)
    mock_unit.fail_write(ENA, ModbusExceptionError.from_code(7, "negative acknowledge"))
    with pytest.raises(HomeAssistantError, match="WMaxLim_Ena"):
        await hass.services.async_call(
            SWITCH_DOMAIN, SERVICE_TURN_ON, {ATTR_ENTITY_ID: SWITCH}, blocking=True
        )


async def test_settings_without_controls_after_rediscovery(
    hass: HomeAssistant, mock_config_entry: MockConfigEntry, mock_unit: MockModbusUnit
) -> None:
    """If a re-discovery loses model 123, the settings coordinator reports the failure."""
    await _setup(hass, mock_config_entry, power_control=True)
    settings = mock_config_entry.runtime_data.settings_coordinator
    assert settings is not None
    mock_config_entry.runtime_data.inverter.controls = None
    await settings.async_refresh()
    assert not settings.last_update_success

    settings.async_set_updated_data({})
    await hass.async_block_till_done()
    assert hass.states.get(SWITCH).state == "unknown"


async def test_unsupported_model_gets_an_issue_instead_of_entities(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_unit: MockModbusUnit,
    hass_client: ClientSessionGenerator,
    issue_registry: ir.IssueRegistry,
) -> None:
    """A PVI-10.0 with the option on gets no entities but a repair that switches it off."""
    mock_unit.holding.update(default_register_map())  # back to the PVI-10.0-OUTD
    await _setup(hass, mock_config_entry, power_control=True)
    assert mock_config_entry.state is ConfigEntryState.LOADED
    assert mock_config_entry.runtime_data.settings_coordinator is None
    assert mock_config_entry.runtime_data.power_control.supported is False
    assert hass.states.get(NUMBER) is None
    issue = issue_registry.async_get_issue(
        DOMAIN, issue_id(ISSUE_POWER_CONTROL_UNSUPPORTED, mock_config_entry.entry_id)
    )
    assert issue is not None
    assert issue.is_fixable
    assert issue.translation_placeholders["model"] == "PVI-10.0-OUTD"

    assert await async_setup_component(hass, "repairs", {})
    client = await hass_client()
    resp = await client.post(
        "/api/repairs/issues/fix", json={"handler": DOMAIN, "issue_id": issue.issue_id}
    )
    flow = await resp.json()
    assert flow["step_id"] == "confirm"
    assert flow["description_placeholders"] == {"model": "PVI-10.0-OUTD"}
    resp = await client.post(f"/api/repairs/issues/fix/{flow['flow_id']}", json={})
    assert (await resp.json())["type"] == "create_entry"
    await hass.async_block_till_done()
    assert mock_config_entry.options[CONF_POWER_CONTROL] is False
    assert mock_config_entry.state is ConfigEntryState.LOADED
    assert (
        issue_registry.async_get_issue(
            DOMAIN, issue_id(ISSUE_POWER_CONTROL_UNSUPPORTED, mock_config_entry.entry_id)
        )
        is None
    )


async def test_options_offer_power_control_only_when_supported(
    hass: HomeAssistant, mock_config_entry: MockConfigEntry, mock_unit: MockModbusUnit
) -> None:
    """The option appears for a TRIO-8.5 and is replaced by the reason for a PVI-10.0."""
    await _setup(hass, mock_config_entry, power_control=False)
    result = await hass.config_entries.options.async_init(mock_config_entry.entry_id)
    assert result["step_id"] == "init"
    assert CONF_POWER_CONTROL in {str(key) for key in result["data_schema"].schema}
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {CONF_SCAN_INTERVAL: 45, CONF_POWER_CONTROL: True}
    )
    await hass.async_block_till_done()
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert mock_config_entry.options[CONF_POWER_CONTROL] is True
    assert hass.states.get(NUMBER) is not None

    mock_unit.holding.update(default_register_map())  # the inverter is now a PVI-10.0-OUTD
    await hass.config_entries.async_reload(mock_config_entry.entry_id)
    await hass.async_block_till_done()
    result = await hass.config_entries.options.async_init(mock_config_entry.entry_id)
    assert result["step_id"] == "no_power_control"
    assert result["description_placeholders"] == {"model": "PVI-10.0-OUTD"}
    assert CONF_POWER_CONTROL not in {str(key) for key in result["data_schema"].schema}
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {CONF_SCAN_INTERVAL: 45}
    )
    await hass.async_block_till_done()
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert mock_config_entry.options[CONF_POWER_CONTROL] is False
    # the registry keeps the entity, but nothing serves it any more
    assert hass.states.get(NUMBER).state == STATE_UNAVAILABLE
    assert mock_config_entry.runtime_data.settings_coordinator is None
