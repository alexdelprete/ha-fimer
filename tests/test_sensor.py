"""Tests for the FIMER (ABB / Power-One) sensors."""

from __future__ import annotations

from dataclasses import replace
from datetime import timedelta

from freezegun.api import FrozenDateTimeFactory
from modbus_connection import ModbusConnectionError
from modbus_connection.mock import MockModbusUnit
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry, async_fire_time_changed

from custom_components.fimer.pyfimer.modbus.testing import InverterSpec
from homeassistant.const import STATE_UNAVAILABLE, STATE_UNKNOWN
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er

from .conftest import INVERTER_SPEC, default_register_map


@pytest.mark.parametrize(
    ("entity_id", "state"),
    [
        ("sensor.pvi_10_0_outd_power_ac", "1500"),
        ("sensor.pvi_10_0_outd_current_ac", "6.54"),
        ("sensor.pvi_10_0_outd_current_ac_phase_a", "2.18"),
        ("sensor.pvi_10_0_outd_voltage_ac_phase_a_n", "230.5"),
        ("sensor.pvi_10_0_outd_voltage_ac_phase_a_b", "400.1"),
        ("sensor.pvi_10_0_outd_frequency_ac_grid", "50.02"),
        ("sensor.pvi_10_0_outd_power_factor", "99.5"),
        ("sensor.pvi_10_0_outd_energy_ac_produced_lifetime", "1234.567"),
        ("sensor.pvi_10_0_outd_power_dc", "1550"),
        ("sensor.pvi_10_0_outd_cabinet_temperature", "45.3"),
        ("sensor.pvi_10_0_outd_other_temperature", "41.2"),
        ("sensor.pvi_10_0_outd_status_operating", "mppt"),
        ("sensor.pvi_10_0_outd_current_dc_string_1", "3.21"),
        ("sensor.pvi_10_0_outd_voltage_dc_string_2", "340.0"),
        ("sensor.pvi_10_0_outd_power_dc_string_2", "750"),
        ("sensor.pvi_10_0_outd_status_global", "Run"),
        ("sensor.pvi_10_0_outd_inverter_status", "Run"),
        ("sensor.pvi_10_0_outd_status_dc_input_1", "MPPT"),
        ("sensor.pvi_10_0_outd_alarms_active", "Sun Low, Grid OV, Energy data reset"),
        ("sensor.pvi_10_0_outd_system_time", "2025-05-08T06:13:20+00:00"),
        ("sensor.pvi_10_0_outd_energy_ac_produced_today", "12.345"),
        ("sensor.pvi_10_0_outd_energy_ac_produced_current_year", "3000.0"),
        ("sensor.pvi_10_0_outd_temperature_inverter", "45.5"),
        ("sensor.pvi_10_0_outd_temperature_booster", "50.25"),
        ("sensor.pvi_10_0_outd_resistance_insulation", "12.5"),
        ("sensor.pvi_10_0_outd_cos_phi", "0.995"),
        ("sensor.pvi_10_0_outd_power_limit_permanent", "100"),
        ("sensor.pvi_10_0_outd_power_rating", "10000"),
        ("sensor.pvi_10_0_outd_power_limit_active_power", "100"),
        ("sensor.pvi_10_0_outd_power_limit_enabled", "disabled"),
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
    assert hass.states.get("sensor.pvi_10_0_outd_voltage_dc") is None
    assert hass.states.get("sensor.pvi_10_0_outd_energy_dc_string_1_lifetime") is None
    assert hass.states.get("sensor.pvi_10_0_outd_temperature_heat_sink") is None
    assert hass.states.get("sensor.pvi_10_0_outd_current_dc_string_3") is None


async def test_disabled_by_default(
    hass: HomeAssistant, init_integration: MockConfigEntry, entity_registry: er.EntityRegistry
) -> None:
    """Duplicate or low-value points are registered but disabled."""
    entry = entity_registry.async_get("sensor.pvi_10_0_outd_energy_ac_produced_vendor_lifetime")
    assert entry is not None
    assert entry.disabled_by is er.RegistryEntryDisabler.INTEGRATION
    entry = entity_registry.async_get("sensor.pvi_10_0_outd_status_operating_vendor")
    assert entry is not None
    assert entry.disabled_by is er.RegistryEntryDisabler.INTEGRATION


async def test_point_appearing_later_gets_a_sensor(
    hass: HomeAssistant,
    init_integration: MockConfigEntry,
    mock_unit: MockModbusUnit,
    freezer: FrozenDateTimeFactory,
) -> None:
    """A point that starts reporting after setup gets its sensor on the next poll."""
    assert hass.states.get("sensor.pvi_10_0_outd_voltage_dc") is None
    # M103 header at 70, DCV at offset 29, DCV_SF -1: 350.0 V
    mock_unit.holding[70 + 29] = 3500

    freezer.tick(timedelta(seconds=31))
    async_fire_time_changed(hass)
    await hass.async_block_till_done()

    assert (state := hass.states.get("sensor.pvi_10_0_outd_voltage_dc")) is not None
    assert state.state == "350.0"


async def test_every_sensor_unavailable_while_offline(
    hass: HomeAssistant,
    init_integration: MockConfigEntry,
    mock_unit: MockModbusUnit,
    freezer: FrozenDateTimeFactory,
) -> None:
    """When the inverter sleeps, every reading goes unavailable, counters included."""
    mock_unit.fail_requests(ModbusConnectionError("asleep"))
    freezer.tick(timedelta(seconds=31))
    async_fire_time_changed(hass)
    await hass.async_block_till_done()

    assert hass.states.get("sensor.pvi_10_0_outd_power_ac").state == STATE_UNAVAILABLE
    assert (
        hass.states.get("sensor.pvi_10_0_outd_energy_ac_produced_lifetime").state
        == STATE_UNAVAILABLE
    )
    assert (
        hass.states.get("sensor.pvi_10_0_outd_energy_ac_produced_today").state == STATE_UNAVAILABLE
    )

    mock_unit.fail_requests(None)
    freezer.tick(timedelta(seconds=31))
    async_fire_time_changed(hass)
    await hass.async_block_till_done()
    assert hass.states.get("sensor.pvi_10_0_outd_power_ac").state == "1500"


async def _restart_with_energy_unreported(
    hass: HomeAssistant, entry: MockConfigEntry, mock_unit: MockModbusUnit
) -> None:
    """Reload the entry with the inverter not yet reporting its total energy."""
    assert await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()
    mock_unit.holding.clear()
    mock_unit.holding.update(default_register_map(inverter=_inverter_with_energy(0)))


async def test_energy_sensor_not_yet_reported_is_unknown(
    hass: HomeAssistant, init_integration: MockConfigEntry, mock_unit: MockModbusUnit
) -> None:
    """A counter registered before but not reported after a restart exists and is unknown."""
    await _restart_with_energy_unreported(hass, init_integration, mock_unit)
    await hass.config_entries.async_setup(init_integration.entry_id)
    await hass.async_block_till_done()

    assert (
        hass.states.get("sensor.pvi_10_0_outd_energy_ac_produced_lifetime").state == STATE_UNKNOWN
    )


def _inverter_with_energy(energy_total: int) -> InverterSpec:
    return replace(INVERTER_SPEC, energy_total=energy_total)
