"""Tests for the repair issues and their fix flows."""

from __future__ import annotations

from datetime import timedelta
from http import HTTPStatus
from typing import Any
from unittest.mock import patch

from freezegun.api import FrozenDateTimeFactory
from modbus_connection import ModbusConnectionError
from modbus_connection.mock import MockModbusUnit
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    async_fire_time_changed,
    async_mock_service,
)
from pytest_homeassistant_custom_component.typing import ClientSessionGenerator

from custom_components.fimer.const import (
    CONF_CONNECTION_ISSUES,
    CONF_FAILURES_THRESHOLD,
    CONF_KNOWN_DEVICES,
    CONF_MIGRATE_FROM,
    CONF_NOTIFY_RECOVERY,
    CONF_RECOVERY_SCRIPT,
    DOMAIN,
    LEGACY_REST_DOMAIN,
)
from custom_components.fimer.issues import (
    ISSUE_DATALOGGER_SILENT,
    ISSUE_PARTIAL_DISCOVERY,
    ISSUE_TAKEOVER_INCOMPLETE,
    ISSUE_UNSUPPORTED_FIRMWARE,
    issue_id,
)
from homeassistant.config_entries import ConfigEntryState
from homeassistant.const import CONF_HOST
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr, issue_registry as ir
from homeassistant.setup import async_setup_component

from .conftest import SERIAL_NUMBER, fake_vsn300, fake_vsn700, rest_entry

VSN300_LOGGER_RAW_ID = "00:00:00:00:00:02"
VSN700_METER = "120730-3N52-3019"
VSN700_INVERTER = "140842-3P81-2619"


async def _setup(hass: HomeAssistant, entry: MockConfigEntry) -> None:
    entry.add_to_hass(hass)
    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()


async def _poll(hass: HomeAssistant, freezer: FrozenDateTimeFactory, seconds: int = 31) -> None:
    freezer.tick(timedelta(seconds=seconds))
    async_fire_time_changed(hass)
    await hass.async_block_till_done(wait_background_tasks=True)


def _issue(
    issue_registry: ir.IssueRegistry, kind: str, entry: MockConfigEntry
) -> ir.IssueEntry | None:
    return issue_registry.async_get_issue(DOMAIN, issue_id(kind, entry.entry_id))


async def _run_fix_flow(
    hass: HomeAssistant, hass_client: ClientSessionGenerator, kind: str, entry: MockConfigEntry
) -> None:
    assert await async_setup_component(hass, "repairs", {})
    client = await hass_client()
    resp = await client.post(
        "/api/repairs/issues/fix",
        json={"handler": DOMAIN, "issue_id": issue_id(kind, entry.entry_id)},
    )
    assert resp.status == HTTPStatus.OK
    flow = await resp.json()
    assert flow["step_id"] == "confirm"
    resp = await client.post(f"/api/repairs/issues/fix/{flow['flow_id']}", json={})
    assert resp.status == HTTPStatus.OK
    result = await resp.json()
    assert result["type"] == "create_entry"
    await hass.async_block_till_done()


async def test_modbus_outage_raises_issue_and_recovers(
    hass: HomeAssistant,
    init_integration: MockConfigEntry,
    mock_unit: MockModbusUnit,
    issue_registry: ir.IssueRegistry,
    freezer: FrozenDateTimeFactory,
) -> None:
    """Three failed polls in daylight raise the issue; the next good poll clears it."""
    entry = init_integration
    mock_unit.fail_requests(ModbusConnectionError("asleep"))
    await _poll(hass, freezer)
    await _poll(hass, freezer)
    assert _issue(issue_registry, "connection_failed_modbus", entry) is None
    await _poll(hass, freezer)
    issue = _issue(issue_registry, "connection_failed_modbus", entry)
    assert issue is not None
    assert issue.severity is ir.IssueSeverity.ERROR
    assert issue.translation_placeholders["failures"] == "3"
    assert "asleep" in issue.translation_placeholders["error"]
    assert issue.translation_placeholders["title"] == entry.title

    mock_unit.fail_requests(None)
    with patch("custom_components.fimer.issues.persistent_notification.async_create") as notify:
        await _poll(hass, freezer, seconds=301)
    assert _issue(issue_registry, "connection_failed_modbus", entry) is None
    assert notify.call_count == 1
    assert "Modbus" in notify.call_args.args[1]


