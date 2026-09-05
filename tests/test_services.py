"""Tests for the fimer.* actions."""

from __future__ import annotations

from modbus_connection import ModbusConnectionError
from modbus_connection.mock import MockModbusUnit
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.fimer.const import CONF_USE_MODBUS, DOMAIN
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError

from .conftest import SERIAL_NUMBER


async def _call(hass: HomeAssistant, service: str, data: dict, *, response: bool = False):
    return await hass.services.async_call(
        DOMAIN, service, data, blocking=True, return_response=response
    )


async def test_actions_are_registered(
    hass: HomeAssistant, init_integration: MockConfigEntry
) -> None:
    for service in (
        "read_registers",
        "write_registers",
        "write_point",
        "set_power_limit",
        "get_readings",
    ):
        assert hass.services.has_service(DOMAIN, service)


async def test_read_registers(
    hass: HomeAssistant, init_integration: MockConfigEntry, mock_unit: MockModbusUnit
) -> None:
    entry = {"config_entry": init_integration.entry_id}
    result = await _call(
        hass, "read_registers", {**entry, "address": 70, "count": 2}, response=True
    )
    assert result == {
        "address": 70,
        "count": 2,
        "register_type": "holding",
        "registers": [103, 50],
        "value": None,
    }

    result = await _call(
        hass, "read_registers", {**entry, "address": 237, "data_type": "uint16"}, response=True
    )
    assert result["value"] == 100

    mock_unit.holding.update({1000: 0x3F80, 1001: 0})
    result = await _call(
        hass, "read_registers", {**entry, "address": 1000, "data_type": "float32"}, response=True
    )
    assert result["value"] == 1.0
    result = await _call(
        hass,
        "read_registers",
        {**entry, "address": 1000, "data_type": "uint32", "word_order": "little"},
        response=True,
    )
    assert result["value"] == 0x3F80

    mock_unit.holding.update({2000: 0xFFFE, 2001: 0xFFFF, 2002: 0xFFFF})
    assert (
        await _call(
            hass, "read_registers", {**entry, "address": 2000, "data_type": "int16"}, response=True
        )
    )["value"] == -2
    assert (
        await _call(
            hass, "read_registers", {**entry, "address": 2001, "data_type": "int32"}, response=True
        )
    )["value"] == -1
    # the serial number string in the common model
    result = await _call(
        hass,
        "read_registers",
        {**entry, "address": 52, "count": 16, "data_type": "string"},
        response=True,
    )
    assert result["value"] == SERIAL_NUMBER

    mock_unit.input.update({7: 42})
    result = await _call(
        hass,
        "read_registers",
        {**entry, "address": 7, "register_type": "input", "data_type": "uint16"},
        response=True,
    )
    assert result["value"] == 42

    mock_unit.fail_requests(ModbusConnectionError("asleep"))
    with pytest.raises(HomeAssistantError, match="asleep"):
        await _call(hass, "read_registers", {**entry, "address": 70}, response=True)


async def test_write_registers(
    hass: HomeAssistant, init_integration: MockConfigEntry, mock_unit: MockModbusUnit
) -> None:
    entry = {"config_entry": init_integration.entry_id}
    await _call(hass, "write_registers", {**entry, "address": 3000, "value": 80})
    assert mock_unit.holding[3000] == 80
    await _call(
        hass, "write_registers", {**entry, "address": 3001, "value": -2, "data_type": "int16"}
    )
    assert mock_unit.holding[3001] == 0xFFFE
    await _call(
        hass, "write_registers", {**entry, "address": 3002, "value": 1.0, "data_type": "float32"}
    )
    assert (mock_unit.holding[3002], mock_unit.holding[3003]) == (0x3F80, 0)
    await _call(
        hass,
        "write_registers",
        {**entry, "address": 3004, "value": 65536, "data_type": "uint32", "word_order": "little"},
    )
    assert (mock_unit.holding[3004], mock_unit.holding[3005]) == (0, 1)
    await _call(
        hass, "write_registers", {**entry, "address": 3006, "value": -1, "data_type": "int32"}
    )
    assert (mock_unit.holding[3006], mock_unit.holding[3007]) == (0xFFFF, 0xFFFF)
    await _call(
        hass, "write_registers", {**entry, "address": 3010, "value": "AB", "data_type": "string"}
    )
    assert mock_unit.holding[3010] == 0x4142
    await _call(
        hass,
        "write_registers",
        {**entry, "address": 3020, "value": "A", "data_type": "string", "count": 2},
    )
    assert (mock_unit.holding[3020], mock_unit.holding[3021]) == (0x4100, 0)
    await _call(hass, "write_registers", {**entry, "address": 3030, "values": [1, 2, 3]})
    assert [mock_unit.holding[3030 + i] for i in range(3)] == [1, 2, 3]

    with pytest.raises(ServiceValidationError):
        await _call(hass, "write_registers", {**entry, "address": 3040, "value": 70000})
    with pytest.raises(ServiceValidationError):
        await _call(hass, "write_registers", {**entry, "address": 3040})
    mock_unit.fail_requests(ModbusConnectionError("asleep"))
    with pytest.raises(HomeAssistantError, match="asleep"):
        await _call(hass, "write_registers", {**entry, "address": 3040, "value": 1})


