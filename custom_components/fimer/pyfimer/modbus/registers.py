"""Classic Modbus register access, for what SunSpec models do not cover.

:class:`ModbusRegisters` wraps a ``modbus_connection.ModbusUnit`` with raw
and typed reads and writes at absolute addresses: holding and input
registers, coils and discrete inputs, plus 16-bit, 32-bit, float32 and
string helpers. It works next to the SunSpec components on the same unit,
so a device that serves a SunSpec map and a vendor-specific area outside
it, or no SunSpec map at all, is reachable through one object.

Reads wider than the device tolerates are split into chunks; writes wider
than one Modbus request are split as well. Transport failures surface as
``modbus_connection.ModbusError`` subclasses, a value that does not fit its
registers as ``OverflowError``, and an address outside the Modbus range as
``ValueError``.
"""

from __future__ import annotations

from collections.abc import Sequence

from modbus_connection import ModbusUnit, WordOrder
from modbus_connection.decode import (
    decode_float32,
    decode_int16,
    decode_int32,
    decode_string,
    decode_uint16,
    decode_uint32,
)
from modbus_connection.encode import (
    encode_float32,
    encode_int16,
    encode_int32,
    encode_string,
    encode_uint16,
    encode_uint32,
)

from .sunspec import MAX_READ_SPAN

MODBUS_MAX_READ = 125
"""Registers one read request may return."""
MODBUS_MAX_WRITE = 123
"""Registers one write request may carry."""
MAX_ADDRESS = 0xFFFF


