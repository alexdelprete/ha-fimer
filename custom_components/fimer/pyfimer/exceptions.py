"""Exceptions raised by pyfimer.

Transport errors are not wrapped: the Modbus client lets
``modbus_connection.ModbusError`` and ``SunSpecError`` propagate so callers
can tell a lost link from a shifted register map.
"""


class FimerError(Exception):
    """Base class for errors raised by pyfimer itself."""


class FimerUnsupportedDeviceError(FimerError):
    """The device answers but exposes no supported inverter model."""


class FimerNotDiscoveredError(FimerError):
    """A read was attempted before the device was discovered."""


class FimerWriteError(FimerError):
    """A write was accepted by the device but the readback does not show it."""
