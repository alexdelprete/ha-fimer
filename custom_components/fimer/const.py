"""Constants for the FIMER (ABB / Power-One) integration."""

from typing import Final

DOMAIN: Final = "fimer"
VERSION = "0.1.0"
MANUFACTURER: Final = "FIMER"

CONF_UNIT_ID: Final = "unit_id"
CONF_BASE_ADDRESS: Final = "base_address"
CONF_ADVANCED: Final = "advanced"

DEFAULT_PORT: Final = 502
DEFAULT_UNIT_ID: Final = 2
DEFAULT_BASE_ADDRESS: Final = 0
MIN_UNIT_ID: Final = 1
MAX_UNIT_ID: Final = 247
MAX_BASE_ADDRESS: Final = 65535

DEFAULT_SCAN_INTERVAL: Final = 30
MIN_SCAN_INTERVAL: Final = 10
MAX_SCAN_INTERVAL: Final = 600

MAX_FAILED_UPDATES: Final = 3
"""Consecutive failed polls before the interval stretches for a sleeping inverter."""
ERROR_SCAN_INTERVAL: Final = 300