async def test_failures_at_night_do_not_count(
    hass: HomeAssistant,
    init_integration: MockConfigEntry,
    mock_unit: MockModbusUnit,
    issue_registry: ir.IssueRegistry,
    freezer: FrozenDateTimeFactory,
) -> None:
    """A sleeping inverter is not a fault: nothing is raised below the horizon."""
    hass.states.async_set("sun.sun", "below_horizon")
    mock_unit.fail_requests(ModbusConnectionError("asleep"))
    for _ in range(3):
        await _poll(hass, freezer)
    await _poll(hass, freezer, seconds=301)
    assert _issue(issue_registry, "connection_failed_modbus", init_integration) is None

    hass.states.async_set("sun.sun", "above_horizon")
    for _ in range(3):
        await _poll(hass, freezer, seconds=301)
    assert _issue(issue_registry, "connection_failed_modbus", init_integration) is not None


async def test_outage_options(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_unit: MockModbusUnit,
    issue_registry: ir.IssueRegistry,
    freezer: FrozenDateTimeFactory,
) -> None:
    """The threshold and the recovery script are honoured; recovery can be silent."""
    calls = async_mock_service(hass, "script", "turn_on")
    entry = mock_config_entry
    entry.add_to_hass(hass)
    hass.config_entries.async_update_entry(
        entry,
        options={
            CONF_FAILURES_THRESHOLD: 1,
            CONF_RECOVERY_SCRIPT: "script.reboot_card",
            CONF_NOTIFY_RECOVERY: False,
        },
    )
    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    mock_unit.fail_requests(ModbusConnectionError("gone"))
    await _poll(hass, freezer)
    assert _issue(issue_registry, "connection_failed_modbus", entry) is not None
    assert len(calls) == 1
    assert calls[0].data["entity_id"] == "script.reboot_card"
    await _poll(hass, freezer)  # a second failure does not run the script again
    assert len(calls) == 1

    mock_unit.fail_requests(None)
    with patch("custom_components.fimer.issues.persistent_notification.async_create") as notify:
        await _poll(hass, freezer)
    assert _issue(issue_registry, "connection_failed_modbus", entry) is None
    notify.assert_not_called()


async def test_missing_recovery_script_is_logged(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_unit: MockModbusUnit,
    issue_registry: ir.IssueRegistry,
    freezer: FrozenDateTimeFactory,
    caplog: Any,
) -> None:
    """A script that does not exist is reported, not raised."""
    entry = mock_config_entry
    entry.add_to_hass(hass)
    hass.config_entries.async_update_entry(
        entry, options={CONF_FAILURES_THRESHOLD: 1, CONF_RECOVERY_SCRIPT: "script.nope"}
    )
    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    mock_unit.fail_requests(ModbusConnectionError("gone"))
    await _poll(hass, freezer)
    assert _issue(issue_registry, "connection_failed_modbus", entry) is not None
    assert "script.nope could not be run" in caplog.text


async def test_connection_issues_can_be_switched_off(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_unit: MockModbusUnit,
    issue_registry: ir.IssueRegistry,
    freezer: FrozenDateTimeFactory,
) -> None:
    """With the option off nothing is raised, and a raised issue is cleared on reload."""
    entry = mock_config_entry
    entry.add_to_hass(hass)
    hass.config_entries.async_update_entry(entry, options={CONF_FAILURES_THRESHOLD: 1})
    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    mock_unit.fail_requests(ModbusConnectionError("gone"))
    await _poll(hass, freezer)
    assert _issue(issue_registry, "connection_failed_modbus", entry) is not None

    hass.config_entries.async_update_entry(
        entry, options={CONF_FAILURES_THRESHOLD: 1, CONF_CONNECTION_ISSUES: False}
    )
    # still failing: the reload does not get past the first refresh, yet the issue goes
    await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done()
    assert entry.state is ConfigEntryState.SETUP_RETRY
    assert _issue(issue_registry, "connection_failed_modbus", entry) is None

    mock_unit.fail_requests(None)
    await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done()
    assert entry.state is ConfigEntryState.LOADED
    mock_unit.fail_requests(ModbusConnectionError("gone"))
    for _ in range(3):
        await _poll(hass, freezer)
    assert _issue(issue_registry, "connection_failed_modbus", entry) is None


