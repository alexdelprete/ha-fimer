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


class FimerConnectionError(FimerError):
    """The device could not be reached or did not answer as expected."""


class FimerAuthenticationError(FimerError):
    """The device rejected the credentials."""


class FimerDetectionError(FimerError):
    """The device answered but could not be identified as a supported datalogger."""


class FimerDataError(FimerError):
    """The device answered, but with data the library cannot interpret."""


class FimerUnsupportedFirmwareError(FimerError):
    """The datalogger firmware has a known defect that prevents operation."""

    def __init__(self, message: str, firmware_version: str | None = None) -> None:
        """Keep the offending firmware version for the caller."""
        super().__init__(message)
        self.firmware_version = firmware_version
