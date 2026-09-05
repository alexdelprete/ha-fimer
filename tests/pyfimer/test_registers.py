"""Tests for classic register access on the modbus-connection mock."""

from __future__ import annotations

from modbus_connection.mock import MockModbusConnection, MockModbusUnit, WriteEvent
import pytest

from custom_components.fimer.pyfimer.modbus import ModbusRegisters
from custom_components.fimer.pyfimer.modbus.registers import MODBUS_MAX_WRITE


@pytest.fixture
def unit() -> MockModbusUnit:
    return MockModbusConnection().for_unit(1)


@pytest.fixture
def registers(unit: MockModbusUnit) -> ModbusRegisters:
    return ModbusRegisters(unit, max_read=8)


async def test_raw_reads_are_chunked(unit: MockModbusUnit, registers: ModbusRegisters) -> None:
    unit.holding.update({100 + offset: offset for offset in range(20)})
    assert await registers.read_holding(100, 20) == list(range(20))
    assert [(event.address, event.count) for event in unit.read_events] == [
        (100, 8),
        (108, 8),
        (116, 4),
    ]
    assert await registers.read_holding(105) == [5]
    assert await registers.read_block(110, 3) == {110: 10, 111: 11, 112: 12}
    assert registers.unit is unit


async def test_input_registers_coils_and_discrete_inputs(
    unit: MockModbusUnit, registers: ModbusRegisters
) -> None:
    unit.input.update({7: 1234})
    unit.coils.update({3: True, 4: False})
    unit.discrete_inputs.update({9: True})
    assert await registers.read_input(7) == [1234]
    assert await registers.read_uint16(7, input_registers=True) == 1234
    assert await registers.read_block(7, 1, input_registers=True) == {7: 1234}
    assert await registers.read_coils(3, 2) == [True, False]
    assert await registers.read_discrete_inputs(9) == [True]

    await registers.write_coil(3, False)
    await registers.write_coils(10, [True, True])
    assert unit.coils[3] is False
    assert unit.coils[10] is True and unit.coils[11] is True


async def test_typed_reads(unit: MockModbusUnit, registers: ModbusRegisters) -> None:
    unit.holding.update(
        {
            0: 0xFFFE,  # int16 -2
            1: 0x0001,
            2: 0x0000,  # uint32 65536 big / 1 little
            3: 0x3F80,
            4: 0x0000,  # float32 1.0
            5: 0x4142,
            6: 0x4300,  # "ABC"
            7: 0xFFFF,
            8: 0xFFFF,  # int32 -1
        }
    )
    assert await registers.read_int16(0) == -2
    assert await registers.read_uint16(0) == 0xFFFE
    assert await registers.read_uint32(1) == 65536
    assert await registers.read_uint32(1, word_order="little") == 1
    assert await registers.read_float32(3) == 1.0
    assert await registers.read_string(5, 2) == "ABC"
    assert await registers.read_int32(7) == -1

    little = ModbusRegisters(unit, word_order="little")
    assert await little.read_uint32(1) == 1
    assert await little.read_int32(7) == -1


async def test_typed_writes(unit: MockModbusUnit, registers: ModbusRegisters) -> None:
    await registers.write_register(10, 42)
    await registers.write_uint16(11, 65535)
    await registers.write_int16(12, -2)
    await registers.write_uint32(13, 65536)
    await registers.write_int32(15, -1)
    await registers.write_float32(17, 1.0)
    await registers.write_string(19, "ABC", length=2)
    await registers.write_uint32(21, 1, word_order="little")
    assert unit.holding[10] == 42
    assert unit.holding[11] == 0xFFFF
    assert unit.holding[12] == 0xFFFE
    assert (unit.holding[13], unit.holding[14]) == (1, 0)
    assert (unit.holding[15], unit.holding[16]) == (0xFFFF, 0xFFFF)
    assert (unit.holding[17], unit.holding[18]) == (0x3F80, 0)
    assert (unit.holding[19], unit.holding[20]) == (0x4142, 0x4300)
    assert (unit.holding[21], unit.holding[22]) == (1, 0)


async def test_wide_writes_are_split(unit: MockModbusUnit, registers: ModbusRegisters) -> None:
    writes: list[WriteEvent] = []
    unit.on_write(writes.append)
    values = list(range(MODBUS_MAX_WRITE + 5))
    await registers.write_registers(1000, values)
    assert [unit.holding[1000 + offset] for offset in range(len(values))] == values
    assert [(event.address, len(event.values)) for event in writes] == [
        (1000, MODBUS_MAX_WRITE),
        (1000 + MODBUS_MAX_WRITE, 5),
    ]


async def test_invalid_arguments(unit: MockModbusUnit, registers: ModbusRegisters) -> None:
    with pytest.raises(ValueError, match="max_read"):
        ModbusRegisters(unit, max_read=0)
    with pytest.raises(ValueError, match="max_read"):
        ModbusRegisters(unit, max_read=126)
    with pytest.raises(ValueError, match="count"):
        await registers.read_holding(0, 0)
    with pytest.raises(ValueError, match="outside"):
        await registers.read_holding(65535, 2)
    with pytest.raises(ValueError, match="outside"):
        await registers.read_coils(70000)
    with pytest.raises(OverflowError):
        await registers.write_register(0, 70000)
    with pytest.raises(OverflowError):
        await registers.write_int16(0, 40000)
