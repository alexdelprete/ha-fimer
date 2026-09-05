"""Tests for reading the inverter over Modbus and the datalogger REST API together."""

from __future__ import annotations

from datetime import timedelta
from typing import Any

from freezegun.api import FrozenDateTimeFactory
from modbus_connection import ModbusConnectionError
from modbus_connection.mock import MockModbusUnit
from pytest_homeassistant_custom_component.common import MockConfigEntry, async_fire_time_changed

from custom_components.fimer.const import DOMAIN
from homeassistant.config_entries import ConfigEntryState
from homeassistant.const import STATE_UNAVAILABLE
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr, entity_registry as er

from .conftest import SERIAL_NUMBER, fake_vsn300, fake_vsn700, rest_entry


async def _setup(hass: HomeAssistant, entry: MockConfigEntry) -> None:
    entry.add_to_hass(hass)
    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()


async def test_both_sources_on_a_vsn300(
    hass: HomeAssistant,
    serve_rest: Any,
    device_registry: dr.DeviceRegistry,
    entity_registry: er.EntityRegistry,
) -> None:
    """Modbus and REST feed one inverter device; the card becomes its own device."""
    host = await serve_rest(fake_vsn300())
    entry = rest_entry(host, use_modbus=True, title="PVI-10.0-OUTD", unique_id=SERIAL_NUMBER)
    await _setup(hass, entry)
    assert entry.state is ConfigEntryState.LOADED
    runtime = entry.runtime_data
    assert runtime.rest_logger is not None and runtime.rest_logger.discovered
    assert [device.device_type for device in runtime.devices] == ["inverter", "datalogger"]

    inverter = device_registry.async_get_device_by_identifier(
        (DOMAIN, SERIAL_NUMBER), entry.entry_id
    )
    logger = device_registry.async_get_device_by_identifier(
        (DOMAIN, "LLLLLL-3N16-BBBB"), entry.entry_id
    )
    assert inverter is not None and logger is not None
    assert inverter.via_device_id == logger.id
    assert logger.model == "WIFI LOGGER CARD"
    assert logger.sw_version == "2.0.1"
    assert logger.configuration_url == "http://ABB-YYYYYY-3G82-XXXX.local"

    # Modbus wins for a point both sources report
    assert hass.states.get("sensor.pvi_10_0_outd_ac_power").state == "1500"
    # REST-only points on the inverter and on the datalogger
    assert hass.states.get("sensor.pvi_10_0_outd_power_peak_lifetime") is not None
    assert hass.states.get("sensor.pvi_10_0_outd_voltage_dc_bulk_capacitor") is not None
    assert hass.states.get("sensor.vsn300_wifi_link_quality").state == "100"
    assert hass.states.get("sensor.vsn300_firmware_version").state == "2.0.1"
    energy_today = hass.states.get("sensor.pvi_10_0_outd_energy_today")
    assert energy_today is not None  # from Modbus vendor model or REST, whichever reports it


async def test_rest_only_vsn700(
    hass: HomeAssistant, serve_rest: Any, device_registry: dr.DeviceRegistry
) -> None:
    """A VSN700 with a REACT2, two batteries and a meter, REST only."""
    host = await serve_rest(fake_vsn700())
    entry = rest_entry(host, use_modbus=False, title="REACT2-5.0-TL", unique_id="140842-3P81-2619")
    await _setup(hass, entry)
    assert entry.state is ConfigEntryState.LOADED
    assert entry.runtime_data.coordinator is None
    types = sorted(device.device_type for device in entry.runtime_data.devices)
    assert types == ["battery", "battery", "datalogger", "inverter", "meter"]

    inverter = device_registry.async_get_device_by_identifier(
        (DOMAIN, "140842-3P81-2619"), entry.entry_id
    )
    assert inverter is not None
    assert inverter.model == "REACT2-5.0-TL"
    battery = device_registry.async_get_device_by_identifier(
        (DOMAIN, "113049-3P72-0221"), entry.entry_id
    )
    assert battery is not None and battery.via_device_id is not None

    assert hass.states.get("sensor.react2_5_0_tl_ac_power") is not None
    assert hass.states.get("sensor.react2_5_0_tl_global_state").state == "Wait Sun / Grid"
    assert hass.states.get("sensor.battery_113049_3p72_0221_state_of_charge") is not None
    assert hass.states.get("sensor.meter_120730_3n52_3019_power_ac_meter_total") is not None


async def test_rest_outage_keeps_modbus_points(
    hass: HomeAssistant, serve_rest: Any, freezer: FrozenDateTimeFactory
) -> None:
    """When the card stops answering, REST-only sensors go unavailable, Modbus ones stay."""
    fake = fake_vsn300()
    host = await serve_rest(fake)
    entry = rest_entry(host, use_modbus=True, title="PVI-10.0-OUTD", unique_id=SERIAL_NUMBER)
    await _setup(hass, entry)
    assert hass.states.get("sensor.vsn300_wifi_link_quality").state == "100"

    fake.livedata_status = 503
    freezer.tick(timedelta(seconds=31))
    async_fire_time_changed(hass)
    # the REST poll suspends on the HTTP request, so it runs as a background task
    await hass.async_block_till_done(wait_background_tasks=True)
    assert hass.states.get("sensor.vsn300_wifi_link_quality").state == STATE_UNAVAILABLE
    assert hass.states.get("sensor.pvi_10_0_outd_ac_power").state == "1500"


async def test_modbus_outage_falls_back_to_rest(
    hass: HomeAssistant, serve_rest: Any, mock_unit: MockModbusUnit, freezer: FrozenDateTimeFactory
) -> None:
    """When Modbus fails, a point REST also reports keeps its REST value."""
    host = await serve_rest(fake_vsn300())
    entry = rest_entry(host, use_modbus=True, title="PVI-10.0-OUTD", unique_id=SERIAL_NUMBER)
    await _setup(hass, entry)
    assert hass.states.get("sensor.pvi_10_0_outd_ac_power").state == "1500"

    mock_unit.fail_requests(ModbusConnectionError("asleep"))
    freezer.tick(timedelta(seconds=31))
    async_fire_time_changed(hass)
    await hass.async_block_till_done(wait_background_tasks=True)
    state = hass.states.get("sensor.pvi_10_0_outd_ac_power")
    assert state.state != STATE_UNAVAILABLE
    assert float(state.state) != 1500  # the REST reading