async def test_write_point_and_power_limit(
    hass: HomeAssistant, init_integration: MockConfigEntry, mock_unit: MockModbusUnit
) -> None:
    entry = {"config_entry": init_integration.entry_id}
    await _call(hass, "write_point", {**entry, "point": "WMaxLimPct", "value": 60})
    await hass.async_block_till_done()
    assert mock_unit.holding[232 + 5] == 60
    with pytest.raises(ServiceValidationError, match="W"):
        await _call(hass, "write_point", {**entry, "point": "W", "value": 1})
    with pytest.raises(ServiceValidationError):
        await _call(hass, "write_point", {**entry, "point": "NoSuchPoint", "value": 1})

    await _call(hass, "set_power_limit", {**entry, "percent": 40, "enabled": True})
    await hass.async_block_till_done()
    assert (mock_unit.holding[232 + 5], mock_unit.holding[232 + 9]) == (40, 1)
    await _call(hass, "set_power_limit", {**entry, "enabled": False})
    assert mock_unit.holding[232 + 9] == 0
    with pytest.raises(ServiceValidationError):
        await _call(hass, "set_power_limit", {**entry, "percent": 101})
    mock_unit.fail_requests(ModbusConnectionError("asleep"))
    with pytest.raises(HomeAssistantError, match="asleep"):
        await _call(hass, "set_power_limit", {**entry, "percent": 40})


async def test_get_readings(hass: HomeAssistant, init_integration: MockConfigEntry) -> None:
    entry = {"config_entry": init_integration.entry_id}
    result = await _call(hass, "get_readings", entry, response=True)
    inverter = result["devices"][SERIAL_NUMBER]
    assert inverter["type"] == "inverter"
    assert inverter["available"] is True
    assert inverter["values"]["W"] == 1500
    assert inverter["values"]["St"] == 4
    assert inverter["values"]["Alarms"] == ["Sun Low", "Grid OV", "Energy data reset"]
    assert "DCV" not in inverter["values"]

    result = await _call(hass, "get_readings", {**entry, "device": SERIAL_NUMBER}, response=True)
    assert list(result["devices"]) == [SERIAL_NUMBER]
    with pytest.raises(ServiceValidationError):
        await _call(hass, "get_readings", {**entry, "device": "nope"}, response=True)


async def test_validation_errors(
    hass: HomeAssistant, init_integration: MockConfigEntry, mock_config_entry: MockConfigEntry
) -> None:
    with pytest.raises(ServiceValidationError):
        await _call(hass, "get_readings", {"config_entry": "missing"}, response=True)
    assert await hass.config_entries.async_unload(init_integration.entry_id)
    await hass.async_block_till_done()
    with pytest.raises(ServiceValidationError):
        await _call(
            hass, "get_readings", {"config_entry": init_integration.entry_id}, response=True
        )


async def test_modbus_actions_need_modbus(
    hass: HomeAssistant, serve_rest: object, mock_config_entry: MockConfigEntry
) -> None:
    from .conftest import fake_vsn300, rest_entry  # noqa: PLC0415

    host = await serve_rest(fake_vsn300())  # type: ignore[operator]
    entry = rest_entry(host, use_modbus=False, title="PVI-10.0-OUTD", unique_id="YYYYYY-3G82-XXXX")
    entry.add_to_hass(hass)
    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    assert entry.data[CONF_USE_MODBUS] is False
    with pytest.raises(ServiceValidationError):
        await _call(
            hass, "read_registers", {"config_entry": entry.entry_id, "address": 0}, response=True
        )
    result = await _call(hass, "get_readings", {"config_entry": entry.entry_id}, response=True)
    assert "YYYYYY-3G82-XXXX" in result["devices"]


async def test_rediscover(
    hass: HomeAssistant, init_integration: MockConfigEntry, mock_unit: MockModbusUnit
) -> None:
    from .conftest import default_register_map  # noqa: PLC0415

    entry = {"config_entry": init_integration.entry_id}
    result = await _call(hass, "rediscover", entry, response=True)
    assert result["modbus"]["model_chain"] == [1, 103, 160, 120, 121, 123, 64061]
    assert result["modbus"]["phases"] == 3
    assert result["reloaded"] is False
    assert "rest" not in result

    # the datalogger now serves a single-phase model at the same address
    mock_unit.holding.clear()
    mock_unit.holding.update(default_register_map(three_phase=False))
    result = await _call(hass, "rediscover", entry, response=True)
    assert result["modbus"]["phases"] == 1
    assert init_integration.runtime_data.coordinator.data["W"] == 1500

    mock_unit.fail_requests(ModbusConnectionError("asleep"))
    with pytest.raises(HomeAssistantError, match="asleep"):
        await _call(hass, "rediscover", entry, response=True)


async def test_rediscover_reloads_on_new_rest_devices(
    hass: HomeAssistant, serve_rest: object, mock_config_entry: MockConfigEntry
) -> None:
    from .conftest import fake_vsn700, rest_entry  # noqa: PLC0415

    fake = fake_vsn700()
    battery = fake.livedata.pop("140821-3P72-1319")  # start with one battery
    host = await serve_rest(fake)  # type: ignore[operator]
    entry = rest_entry(host, use_modbus=False, title="REACT2-5.0-TL", unique_id="140842-3P81-2619")
    entry.add_to_hass(hass)
    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    assert len(entry.runtime_data.devices) == 4

    fake.livedata["140821-3P72-1319"] = battery
    result = await _call(hass, "rediscover", {"config_entry": entry.entry_id}, response=True)
    assert result["reloaded"] is True
    assert "140821-3P72-1319" in result["rest"]["devices"]
    await hass.async_block_till_done(wait_background_tasks=True)
    assert len(entry.runtime_data.devices) == 5
