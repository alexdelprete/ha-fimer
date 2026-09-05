"""Fixtures for FIMER (ABB / Power-One) tests."""

from __future__ import annotations

from collections.abc import AsyncIterator, Awaitable, Callable, Generator
from contextlib import asynccontextmanager
import json
from pathlib import Path
from typing import Any
from unittest.mock import patch

from modbus_connection.mock import MockModbusConnection, MockModbusUnit
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.fimer.const import (
    CONF_BASE_ADDRESS,
    CONF_UNIT_ID,
    CONF_USE_MODBUS,
    CONF_USE_REST,
    DOMAIN,
)
from custom_components.fimer.pyfimer.modbus.testing import (
    InverterSpec,
    MpptInputSpec,
    VendorSpec,
    build_register_map,
)
from homeassistant.const import CONF_HOST, CONF_PASSWORD, CONF_PORT, CONF_USERNAME
from homeassistant.core import HomeAssistant

from .pyfimer.fake_vsn import FakeVsn

FIXTURES = Path(__file__).parent / "fixtures" / "rest"
REST_PASSWORD = "secret"  # noqa: S105

SERIAL_NUMBER = "123456-3N01-1234"
HOST = "192.0.2.10"

INVERTER_SPEC = InverterSpec(
    ac_current=6.54,
    ac_current_phase_a=2.18,
    ac_current_phase_b=2.2,
    ac_current_phase_c=2.16,
    voltage_a=230.5,
    voltage_b=231.0,
    voltage_c=229.5,
    voltage_ab=400.1,
    ac_power=1500,
    frequency=50.02,
    power_factor=99.5,
    energy_total=1234567,
    dc_voltage=None,
    dc_power=1550,
    cabinet_temperature=453.0,  # the tenfold scale factor quirk
    other_temperature=41.2,
    operating_state=4,
    vendor_operating_state=2,
)
MPPT_INPUTS = [
    MpptInputSpec("String 1", current=3.21, voltage=350.0, power=800),
    MpptInputSpec("String 2", current=2.5, voltage=340.0, power=750),
]
VENDOR_SPEC = VendorSpec(
    global_state=6,
    inverter_state=2,
    dc_state_1=2,
    dc_state_2=2,
    sys_time=800000000,
    alarms=[1, 32, 77],
    day_wh=12345.0,
    total_wh=1234567.0,
    week_wh=50000.0,
    month_wh=200000.0,
    year_wh=3000000.0,
    temperature=45.5,
    booster_temperature=50.25,
    isolation_1=12.5,
    cos_phi=0.995,
    output_power_permanent=100,
)


def default_register_map(**overrides: Any) -> dict[int, int]:
    """Build the register map of the test inverter with optional overrides."""
    kwargs: dict[str, Any] = {
        "serial_number": SERIAL_NUMBER,
        "inverter": INVERTER_SPEC,
        "mppt_inputs": MPPT_INPUTS,
        "vendor": VENDOR_SPEC,
        "include_vendor_model": True,
    }
    kwargs.update(overrides)
    return build_register_map(**kwargs)


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations: None) -> None:
    """Enable custom integrations in all tests."""


@pytest.fixture
def mock_unit() -> MockModbusUnit:
    """A mock Modbus unit serving the test inverter's SunSpec chain."""
    unit = MockModbusConnection().for_unit(2)
    unit.holding.update(default_register_map())
    return unit


@pytest.fixture(autouse=True)
def mock_shared_connection(mock_unit: MockModbusUnit) -> Generator[None]:
    """Hand out the mock unit in place of core's shared Modbus connection."""

    @asynccontextmanager
    async def temporary_unit(*args: Any, **kwargs: Any) -> AsyncIterator[MockModbusUnit]:
        yield mock_unit

    with (
        patch("custom_components.fimer.async_get_unit", return_value=mock_unit),
        patch("custom_components.fimer.config_flow.async_get_temporary_unit", temporary_unit),
    ):
        yield


@pytest.fixture
def mock_config_entry() -> MockConfigEntry:
    """A config entry for the test inverter."""
    return MockConfigEntry(
        domain=DOMAIN,
        title="PVI-10.0-OUTD",
        unique_id=SERIAL_NUMBER,
        data={CONF_HOST: HOST, CONF_PORT: 502, CONF_UNIT_ID: 2, CONF_BASE_ADDRESS: 0},
    )


@pytest.fixture
async def init_integration(
    hass: HomeAssistant, mock_config_entry: MockConfigEntry
) -> MockConfigEntry:
    """Set up the integration with the test inverter."""
    mock_config_entry.add_to_hass(hass)
    await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()
    return mock_config_entry


def load_capture(name: str) -> dict[str, Any]:
    """Load a REST capture fixture."""
    return json.loads(FIXTURES.joinpath(f"{name}.json").read_text())


def fake_vsn300() -> FakeVsn:
    """A fake VSN300 in front of the test PVI, as captured."""
    return FakeVsn(
        "VSN300",
        load_capture("alexdelprete_vsn300_fw201_status"),
        load_capture("alexdelprete_vsn300_fw201_livedata"),
        password=REST_PASSWORD,
    )


def fake_vsn700() -> FakeVsn:
    """A fake VSN700 with a REACT2, two batteries and a meter, as captured."""
    return FakeVsn(
        "VSN700",
        load_capture("giannicoderani_vsn700_status"),
        load_capture("giannicoderani_vsn700_livedata"),
        password=REST_PASSWORD,
    )


@pytest.fixture
async def serve_rest(
    aiohttp_server: Callable[..., Awaitable[Any]], socket_enabled: None
) -> Callable[[FakeVsn], Awaitable[str]]:
    """Start a fake card on the loopback interface and return ``host:port``."""

    async def start(fake: FakeVsn) -> str:
        server = await aiohttp_server(fake.app())
        return f"{server.host}:{server.port}"

    return start


def rest_entry(host: str, *, use_modbus: bool, title: str, unique_id: str) -> MockConfigEntry:
    """A config entry reading the REST API at ``host``, with or without Modbus."""
    return MockConfigEntry(
        domain=DOMAIN,
        title=title,
        unique_id=unique_id,
        data={
            CONF_HOST: host,
            CONF_PORT: 502,
            CONF_USE_MODBUS: use_modbus,
            CONF_UNIT_ID: 2,
            CONF_BASE_ADDRESS: 0,
            CONF_USE_REST: True,
            CONF_USERNAME: "guest",
            CONF_PASSWORD: REST_PASSWORD,
        },
    )
