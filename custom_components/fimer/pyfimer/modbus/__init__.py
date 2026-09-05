"""Modbus TCP (SunSpec) client for FIMER (ABB / Power-One) inverters.

Consumes a ``modbus_connection.ModbusUnit``; the connection lifecycle stays
with the caller (in Home Assistant, the core ``modbus`` integration).

:class:`FimerModbusInverter` reads the SunSpec models and writes their
writable points; :class:`ModbusRegisters` reads and writes registers, coils
and typed values at absolute addresses for anything outside SunSpec.
"""

from .inverter import DeviceIdentity, FimerModbusInverter
from .models import Common, Event1, Inverter, Mppt, MpptInput, MpptOperatingState, OperatingState
from .registers import ModbusRegisters
from .sunspec import (
    ABB_VENDOR_MODEL_ID,
    BASE_ADDRESS_DATALOGGER,
    BASE_ADDRESS_NATIVE,
    COMMON_MODEL_ID,
    DEFAULT_UNIT_ID_DATALOGGER,
    DEFAULT_UNIT_ID_NATIVE,
    INVERTER_MODEL_IDS,
    MPPT_MODEL_ID,
    SunSpecError,
    SunSpecMapShiftError,
    SunSpecModel,
)
from .vendor import AbbVendor, DevicePresence

__all__ = [
    "ABB_VENDOR_MODEL_ID",
    "BASE_ADDRESS_DATALOGGER",
    "BASE_ADDRESS_NATIVE",
    "COMMON_MODEL_ID",
    "DEFAULT_UNIT_ID_DATALOGGER",
    "DEFAULT_UNIT_ID_NATIVE",
    "INVERTER_MODEL_IDS",
    "MPPT_MODEL_ID",
    "AbbVendor",
    "Common",
    "DeviceIdentity",
    "DevicePresence",
    "Event1",
    "FimerModbusInverter",
    "Inverter",
    "ModbusRegisters",
    "Mppt",
    "MpptInput",
    "MpptOperatingState",
    "OperatingState",
    "SunSpecError",
    "SunSpecMapShiftError",
    "SunSpecModel",
]
