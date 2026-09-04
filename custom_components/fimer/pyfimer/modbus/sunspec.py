"""SunSpec constants of the FIMER (ABB / Power-One) register maps."""

from __future__ import annotations

from typing import Final

from modbus_connection.model.sunspec import (
    SunSpecComponent,
    SunSpecError,
    SunSpecMapShiftError,
    SunSpecModel,
    SunSpecModels,
    scan,
)

__all__ = [
    "ABB_VENDOR_MODEL_ID",
    "ABB_VENDOR_MODEL_LENGTH",
    "BASE_ADDRESS_DATALOGGER",
    "BASE_ADDRESS_NATIVE",
    "COMMON_MODEL_ID",
    "DEFAULT_UNIT_ID_DATALOGGER",
    "DEFAULT_UNIT_ID_NATIVE",
    "INVERTER_MODEL_IDS",
    "MAX_READ_SPAN",
    "MPPT_MODEL_ID",
    "SunSpecComponent",
    "SunSpecError",
    "SunSpecMapShiftError",
    "SunSpecModel",
    "SunSpecModels",
    "scan",
]

BASE_ADDRESS_DATALOGGER: Final = 0
"""Where a VSN300 / VSN700 datalogger card places the SunSpec marker."""

BASE_ADDRESS_NATIVE: Final = 40000
"""Where natively Modbus inverters (REACT2, TRIO with PICS) place the marker."""

DEFAULT_UNIT_ID_DATALOGGER: Final = 2
"""The unit ID a VSN card forwards to the inverter (some firmwares use 247)."""

DEFAULT_UNIT_ID_NATIVE: Final = 1

COMMON_MODEL_ID: Final = 1
INVERTER_MODEL_IDS: Final = frozenset({101, 102, 103})
MPPT_MODEL_ID: Final = 160
ABB_VENDOR_MODEL_ID: Final = 64061
ABB_VENDOR_MODEL_LENGTH: Final = 124
"""Length of the vendor model in the 2013 Power-One map this library implements."""

MAX_READ_SPAN: Final = 64
"""Registers per read. Older PVI firmware rejects the Modbus maximum of 125."""
