"""Take over the entities of the earlier ABB/FIMER PVI VSN REST integration.

The earlier integration keyed its sensors as
``abb_fimer_pvi_vsn_rest_<type>_<compact serial>_<mapping key>`` (meters
with the logger serial in between). This integration keys them as
``<device unique id>_<point name>``. When an entry was created from a
legacy entry, the legacy entry is removed and every one of its sensors
that maps to a point here is re-registered under the new unique ID with
its old entity ID, name, icon and area, so history continues.
"""

from __future__ import annotations

from dataclasses import dataclass
import logging
from typing import TYPE_CHECKING

from homeassistant.components.sensor import DOMAIN as SENSOR_DOMAIN
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er, issue_registry as ir

from .const import CONF_MIGRATE_FROM, DOMAIN, LEGACY_REST_DOMAIN
from .issues import ISSUE_TAKEOVER_INCOMPLETE, async_create_entry_issue
from .pyfimer.rest import REST_POINTS
from .pyfimer.rest.mapping import SHARED_NAME_ALIASES

if TYPE_CHECKING:
    from . import FimerConfigEntry
    from .devices import FimerDevice

_LOGGER = logging.getLogger(__name__)

_LEGACY_PREFIX = f"{LEGACY_REST_DOMAIN}_"
# Mapping keys, longest first so a suffix match cannot stop at a shorter key.
_MAPPING_KEYS = sorted(
    {point.ha_name: point for point in reversed(REST_POINTS)}.items(),
    key=lambda item: len(item[0]),
    reverse=True,
)


@dataclass(frozen=True)
class LegacySensor:
    """What is kept of a legacy sensor registry entry."""

    entity_id: str
    unique_id: str
    name: str | None
    icon: str | None
    area_id: str | None
    disabled_by_user: bool
    hidden_by_user: bool


def compact_serial(serial: str) -> str:
    """Compact a serial the way the legacy integration did."""
    return serial.replace("-", "").replace(":", "").replace("_", "").lower()


def legacy_unique_id_to_new(unique_id: str, devices: list[FimerDevice]) -> str | None:
    """Return this integration's unique ID for a legacy sensor unique ID, if any."""
    if not unique_id.startswith(_LEGACY_PREFIX):
        return None
    rest = unique_id[len(_LEGACY_PREFIX) :]
    for mapping_key, point in _MAPPING_KEYS:
        if not rest.endswith(f"_{mapping_key}"):
            continue
        middle = rest[: -len(mapping_key) - 1]
        serial = middle.rsplit("_", 1)[-1]
        device = next((d for d in devices if compact_serial(d.unique_id) == serial), None)
        if device is None:
            return None
        name = SHARED_NAME_ALIASES.get(point.name, point.name)
        return f"{device.unique_id}_{name}"
    return None


async def async_take_over_legacy_entities(hass: HomeAssistant, entry: FimerConfigEntry) -> None:
    """Remove the legacy entry and re-register its sensors under this entry."""
    legacy_id = entry.data[CONF_MIGRATE_FROM]
    registry = er.async_get(hass)
    legacy_entry = hass.config_entries.async_get_entry(legacy_id)
    plan: list[tuple[str, LegacySensor]] = []
    left_behind: list[str] = []
    if legacy_entry is not None:
        for old in er.async_entries_for_config_entry(registry, legacy_id):
            if old.domain != SENSOR_DOMAIN:
                continue
            target = legacy_unique_id_to_new(old.unique_id, entry.runtime_data.devices)
            if target is None:
                left_behind.append(old.entity_id)
                continue
            plan.append(
                (
                    target,
                    LegacySensor(
                        entity_id=old.entity_id,
                        unique_id=old.unique_id,
                        name=old.name,
                        icon=old.icon,
                        area_id=old.area_id,
                        disabled_by_user=old.disabled_by is er.RegistryEntryDisabler.USER,
                        hidden_by_user=old.hidden_by is er.RegistryEntryHider.USER,
                    ),
                )
            )
        await hass.config_entries.async_remove(legacy_id)
        _LOGGER.info("Removed legacy entry %s; taking over %d of its sensors", legacy_id, len(plan))
        if left_behind:
            _async_report_left_behind(hass, entry, sorted(left_behind))

    for target, old in plan:
        if registry.async_get_entity_id(SENSOR_DOMAIN, DOMAIN, target):
            continue
        new = registry.async_get_or_create(
            SENSOR_DOMAIN,
            DOMAIN,
            target,
            suggested_object_id=old.entity_id.split(".", 1)[1],
            config_entry=entry,
        )
        registry.async_update_entity(
            new.entity_id,
            name=old.name,
            icon=old.icon,
            area_id=old.area_id,
            disabled_by=er.RegistryEntryDisabler.USER if old.disabled_by_user else None,
            hidden_by=er.RegistryEntryHider.USER if old.hidden_by_user else None,
        )

    data = {key: value for key, value in entry.data.items() if key != CONF_MIGRATE_FROM}
    hass.config_entries.async_update_entry(entry, data=data)


_LISTED_LEFT_BEHIND = 25


def _async_report_left_behind(
    hass: HomeAssistant, entry: FimerConfigEntry, entity_ids: list[str]
) -> None:
    """Tell the user which legacy sensors have no counterpart here."""
    listed = [f"- `{entity_id}`" for entity_id in entity_ids[:_LISTED_LEFT_BEHIND]]
    if len(entity_ids) > _LISTED_LEFT_BEHIND:
        listed.append(f"- … and {len(entity_ids) - _LISTED_LEFT_BEHIND} more")
    async_create_entry_issue(
        hass,
        entry,
        ISSUE_TAKEOVER_INCOMPLETE,
        severity=ir.IssueSeverity.WARNING,
        is_fixable=True,
        placeholders={"count": str(len(entity_ids)), "entities": "\n".join(listed)},
    )
