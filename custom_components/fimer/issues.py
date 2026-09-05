"""Repair issues the integration raises, and the outage monitor behind them.

Every issue ID ends with the config entry ID, so the issues of one entry can
be found and cleared together. The texts live under ``issues`` in the
translations; the fix flows in :mod:`repairs`.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any, Final

from homeassistant.components import persistent_notification
from homeassistant.const import ATTR_ENTITY_ID, CONF_HOST
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import device_registry as dr, issue_registry as ir

from .const import (
    CONF_CONNECTION_ISSUES,
    CONF_FAILURES_THRESHOLD,
    CONF_NOTIFY_RECOVERY,
    CONF_RECOVERY_SCRIPT,
    DEFAULT_CONNECTION_ISSUES,
    DEFAULT_FAILURES_THRESHOLD,
    DEFAULT_NOTIFY_RECOVERY,
    DOMAIN,
    STATE_BELOW_HORIZON,
    SUN_ENTITY_ID,
)

if TYPE_CHECKING:
    from homeassistant.config_entries import ConfigEntry

_LOGGER = logging.getLogger(__name__)

ISSUE_CONNECTION_FAILED: Final = "connection_failed"
"""Suffixed with the source: ``connection_failed_modbus`` or ``connection_failed_rest``."""
ISSUE_UNSUPPORTED_FIRMWARE: Final = "unsupported_firmware"
ISSUE_DATALOGGER_SILENT: Final = "datalogger_silent"
ISSUE_PARTIAL_DISCOVERY: Final = "partial_discovery"
ISSUE_TAKEOVER_INCOMPLETE: Final = "takeover_incomplete"

LEARN_MORE_URL: Final = "https://github.com/alexdelprete/ha-fimer#troubleshooting"

SOURCE_MODBUS: Final = "modbus"
SOURCE_REST: Final = "rest"


def issue_id(kind: str, entry_id: str) -> str:
    """The registry ID of an issue of a kind for one entry."""
    return f"{kind}_{entry_id}"


@callback
def async_get_entry_issue(hass: HomeAssistant, entry_id: str, kind: str) -> ir.IssueEntry | None:
    """Return the issue of a kind for an entry, if it is raised."""
    return ir.async_get(hass).async_get_issue(DOMAIN, issue_id(kind, entry_id))


@callback
def async_create_entry_issue(
    hass: HomeAssistant,
    entry: ConfigEntry,
    kind: str,
    *,
    severity: ir.IssueSeverity,
    placeholders: dict[str, str] | None = None,
    is_fixable: bool = False,
    data: dict[str, Any] | None = None,
) -> None:
    """Raise (or refresh) an issue of a kind for an entry."""
    ir.async_create_issue(
        hass,
        DOMAIN,
        issue_id(kind, entry.entry_id),
        is_fixable=is_fixable,
        severity=severity,
        translation_key=kind,
        translation_placeholders={
            "title": entry.title,
            "host": entry.data.get(CONF_HOST, ""),
            **(placeholders or {}),
        },
        learn_more_url=LEARN_MORE_URL,
        data={"entry_id": entry.entry_id, **(data or {})},
    )


@callback
def async_delete_entry_issue(hass: HomeAssistant, entry_id: str, kind: str) -> bool:
    """Clear an issue of a kind for an entry; return whether it was raised."""
    if async_get_entry_issue(hass, entry_id, kind) is None:
        return False
    ir.async_delete_issue(hass, DOMAIN, issue_id(kind, entry_id))
    return True


@callback
def async_delete_entry_issues(hass: HomeAssistant, entry_id: str) -> None:
    """Clear every issue of an entry, when the entry goes away."""
    registry = ir.async_get(hass)
    suffix = f"_{entry_id}"
    for domain, issue_id_ in list(registry.issues):
        if domain == DOMAIN and issue_id_.endswith(suffix):
            registry.async_delete(DOMAIN, issue_id_)


def format_device_list(hass: HomeAssistant, entry_id: str, device_ids: list[str]) -> str:
    """A Markdown list of device IDs with the names the registry knows them by."""
    registry = dr.async_get(hass)
    lines = []
    for device_id in device_ids:
        device = registry.async_get_device_by_identifier((DOMAIN, device_id), entry_id)
        name = (device.name_by_user or device.name) if device else None
        lines.append(f"- {name} ({device_id})" if name else f"- {device_id}")
    return "\n".join(lines)


class OutageMonitor:
    """Raise a repair issue when a source stays unreachable, clear it when it recovers.

    Failures only count while the sun is up: a PV inverter that answers
    nothing at night is asleep, not broken. When the issue is raised the
    optional recovery script runs once, and when the source comes back a
    notification says so.
    """

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry, source: str) -> None:
        """Start counting for one source of an entry."""
        self.hass = hass
        self.entry = entry
        self.source = source
        self.kind = f"{ISSUE_CONNECTION_FAILED}_{source}"
        self.failures = 0
        if not self._enabled:
            # the option was switched off while an issue was raised
            async_delete_entry_issue(hass, entry.entry_id, self.kind)

    @property
    def _enabled(self) -> bool:
        return self.entry.options.get(CONF_CONNECTION_ISSUES, DEFAULT_CONNECTION_ISSUES)

    @property
    def _threshold(self) -> int:
        return self.entry.options.get(CONF_FAILURES_THRESHOLD, DEFAULT_FAILURES_THRESHOLD)

    @property
    def raised(self) -> bool:
        """Whether the issue is currently raised."""
        return async_get_entry_issue(self.hass, self.entry.entry_id, self.kind) is not None

    def _daylight(self) -> bool:
        sun = self.hass.states.get(SUN_ENTITY_ID)
        return sun is None or sun.state != STATE_BELOW_HORIZON

    async def async_failure(self, error: str) -> None:
        """Count a failed poll; raise the issue at the threshold."""
        if not self._enabled or self.raised:
            return
        if not self._daylight():
            self.failures = 0
            return
        self.failures += 1
        if self.failures < self._threshold:
            return
        async_create_entry_issue(
            self.hass,
            self.entry,
            self.kind,
            severity=ir.IssueSeverity.ERROR,
            placeholders={"error": error, "failures": str(self.failures)},
        )
        if script := self.entry.options.get(CONF_RECOVERY_SCRIPT):
            await self._async_run_script(script)

    async def _async_run_script(self, script: str) -> None:
        _LOGGER.info("Running recovery script %s for %s", script, self.entry.title)
        try:
            await self.hass.services.async_call(
                "script", "turn_on", {ATTR_ENTITY_ID: script}, blocking=False
            )
        except HomeAssistantError as err:
            _LOGGER.warning("Recovery script %s could not be run: %s", script, err)

    async def async_success(self) -> None:
        """Note a successful poll; clear the issue and announce the recovery."""
        self.failures = 0
        if not async_delete_entry_issue(self.hass, self.entry.entry_id, self.kind):
            return
        _LOGGER.info("The %s source of %s is reachable again", self.source, self.entry.title)
        if not self.entry.options.get(CONF_NOTIFY_RECOVERY, DEFAULT_NOTIFY_RECOVERY):
            return
        label = "Modbus" if self.source == SOURCE_MODBUS else "datalogger REST API"
        persistent_notification.async_create(
            self.hass,
            f"The {label} of {self.entry.title} at {self.entry.data.get(CONF_HOST, '')} "
            "answers again. Its readings are up to date.",
            title=f"{self.entry.title} recovered",
            notification_id=f"{DOMAIN}_recovered_{self.source}_{self.entry.entry_id}",
        )