async def test_rest_outage_raises_issue(
    hass: HomeAssistant,
    serve_rest: Any,
    issue_registry: ir.IssueRegistry,
    freezer: FrozenDateTimeFactory,
) -> None:
    """The REST source has its own issue, cleared when the card answers again."""
    fake = fake_vsn300()
    host = await serve_rest(fake)
    entry = rest_entry(host, use_modbus=False, title="PVI-10.0-OUTD", unique_id=SERIAL_NUMBER)
    await _setup(hass, entry)

    fake.livedata_status = 503
    for _ in range(3):
        await _poll(hass, freezer)
    issue = _issue(issue_registry, "connection_failed_rest", entry)
    assert issue is not None
    assert issue.translation_placeholders["host"] == host

    fake.livedata_status = 200
    await _poll(hass, freezer, seconds=301)
    assert _issue(issue_registry, "connection_failed_rest", entry) is None


async def test_unsupported_firmware(
    hass: HomeAssistant, serve_rest: Any, issue_registry: ir.IssueRegistry
) -> None:
    """A VSN300 on firmware 2.0.0 fails setup for good, with an issue carrying the fix."""
    fake = fake_vsn300()
    fake.status["keys"]["fw.release_number"]["value"] = "2.0.0"
    host = await serve_rest(fake)
    entry = rest_entry(host, use_modbus=False, title="PVI-10.0-OUTD", unique_id=SERIAL_NUMBER)
    await _setup(hass, entry)
    assert entry.state is ConfigEntryState.SETUP_ERROR
    issue = _issue(issue_registry, ISSUE_UNSUPPORTED_FIRMWARE, entry)
    assert issue is not None
    assert issue.translation_placeholders["firmware_version"] == "2.0.0"
    assert issue.severity is ir.IssueSeverity.ERROR

    fake.status["keys"]["fw.release_number"]["value"] = "2.0.1"
    await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done()
    assert entry.state is ConfigEntryState.LOADED
    assert _issue(issue_registry, ISSUE_UNSUPPORTED_FIRMWARE, entry) is None


async def test_datalogger_silent(
    hass: HomeAssistant,
    serve_rest: Any,
    issue_registry: ir.IssueRegistry,
    freezer: FrozenDateTimeFactory,
) -> None:
    """A card that stops reporting on itself for half an hour gets an issue."""
    fake = fake_vsn300()
    logger_data = fake.livedata.pop(VSN300_LOGGER_RAW_ID)
    host = await serve_rest(fake)
    entry = rest_entry(host, use_modbus=False, title="PVI-10.0-OUTD", unique_id=SERIAL_NUMBER)
    await _setup(hass, entry)
    assert entry.state is ConfigEntryState.LOADED

    await _poll(hass, freezer, seconds=600)
    assert _issue(issue_registry, ISSUE_DATALOGGER_SILENT, entry) is None
    await _poll(hass, freezer, seconds=1300)
    issue = _issue(issue_registry, ISSUE_DATALOGGER_SILENT, entry)
    assert issue is not None
    assert issue.translation_placeholders["minutes"] == "30"

    fake.livedata[VSN300_LOGGER_RAW_ID] = logger_data
    await _poll(hass, freezer)
    assert _issue(issue_registry, ISSUE_DATALOGGER_SILENT, entry) is None


async def test_partial_discovery_and_forget(
    hass: HomeAssistant,
    serve_rest: Any,
    hass_client: ClientSessionGenerator,
    issue_registry: ir.IssueRegistry,
    device_registry: dr.DeviceRegistry,
    freezer: FrozenDateTimeFactory,
) -> None:
    """A device the card stops reporting is listed, and can be forgotten through the fix."""
    fake = fake_vsn700()
    host = await serve_rest(fake)
    entry = rest_entry(host, use_modbus=False, title="REACT2-5.0-TL", unique_id=VSN700_INVERTER)
    await _setup(hass, entry)
    known = entry.data[CONF_KNOWN_DEVICES]
    assert VSN700_METER in known
    assert VSN700_INVERTER in known
    assert not any(":" in device_id or device_id.startswith("0c1c57") for device_id in known)
    assert _issue(issue_registry, ISSUE_PARTIAL_DISCOVERY, entry) is None

    meter_data = fake.livedata.pop(VSN700_METER)
    await _poll(hass, freezer)
    issue = _issue(issue_registry, ISSUE_PARTIAL_DISCOVERY, entry)
    assert issue is not None
    assert issue.is_fixable
    assert issue.data == {"entry_id": entry.entry_id, "missing": [VSN700_METER]}
    assert VSN700_METER in issue.translation_placeholders["missing_devices"]

    # the missing device survives a reload: it is remembered in the entry
    await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done()
    assert _issue(issue_registry, ISSUE_PARTIAL_DISCOVERY, entry) is not None
    assert device_registry.async_get_device_by_identifier((DOMAIN, VSN700_METER), entry.entry_id)

    await _run_fix_flow(hass, hass_client, ISSUE_PARTIAL_DISCOVERY, entry)
    assert _issue(issue_registry, ISSUE_PARTIAL_DISCOVERY, entry) is None
    assert VSN700_METER not in entry.data[CONF_KNOWN_DEVICES]
    assert (
        device_registry.async_get_device_by_identifier((DOMAIN, VSN700_METER), entry.entry_id)
        is None
    )

    # when the card reports it again it comes back as a new device
    fake.livedata[VSN700_METER] = meter_data
    await _poll(hass, freezer)
    assert VSN700_METER in entry.data[CONF_KNOWN_DEVICES]
    assert device_registry.async_get_device_by_identifier((DOMAIN, VSN700_METER), entry.entry_id)
    assert _issue(issue_registry, ISSUE_PARTIAL_DISCOVERY, entry) is None


