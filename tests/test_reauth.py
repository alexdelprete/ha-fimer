"""Tests for the datalogger credential reauthentication flow."""

from __future__ import annotations

from typing import Any

from custom_components.fimer.const import DOMAIN
from homeassistant.config_entries import SOURCE_REAUTH, ConfigEntryState
from homeassistant.const import CONF_PASSWORD, CONF_USERNAME
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType

from .conftest import REST_PASSWORD, SERIAL_NUMBER, fake_vsn300, rest_entry


async def test_wrong_password_starts_reauth_and_reauth_fixes_it(
    hass: HomeAssistant, serve_rest: Any
) -> None:
    """A rejected password puts the entry in reauth; the flow stores new credentials."""
    fake = fake_vsn300()
    fake.password = "changed"  # noqa: S105 - the card's new password
    host = await serve_rest(fake)
    entry = rest_entry(host, use_modbus=True, title="PVI-10.0-OUTD", unique_id=SERIAL_NUMBER)
    entry.add_to_hass(hass)
    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    assert entry.state is ConfigEntryState.SETUP_ERROR

    flows = hass.config_entries.flow.async_progress_by_handler(DOMAIN)
    assert len(flows) == 1
    flow = flows[0]
    assert flow["context"]["source"] == SOURCE_REAUTH
    assert flow["step_id"] == "reauth_confirm"

    # a wrong password again keeps the form up with the error
    result = await hass.config_entries.flow.async_configure(
        flow["flow_id"], {CONF_USERNAME: "guest", CONF_PASSWORD: "still wrong"}
    )
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": "invalid_auth"}

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_USERNAME: "guest", CONF_PASSWORD: "changed"}
    )
    await hass.async_block_till_done()
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "reauth_successful"
    assert entry.data[CONF_PASSWORD] == "changed"
    assert entry.state is ConfigEntryState.LOADED
    assert hass.states.get("sensor.vsn300_wifi_link_quality") is not None


async def test_reauth_can_be_started_manually(hass: HomeAssistant, serve_rest: Any) -> None:
    host = await serve_rest(fake_vsn300())
    entry = rest_entry(host, use_modbus=False, title="PVI-10.0-OUTD", unique_id="YYYYYY-3G82-XXXX")
    entry.add_to_hass(hass)
    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    assert entry.state is ConfigEntryState.LOADED

    result = await entry.start_reauth_flow(hass)
    assert result["step_id"] == "reauth_confirm"
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_USERNAME: "guest", CONF_PASSWORD: REST_PASSWORD}
    )
    await hass.async_block_till_done()
    assert result["reason"] == "reauth_successful"
    assert entry.state is ConfigEntryState.LOADED
