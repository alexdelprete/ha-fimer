"""Tests for the experimental power limit control."""

from __future__ import annotations

from modbus_connection import ModbusExceptionError
from modbus_connection.mock import MockModbusUnit
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.fimer.const import CONF_POWER_CONTROL
from homeassistant.components.number import ATTR_VALUE, DOMAIN as NUMBER_DOMAIN, SERVICE_SET_VALUE
from homeassistant.components.switch import DOMAIN as SWITCH_DOMAIN
from homeassistant.config_entries import ConfigEntryState
from homeassistant.const import (
    ATTR_ENTITY_ID,
    SERVICE_TURN_OFF,
    SERVICE_TURN_ON,
    STATE_OFF,
    STATE_ON,
)
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError

from .conftest import default_register_map

NUMBER = "number.pvi_10_0_outd_power_limit_active_power"
SWITCH = "switch.pvi_10_0_outd_power_limit_enabled"
PCT, ENA = 232 + 5, 232 + 9


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
    mock_unit.holding.update(default_register_map(include_controls_model=False))
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
