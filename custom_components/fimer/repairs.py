"""Fix flows for the integration's repair issues."""

from __future__ import annotations

from typing import Any

import voluptuous as vol

from homeassistant import data_entry_flow
from homeassistant.components.repairs import ConfirmRepairFlow, RepairsFlow
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr

from .const import CONF_KNOWN_DEVICES, DOMAIN
from .issues import ISSUE_PARTIAL_DISCOVERY, format_device_list, issue_id


class ForgetDevicesRepairFlow(RepairsFlow):
    """Drop the devices the datalogger no longer reports."""

    def __init__(self, entry_id: str, missing: list[str]) -> None:
        """Remember which entry and devices the issue is about."""
        self._entry_id = entry_id
        self._missing = missing

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> data_entry_flow.FlowResult:
        """Go straight to the confirmation."""
        return await self.async_step_confirm()

    async def async_step_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> data_entry_flow.FlowResult:
        """Forget the devices once confirmed."""
        if user_input is not None:
            async_forget_devices(self.hass, self._entry_id, set(self._missing))
            return self.async_create_entry(data={})
        return self.async_show_form(
            step_id="confirm",
            data_schema=vol.Schema({}),
            description_placeholders={
                "missing_devices": format_device_list(self.hass, self._entry_id, self._missing)
            },
        )


def async_forget_devices(hass: HomeAssistant, entry_id: str, device_ids: set[str]) -> None:
    """Remove devices from the entry's known list and from the registry."""
    entry = hass.config_entries.async_get_entry(entry_id)
    if entry is not None:
        known = [d for d in entry.data.get(CONF_KNOWN_DEVICES, []) if d not in device_ids]
        hass.config_entries.async_update_entry(
            entry, data={**entry.data, CONF_KNOWN_DEVICES: known}
        )
        runtime = getattr(entry, "runtime_data", None)
        if runtime is not None and runtime.rest_coordinator is not None:
            runtime.rest_coordinator.known_device_ids -= device_ids
            runtime.devices[:] = [d for d in runtime.devices if d.unique_id not in device_ids]
    registry = dr.async_get(hass)
    for device_id in device_ids:
        device = registry.async_get_device_by_identifier((DOMAIN, device_id), entry_id)
        if device is not None:
            registry.async_update_device(device.id, remove_config_entry_id=entry_id)


async def async_create_fix_flow(
    hass: HomeAssistant, issue_id_: str, data: dict[str, Any] | None
) -> RepairsFlow:
    """Return the fix flow for an issue."""
    entry_id = (data or {}).get("entry_id", "")
    if issue_id_ == issue_id(ISSUE_PARTIAL_DISCOVERY, entry_id):
        return ForgetDevicesRepairFlow(entry_id, list((data or {}).get("missing", [])))
    return ConfirmRepairFlow()
