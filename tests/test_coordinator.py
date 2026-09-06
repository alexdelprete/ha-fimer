"""Tests for the FIMER (ABB / Power-One) coordinator."""

from __future__ import annotations

from datetime import timedelta
from unittest.mock import patch

from freezegun.api import FrozenDateTimeFactory
from modbus_connection import ModbusConnectionError
from modbus_connection.mock import MockModbusUnit
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry, async_fire_time_changed

from custom_components.fimer.const import ERROR_SCAN_INTERVAL, MAX_FAILED_UPDATES
from homeassistant.const import STATE_UNAVAILABLE
from homeassistant.core import HomeAssistant

from .conftest import default_register_map


async def _poll(hass: HomeAssistant, freezer: FrozenDateTimeFactory, seconds: int = 31) -> None:
    freezer.tick(timedelta(seconds=seconds))
    async_fire_time_changed(hass)
    await hass.async_block_till_done()


async def test_map_shift_rediscovers(
    hass: HomeAssistant,
    init_integration: MockConfigEntry,
    mock_unit: MockModbusUnit,
    freezer: FrozenDateTimeFactory,
) -> None:
    """A moved register map is re-discovered in place instead of failing."""
    inverter = init_integration.runtime_data.inverter
    assert inverter.phases == 3

    # the datalogger now serves a single-phase inverter model at the same address
    mock_unit.holding.clear()
    mock_unit.holding.update(default_register_map(three_phase=False))
    await _poll(hass, freezer)

    coordinator = init_integration.runtime_data.coordinator
    assert coordinator.last_update_success
    assert inverter.phases == 1
    assert coordinator.data["W"] == 1500


async def test_failed_polls_stretch_the_interval(
    hass: HomeAssistant,
    init_integration: MockConfigEntry,
    mock_unit: MockModbusUnit,
    freezer: FrozenDateTimeFactory,
) -> None:
    """After repeated failures the inverter is polled gently until it answers."""
    coordinator = init_integration.runtime_data.coordinator
    default_interval = coordinator.update_interval

    mock_unit.fail_requests(ModbusConnectionError("asleep"))
    for _ in range(MAX_FAILED_UPDATES):
        await _poll(hass, freezer)
    assert not coordinator.last_update_success
    assert coordinator.update_interval == timedelta(seconds=ERROR_SCAN_INTERVAL)

    mock_unit.fail_requests(None)
    await _poll(hass, freezer, ERROR_SCAN_INTERVAL + 1)
    assert coordinator.last_update_success
    assert coordinator.update_interval == default_interval


async def test_unexpected_error_is_a_failed_poll(
    hass: HomeAssistant,
    init_integration: MockConfigEntry,
    freezer: FrozenDateTimeFactory,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """A bug in a poll makes the entities unavailable without a traceback at ERROR."""
    inverter = init_integration.runtime_data.inverter
    with patch.object(inverter, "async_update", side_effect=RuntimeError("boom")):
        freezer.tick(timedelta(seconds=31))
        async_fire_time_changed(hass)
        await hass.async_block_till_done()
    assert hass.states.get("sensor.pvi_10_0_outd_power_ac").state == STATE_UNAVAILABLE
    assert "Unexpected error fetching" not in caplog.text  # HA's own traceback path
    assert "unexpected RuntimeError: boom" in caplog.text
    assert init_integration.runtime_data.coordinator.outage.failures == 1
