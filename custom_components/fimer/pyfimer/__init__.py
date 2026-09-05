"""Device library for FIMER (ABB / Power-One) PV inverters.

One point vocabulary, two transports. Every client in this package reports
readings as a flat mapping keyed by the SunSpec normalized point names in
:mod:`pyfimer.points`, so an integration can merge sources without a
translation layer:

- :mod:`pyfimer.modbus` reads SunSpec models over Modbus TCP through a
  ``modbus_connection.ModbusUnit`` handed in by the caller. It never opens a
  connection itself.
- ``pyfimer.rest`` (planned) reads the VSN300/VSN700 datalogger REST API
  through an ``aiohttp.ClientSession`` handed in by the caller.

The Aurora protocol state tables shared by both transports live in
:mod:`pyfimer.aurora`.
"""

from .aurora import (
    ALARM_CODES,
    AURORA_EPOCH_OFFSET,
    DCDC_STATES,
    GLOBAL_STATES,
    INVERTER_MODELS,
    INVERTER_STATES,
    decode_alarms,
    inverter_model_from_options,
)
from .exceptions import (
    FimerError,
    FimerNotDiscoveredError,
    FimerUnsupportedDeviceError,
    FimerWriteError,
)
from .points import POINTS, POINTS_BY_NAME, Point, PointKind

__all__ = [
    "ALARM_CODES",
    "AURORA_EPOCH_OFFSET",
    "DCDC_STATES",
    "GLOBAL_STATES",
    "INVERTER_MODELS",
    "INVERTER_STATES",
    "POINTS",
    "POINTS_BY_NAME",
    "FimerError",
    "FimerNotDiscoveredError",
    "FimerUnsupportedDeviceError",
    "FimerWriteError",
    "Point",
    "PointKind",
    "decode_alarms",
    "inverter_model_from_options",
]
