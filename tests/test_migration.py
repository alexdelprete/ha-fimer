"""Tests for taking over the entities of the legacy REST integration."""

from __future__ import annotations

from typing import Any

from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.fimer.const import CONF_MIGRATE_FROM, DOMAIN, LEGACY_REST_DOMAIN
from custom_components.fimer.migration import compact_serial, legacy_unique_id_to_new
from homeassistant.config_entries import ConfigEntryState
from homeassistant.const import CONF_HOST
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er

from .conftest import fake_vsn300, rest_entry


def test_compact_serial() -> None:
    assert compact_serial("077909-3G82-3112") == "0779093g823112"
    assert compact_serial("0c:1c:57:fd:c6:2c") == "0c1c57fdc62c"


async def test_takeover(
    hass: HomeAssistant, serve_rest: Any, entity_registry: er.EntityRegistry
) -> None:
    """Legacy sensors keep their entity IDs, names and areas under the new unique IDs."""
    host = await serve_rest(fake_vsn300())
    legacy = MockConfigEntry(
        domain=LEGACY_REST_DOMAIN, title="VSN300 (LLLLLL-3N16-BBBB)", data={CONF_HOST: host}
    )
    legacy.add_to_hass(hass)
    old_power = entity_registry.async_get_or_create(
        "sensor",
        LEGACY_REST_DOMAIN,
        "abb_fimer_pvi_vsn_rest_inverter_yyyyyy3g82xxxx_watts",
        suggested_object_id="abb_fimer_inverter_power_ac",
        config_entry=legacy,
    )
    entity_registry.async_update_entity(old_power.entity_id, name="Solar power", icon="mdi:sun")
    old_quality = entity_registry.async_get_or_create(
        "sensor",
        LEGACY_REST_DOMAIN,
        "abb_fimer_pvi_vsn_rest_datalogger_llllll3n16bbbb_wlan0_link_quality",
        suggested_object_id="abb_fimer_datalogger_wifi_link_quality",
        config_entry=legacy,
    )
    entity_registry.async_get_or_create(
        "sensor",
        LEGACY_REST_DOMAIN,
        "abb_fimer_pvi_vsn_rest_inverter_yyyyyy3g82xxxx_no_such_point",
        config_entry=legacy,
    )

    base = rest_entry(host, use_modbus=False, title="PVI-10.0-OUTD", unique_id="YYYYYY-3G82-XXXX")
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="PVI-10.0-OUTD",
        unique_id="YYYYYY-3G82-XXXX",
        data={**base.data, CONF_MIGRATE_FROM: legacy.entry_id},
    )
    entry.add_to_hass(hass)
    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    assert entry.state is ConfigEntryState.LOADED

    assert hass.config_entries.async_get_entry(legacy.entry_id) is None
    assert CONF_MIGRATE_FROM not in entry.data

    power = entity_registry.async_get("sensor.abb_fimer_inverter_power_ac")
    assert power is not None
    assert power.platform == DOMAIN
    assert power.unique_id == "YYYYYY-3G82-XXXX_W"
    assert power.name == "Solar power"
    assert power.icon == "mdi:sun"
    assert hass.states.get("sensor.abb_fimer_inverter_power_ac") is not None

    quality = entity_registry.async_get(old_quality.entity_id)
    assert quality is not None
    assert quality.unique_id == "LLLLLL-3N16-BBBB_wlan0_link_quality"
    assert hass.states.get(old_quality.entity_id).state == "100"


def test_unique_id_mapping_edge_cases() -> None:
    from custom_components.fimer.devices import FimerDevice  # noqa: PLC0415
    from homeassistant.helpers.device_registry import DeviceInfo  # noqa: PLC0415

    device = FimerDevice("077909-3G82-3112", "inverter", DeviceInfo(identifiers=set()))
    assert legacy_unique_id_to_new("other_domain_x", [device]) is None
    assert (
        legacy_unique_id_to_new("abb_fimer_pvi_vsn_rest_inverter_0779093g823112_bogus", [device])
        is None
    )
    assert (
        legacy_unique_id_to_new("abb_fimer_pvi_vsn_rest_inverter_unknown_watts", [device]) is None
    )
    assert (
        legacy_unique_id_to_new("abb_fimer_pvi_vsn_rest_inverter_0779093g823112_watts", [device])
        == "077909-3G82-3112_W"
    )
    # a VSN700 state name is emitted under the shared name
    assert (
        legacy_unique_id_to_new(
            "abb_fimer_pvi_vsn_rest_inverter_0779093g823112_glob_state", [device]
        )
        == "077909-3G82-3112_GlobalSt"
    )
