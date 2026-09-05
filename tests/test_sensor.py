"""Tests for the FIMER (ABB / Power-One) sensors."""

from __future__ import annotations

from dataclasses import replace
from datetime import timedelta

from freezegun.api import FrozenDateTimeFactory
from modbus_connection import ModbusConnectionError
from modbus_connection.mock import MockModbusUnit
import pytest
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    async_fire_time_changed,
    mock_restore_cache_with_extra_data,
)

from custom_components.fimer.pyfimer.modbus.testing import InverterSpec
from homeassistant.const import STATE_UNAVAILABLE, STATE_UNKNOWN
from homeassistant.core import HomeAssistant, State
from homeassistant.helpers import entity_registry as er

from .conftest import INVERTER_SPEC, default_register_map


@pytest.mark.parametrize(
    ("entity_id", "state"),
    [
        ("sensor.pvi_10_0_outd_ac_power", "1500"),
        ("sensor.pvi_10_0_outd_ac_current", "6.54"),
        ("sensor.pvi_10_0_outd_ac_current_phase_a", "2.18"),
        ("sensor.pvi_10_0_outd_ac_voltage_phase_a", "230.5"),
        ("sensor.pvi_10_0_outd_ac_voltage_phase_a_b", "400.1"),
        ("sensor.pvi_10_0_outd_ac_frequency", "50.02"),
        ("sensor.pvi_10_0_outd_power_factor", "99.5"),
        ("sensor.pvi_10_0_outd_total_energy", "1234.567"),
        ("sensor.pvi_10_0_outd_dc_power", "1550"),
        ("sensor.pvi_10_0_outd_cabinet_temperature", "45.3"),
        ("sensor.pvi_10_0_outd_other_temperature", "41.2"),
        ("sensor.pvi_10_0_outd_operating_state", "mppt"),
        ("sensor.pvi_10_0_outd_dc_current_input_1", "3.21"),
        ("sensor.pvi_10_0_outd_dc_voltage_input_2", "340.0"),
        ("sensor.pvi_10_0_outd_dc_power_input_2", "750"),
        ("sensor.pvi_10_0_outd_global_state", "Run"),
        ("sensor.pvi_10_0_outd_inverter_state", "Run"),
        ("sensor.pvi_10_0_outd_dc_input_1_state", "MPPT"),
        ("sensor.pvi_10_0_outd_alarms", "Sun Low, Grid OV, Energy data reset"),
        ("sensor.pvi_10_0_outd_system_time", "2025-05-08T06:13:20+00:00"),
        ("sensor.pvi_10_0_outd_energy_today", "12.345"),
        ("sensor.pvi_10_0_outd_energy_this_year", "3000.0"),
        ("sensor.pvi_10_0_outd_inverter_temperature", "45.5"),
        ("sensor.pvi_10_0_outd_booster_temperature", "50.25"),
        ("sensor.pvi_10_0_outd_isolation_resistance_input_1", "12.5"),
        ("sensor.pvi_10_0_outd_cos_phi", "0.995"),
        ("sensor.pvi_10_0_outd_power_limit_permanent", "100"),
    ],
)
async def test_sensor_states(
    hass: HomeAssistant, init_integration: MockConfigEntry, entity_id: str, state: str
) -> None:
    """Every implemented point becomes a sensor with the converted reading."""
    assert (entity := hass.states.get(entity_id)) is not None, entity_id
    assert entity.state == state


async def test_unimplemented_points_have_no_sensor(
    hass: HomeAssistant, init_integration: MockConfigEntry, entity_registry: er.EntityRegistry
) -> None:
    """Points the inverter does not implement create no entity at all."""
    assert hass.states.get("sensor.pvi_10_0_outd_dc_voltage") is None
    assert hass.states.get("sensor.pvi_10_0_outd_dc_energy_input_1") is None
    assert hass.states.get("sensor.pvi_10_0_outd_heat_sink_temperature") is None
    assert hass.states.get("sensor.pvi_10_0_outd_dc_current_input_3") is None


