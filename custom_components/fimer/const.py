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

CONF_POWER_CONTROL: Final = "power_control"
"""Option: expose the SunSpec power limit as number and switch entities (experimental)."""
DEFAULT_POWER_CONTROL: Final = False
SETTINGS_SCAN_INTERVAL: Final = 60
"""Seconds between polls of the immediate controls model when power control is on."""

CONF_USE_MODBUS: Final = "use_modbus"
CONF_USE_REST: Final = "use_rest"
CONF_REST_MODEL: Final = "rest_model"
"""The detected datalogger family, cached so setup skips detection."""
CONF_REST_REQUIRES_AUTH: Final = "rest_requires_auth"
CONF_MODBUS_SECTION: Final = "modbus"
CONF_REST_SECTION: Final = "rest"
CONF_MIGRATE_FROM: Final = "migrate_from"
"""Entry ID of the earlier REST integration whose entities this entry takes over."""
DEFAULT_REST_USERNAME: Final = "guest"
LEGACY_REST_DOMAIN: Final = "abb_fimer_pvi_vsn_rest"

DEVICE_TYPE_INVERTER: Final = "inverter"
DEVICE_TYPE_DATALOGGER: Final = "datalogger"
DEVICE_TYPE_METER: Final = "meter"
DEVICE_TYPE_BATTERY: Final = "battery"

CONF_CONNECTION_ISSUES: Final = "connection_issues"
"""Option: raise a repair issue when a source stays unreachable."""
DEFAULT_CONNECTION_ISSUES: Final = True
CONF_STARTUP_ISSUES: Final = "startup_issues"
"""Option: count failed setup attempts towards the outage issue as well."""
DEFAULT_STARTUP_ISSUES: Final = False
CONF_FAILURES_THRESHOLD: Final = "failures_threshold"
"""Option: consecutive failed polls in daylight before the issue is raised."""
DEFAULT_FAILURES_THRESHOLD: Final = 3
MIN_FAILURES_THRESHOLD: Final = 1
MAX_FAILURES_THRESHOLD: Final = 100
CONF_NOTIFY_RECOVERY: Final = "notify_recovery"
"""Option: post a notification when a source recovers after an issue was raised."""
DEFAULT_NOTIFY_RECOVERY: Final = True
CONF_RECOVERY_SCRIPT: Final = "recovery_script"
"""Option: a script to run once when the issue is raised, e.g. to power-cycle the card."""
CONF_KNOWN_DEVICES: Final = "known_devices"
"""Entry data: REST device IDs seen so far, so a vanished device can be reported."""

DATALOGGER_SILENT_THRESHOLD: Final = 1800
"""Seconds without the datalogger's own readings before its repair issue is raised."""
SUN_ENTITY_ID: Final = "sun.sun"
STATE_BELOW_HORIZON: Final = "below_horizon"