async def test_partial_discovery_clears_when_device_returns(
    hass: HomeAssistant,
    serve_rest: Any,
    issue_registry: ir.IssueRegistry,
    freezer: FrozenDateTimeFactory,
) -> None:
    """The issue disappears by itself when the device is reported again."""
    fake = fake_vsn700()
    host = await serve_rest(fake)
    entry = rest_entry(host, use_modbus=False, title="REACT2-5.0-TL", unique_id=VSN700_INVERTER)
    await _setup(hass, entry)
    meter_data = fake.livedata.pop(VSN700_METER)
    await _poll(hass, freezer)
    assert _issue(issue_registry, ISSUE_PARTIAL_DISCOVERY, entry) is not None
    fake.livedata[VSN700_METER] = meter_data
    await _poll(hass, freezer)
    assert _issue(issue_registry, ISSUE_PARTIAL_DISCOVERY, entry) is None


async def test_takeover_incomplete(
    hass: HomeAssistant,
    serve_rest: Any,
    hass_client: ClientSessionGenerator,
    issue_registry: ir.IssueRegistry,
    entity_registry: Any,
) -> None:
    """Legacy sensors without a counterpart are listed once and can be acknowledged."""
    host = await serve_rest(fake_vsn300())
    legacy = MockConfigEntry(domain=LEGACY_REST_DOMAIN, title="VSN300", data={CONF_HOST: host})
    legacy.add_to_hass(hass)
    entity_registry.async_get_or_create(
        "sensor",
        LEGACY_REST_DOMAIN,
        "abb_fimer_pvi_vsn_rest_inverter_yyyyyy3g82xxxx_watts",
        config_entry=legacy,
    )
    entity_registry.async_get_or_create(
        "sensor",
        LEGACY_REST_DOMAIN,
        "abb_fimer_pvi_vsn_rest_inverter_yyyyyy3g82xxxx_no_such_point",
        suggested_object_id="abb_fimer_inverter_no_such_point",
        config_entry=legacy,
    )
    base = rest_entry(host, use_modbus=False, title="PVI-10.0-OUTD", unique_id="YYYYYY-3G82-XXXX")
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="PVI-10.0-OUTD",
        unique_id="YYYYYY-3G82-XXXX",
        data={**base.data, CONF_MIGRATE_FROM: legacy.entry_id},
    )
    await _setup(hass, entry)
    assert entry.state is ConfigEntryState.LOADED
    issue = _issue(issue_registry, ISSUE_TAKEOVER_INCOMPLETE, entry)
    assert issue is not None
    assert issue.translation_placeholders["count"] == "1"
    assert "sensor.abb_fimer_inverter_no_such_point" in issue.translation_placeholders["entities"]

    await _run_fix_flow(hass, hass_client, ISSUE_TAKEOVER_INCOMPLETE, entry)
    assert _issue(issue_registry, ISSUE_TAKEOVER_INCOMPLETE, entry) is None


async def test_issues_go_with_the_entry(
    hass: HomeAssistant,
    init_integration: MockConfigEntry,
    mock_unit: MockModbusUnit,
    issue_registry: ir.IssueRegistry,
    freezer: FrozenDateTimeFactory,
) -> None:
    """Removing the entry clears whatever issues it raised."""
    entry = init_integration
    mock_unit.fail_requests(ModbusConnectionError("gone"))
    for _ in range(3):
        await _poll(hass, freezer)
    assert _issue(issue_registry, "connection_failed_modbus", entry) is not None
    await hass.config_entries.async_remove(entry.entry_id)
    await hass.async_block_till_done()
    assert _issue(issue_registry, "connection_failed_modbus", entry) is None