async def test_disabled_by_default(
    hass: HomeAssistant, init_integration: MockConfigEntry, entity_registry: er.EntityRegistry
) -> None:
    """Duplicate or low-value points are registered but disabled."""
    entry = entity_registry.async_get("sensor.pvi_10_0_outd_total_energy_vendor_model")
    assert entry is not None
    assert entry.disabled_by is er.RegistryEntryDisabler.INTEGRATION
    entry = entity_registry.async_get("sensor.pvi_10_0_outd_vendor_operating_state")
    assert entry is not None
    assert entry.disabled_by is er.RegistryEntryDisabler.INTEGRATION


async def test_point_appearing_later_gets_a_sensor(
    hass: HomeAssistant,
    init_integration: MockConfigEntry,
    mock_unit: MockModbusUnit,
    freezer: FrozenDateTimeFactory,
) -> None:
    """A point that starts reporting after setup gets its sensor on the next poll."""
    assert hass.states.get("sensor.pvi_10_0_outd_dc_voltage") is None
    # M103 header at 70, DCV at offset 29, DCV_SF -1: 350.0 V
    mock_unit.holding[70 + 29] = 3500

    freezer.tick(timedelta(seconds=31))
    async_fire_time_changed(hass)
    await hass.async_block_till_done()

    assert (state := hass.states.get("sensor.pvi_10_0_outd_dc_voltage")) is not None
    assert state.state == "350.0"


async def test_energy_sensor_keeps_value_while_offline(
    hass: HomeAssistant,
    init_integration: MockConfigEntry,
    mock_unit: MockModbusUnit,
    freezer: FrozenDateTimeFactory,
) -> None:
    """When the inverter sleeps, measurements go unavailable but counters stay."""
    mock_unit.fail_requests(ModbusConnectionError("asleep"))
    freezer.tick(timedelta(seconds=31))
    async_fire_time_changed(hass)
    await hass.async_block_till_done()

    assert hass.states.get("sensor.pvi_10_0_outd_ac_power").state == STATE_UNAVAILABLE
    assert hass.states.get("sensor.pvi_10_0_outd_total_energy").state == "1234.567"
    assert hass.states.get("sensor.pvi_10_0_outd_energy_today").state == "12.345"

    mock_unit.fail_requests(None)
    freezer.tick(timedelta(seconds=31))
    async_fire_time_changed(hass)
    await hass.async_block_till_done()
    assert hass.states.get("sensor.pvi_10_0_outd_ac_power").state == "1500"


async def _restart_with_energy_unreported(
    hass: HomeAssistant, entry: MockConfigEntry, mock_unit: MockModbusUnit
) -> None:
    """Reload the entry with the inverter not yet reporting its total energy."""
    assert await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()
    mock_unit.holding.clear()
    mock_unit.holding.update(default_register_map(inverter=_inverter_with_energy(0)))


async def test_energy_sensor_restores_last_value(
    hass: HomeAssistant, init_integration: MockConfigEntry, mock_unit: MockModbusUnit
) -> None:
    """A counter not yet reported after a restart shows the restored value, not a gap."""
    await _restart_with_energy_unreported(hass, init_integration, mock_unit)
    mock_restore_cache_with_extra_data(
        hass,
        (
            (
                State("sensor.pvi_10_0_outd_total_energy", "1234.567"),
                {"native_value": 1234567, "native_unit_of_measurement": "Wh"},
            ),
        ),
    )
    await hass.config_entries.async_setup(init_integration.entry_id)
    await hass.async_block_till_done()

    assert hass.states.get("sensor.pvi_10_0_outd_total_energy").state == "1234.567"


async def test_energy_sensor_without_history_is_unknown(
    hass: HomeAssistant, init_integration: MockConfigEntry, mock_unit: MockModbusUnit
) -> None:
    """A counter not yet reported after a restart with nothing to restore is unknown."""
    await _restart_with_energy_unreported(hass, init_integration, mock_unit)
    mock_restore_cache_with_extra_data(hass, ())
    await hass.config_entries.async_setup(init_integration.entry_id)
    await hass.async_block_till_done()

    assert hass.states.get("sensor.pvi_10_0_outd_total_energy").state == STATE_UNKNOWN


def _inverter_with_energy(energy_total: int) -> InverterSpec:
    return replace(INVERTER_SPEC, energy_total=energy_total)