class ModbusRegisters:
    """Raw and typed reads and writes on one Modbus unit."""

    def __init__(
        self,
        unit: ModbusUnit,
        *,
        max_read: int = MAX_READ_SPAN,
        word_order: WordOrder = "big",
    ) -> None:
        """Wrap a unit, chunking reads at ``max_read`` registers.

        ``word_order`` is the default for the 32-bit helpers; SunSpec and
        most inverters send the high word first ("big").
        """
        if not 1 <= max_read <= MODBUS_MAX_READ:
            raise ValueError(f"max_read must be 1..{MODBUS_MAX_READ}, got {max_read}")
        self._unit = unit
        self._max_read = max_read
        self._word_order: WordOrder = word_order

    @property
    def unit(self) -> ModbusUnit:
        """The unit the registers are read from."""
        return self._unit

    # Raw access

    async def read_holding(self, address: int, count: int = 1) -> list[int]:
        """Read ``count`` holding registers from ``address``."""
        return await self._read(address, count, input_registers=False)

    async def read_input(self, address: int, count: int = 1) -> list[int]:
        """Read ``count`` input registers from ``address``."""
        return await self._read(address, count, input_registers=True)

    async def read_coils(self, address: int, count: int = 1) -> list[bool]:
        """Read ``count`` coils from ``address``."""
        _check_range(address, count)
        return await self._unit.read_coils(address, count)

    async def read_discrete_inputs(self, address: int, count: int = 1) -> list[bool]:
        """Read ``count`` discrete inputs from ``address``."""
        _check_range(address, count)
        return await self._unit.read_discrete_inputs(address, count)

    async def read_block(
        self, address: int, count: int, *, input_registers: bool = False
    ) -> dict[int, int]:
        """Read ``count`` registers from ``address`` keyed by address.

        The result is the layout ``MockModbusUnit.load_raw()`` accepts under
        ``"holding"`` or ``"input"``, so a capture can back a test.
        """
        words = await self._read(address, count, input_registers=input_registers)
        return dict(zip(range(address, address + count), words, strict=True))

    async def write_register(self, address: int, value: int) -> None:
        """Write one holding register."""
        _check_range(address, 1)
        await self._unit.write_register(address, encode_uint16(value)[0])

    async def write_registers(self, address: int, values: Sequence[int]) -> None:
        """Write consecutive holding registers, in as many requests as needed."""
        _check_range(address, len(values))
        words = [encode_uint16(value)[0] for value in values]
        for start in range(0, len(words), MODBUS_MAX_WRITE):
            chunk = words[start : start + MODBUS_MAX_WRITE]
            await self._unit.write_registers(address + start, chunk)

    async def write_coil(self, address: int, value: bool) -> None:
        """Write one coil."""
        _check_range(address, 1)
        await self._unit.write_coil(address, value)

    async def write_coils(self, address: int, values: Sequence[bool]) -> None:
        """Write consecutive coils."""
        _check_range(address, len(values))
        await self._unit.write_coils(address, list(values))

    # Typed reads

    async def read_uint16(self, address: int, *, input_registers: bool = False) -> int:
        """Read an unsigned 16-bit integer."""
        return decode_uint16(await self._read(address, 1, input_registers=input_registers))

    async def read_int16(self, address: int, *, input_registers: bool = False) -> int:
        """Read a signed 16-bit integer."""
        return decode_int16(await self._read(address, 1, input_registers=input_registers))

    async def read_uint32(
        self, address: int, *, input_registers: bool = False, word_order: WordOrder | None = None
    ) -> int:
        """Read an unsigned 32-bit integer from two registers."""
        words = await self._read(address, 2, input_registers=input_registers)
        return decode_uint32(words, word_order=word_order or self._word_order)

    async def read_int32(
        self, address: int, *, input_registers: bool = False, word_order: WordOrder | None = None
    ) -> int:
        """Read a signed 32-bit integer from two registers."""
        words = await self._read(address, 2, input_registers=input_registers)
        return decode_int32(words, word_order=word_order or self._word_order)

    async def read_float32(
        self, address: int, *, input_registers: bool = False, word_order: WordOrder | None = None
    ) -> float:
        """Read an IEEE-754 single-precision float from two registers."""
        words = await self._read(address, 2, input_registers=input_registers)
        return decode_float32(words, word_order=word_order or self._word_order)

    async def read_string(self, address: int, length: int, *, input_registers: bool = False) -> str:
        """Read a null-padded ASCII string spanning ``length`` registers."""
        words = await self._read(address, length, input_registers=input_registers)
        return decode_string(words).strip("\x00 ")

    # Typed writes

    async def write_uint16(self, address: int, value: int) -> None:
        """Write an unsigned 16-bit integer."""
        await self.write_registers(address, encode_uint16(value))

    async def write_int16(self, address: int, value: int) -> None:
        """Write a signed 16-bit integer."""
        await self.write_registers(address, encode_int16(value))

    async def write_uint32(
        self, address: int, value: int, *, word_order: WordOrder | None = None
    ) -> None:
        """Write an unsigned 32-bit integer into two registers."""
        await self.write_registers(
            address, encode_uint32(value, word_order=word_order or self._word_order)
        )

    async def write_int32(
        self, address: int, value: int, *, word_order: WordOrder | None = None
    ) -> None:
        """Write a signed 32-bit integer into two registers."""
        await self.write_registers(
            address, encode_int32(value, word_order=word_order or self._word_order)
        )

    async def write_float32(
        self, address: int, value: float, *, word_order: WordOrder | None = None
    ) -> None:
        """Write an IEEE-754 single-precision float into two registers."""
        await self.write_registers(
            address, encode_float32(value, word_order=word_order or self._word_order)
        )

    async def write_string(self, address: int, value: str, *, length: int) -> None:
        """Write a null-padded ASCII string into ``length`` registers."""
        await self.write_registers(address, encode_string(value, length=length))

    async def _read(self, address: int, count: int, *, input_registers: bool) -> list[int]:
        _check_range(address, count)
        read = (
            self._unit.read_input_registers
            if input_registers
            else self._unit.read_holding_registers
        )
        words: list[int] = []
        for start in range(address, address + count, self._max_read):
            size = min(self._max_read, address + count - start)
            words += await read(start, size)
        return words


def _check_range(address: int, count: int) -> None:
    if count < 1:
        raise ValueError(f"count must be at least 1, got {count}")
    if not 0 <= address <= MAX_ADDRESS or address + count - 1 > MAX_ADDRESS:
        raise ValueError(
            f"address range {address}..{address + count - 1} is outside 0..{MAX_ADDRESS}"
        )
