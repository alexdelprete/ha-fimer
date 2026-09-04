"""Tests for the pyfimer Modbus client on the modbus-connection mock."""

from __future__ import annotations

from modbus_connection.mock import MockModbusConnection, MockModbusUnit
import pytest

from custom_components.fimer.pyfimer import (
    POINTS_BY_NAME,
    FimerNotDiscoveredError,
    FimerUnsupportedDeviceError,
)
from custom_components.fimer.pyfimer.modbus import (
    FimerModbusInverter,
    OperatingState,
    SunSpecError,
    SunSpecMapShiftError,
)
from custom_components.fimer.pyfimer.modbus.testing import (
    InverterSpec,
    MpptInputSpec,
    VendorSpec,
    build_register_map,
)
from tests.conftest import INVERTER_SPEC, MPPT_INPUTS, SERIAL_NUMBER, VENDOR_SPEC


@pytest.fixture
def unit() -> MockModbusUnit:
    return MockModbusConnection().for_unit(2)


async def discovered(unit: MockModbusUnit, **overrides: object) -> FimerModbusInverter:
    """Load a register map and return a discovered, updated inverter."""
    kwargs: dict[str, object] = {
        "serial_number": SERIAL_NUMBER,
        "inverter": INVERTER_SPEC,
        "mppt_inputs": MPPT_INPUTS,
        "vendor": VENDOR_SPEC,
    }
    kwargs.update(overrides)
    unit.holding.update(build_register_map(**kwargs))  # type: ignore[arg-type]
    inverter = FimerModbusInverter(unit, base_address=kwargs.get("base_address", 0))  # type: ignore[arg-type]
    await inverter.discover()
    await inverter.async_update()
    return inverter


async def test_discover_and_values(unit: MockModbusUnit) -> None:
    inverter = FimerModbusInverter(unit)
    assert not inverter.discovered
    assert inverter.phases is None
    with pytest.raises(FimerNotDiscoveredError):
        await inverter.async_update()
    with pytest.raises(FimerNotDiscoveredError):
        await inverter.async_read_raw()
    with pytest.raises(FimerNotDiscoveredError):
        _ = inverter.identity

    inverter = await discovered(unit)
    assert inverter.discovered
    assert inverter.base_address == 0
    assert [(m.model_id, m.address, m.length) for m in inverter.model_chain] == [
        (1, 2, 66),
        (103, 70, 50),
        (160, 122, 48),
        (64061, 172, 124),
    ]
    assert inverter.phases == 3
    assert inverter.vendor_model_length == 124

    identity = inverter.identity
    assert identity.manufacturer == "ABB"
    assert identity.device_model == "VSN300"
    assert identity.inverter_model == "PVI-10.0-OUTD"
    assert identity.model == "PVI-10.0-OUTD"
    assert identity.serial_number == SERIAL_NUMBER
    assert identity.firmware_version == "1.9.2"

    values = inverter.values()
    assert set(values) <= set(POINTS_BY_NAME)
    assert values["W"] == 1500
    assert values["A"] == 6.54
    assert values["PhVphAB"] == 400.1
    assert values["Hz"] == 50.02
    assert values["WH"] == 1234567
    assert values["DCV"] is None
    assert values["TmpCab"] == 45.3  # tenfold quirk corrected
    assert values["TmpOt"] == 41.2
    assert values["St"] is OperatingState.MPPT
    assert values["StVnd"] == 2
    assert values["N"] == 2
    assert values["DCA_1"] == 3.21
    assert values["DCV_2"] == 340.0
    assert values["DCW_2"] == 750
    assert values["DCWH_1"] is None
    assert "DCA_3" not in values
    assert values["GlobalSt"] == 6
    assert values["Alarms"] == ["Sun Low", "Grid OV", "Energy data reset"]
    assert values["SysTime"] == 800000000 + 946684800
    assert values["DayWH"] == 12345.0
    assert values["Booster_Tmp"] == 50.25
    assert values["Isolation_Ohm1"] == 12.5
    assert values["Isolation_Ohm2"] is None
    assert values["OutputW_Perm"] == 100
    assert values["OutputW_Dynamic"] is None

    raw = await inverter.async_read_raw()
    assert raw["holding"][0] == 0x5375
    assert raw["holding"][172] == 64061


async def test_reads_are_pooled_and_capped(unit: MockModbusUnit) -> None:
    """One update reads every model in a few block reads no wider than 64 registers."""
    inverter = await discovered(unit)
    unit.read_events.clear()
    await inverter.async_update()
    assert 0 < len(unit.read_events) <= 8
    assert all(event.count <= 64 for event in unit.read_events)


async def test_single_phase_native_inverter(unit: MockModbusUnit) -> None:
    inverter = await discovered(
        unit,
        base_address=40000,
        three_phase=False,
        options="0x0D",
        include_mppt_model=False,
        include_vendor_model=False,
    )
    assert inverter.phases == 1
    assert inverter.identity.model == "REACT2-UNO-5.0-TL"
    assert inverter.mppt is None
    assert inverter.vendor is None
    assert inverter.vendor_model_length is None
    values = inverter.values()
    assert values["W"] == 1500
    assert "DCA_1" not in values
    assert "GlobalSt" not in values


async def test_unknown_model_code(unit: MockModbusUnit) -> None:
    inverter = await discovered(unit, options="?")
    assert inverter.identity.inverter_model is None
    assert inverter.identity.model == "VSN300"


async def test_vendor_model_with_unexpected_length_is_skipped(unit: MockModbusUnit) -> None:
    inverter = await discovered(unit, vendor_model_length=140)
    assert inverter.vendor is None
    assert inverter.vendor_model_length == 140
    assert "GlobalSt" not in inverter.values()

    unit.holding.clear()
    inverter = await discovered(unit, vendor_model_length=100)
    assert inverter.vendor is None
    assert inverter.vendor_model_length == 100


async def test_mppt_energy_when_implemented(unit: MockModbusUnit) -> None:
    inverter = await discovered(
        unit,
        mppt_inputs=[MpptInputSpec("A", 1.0, 300.0, 300, energy=4321, operating_state=4)],
        mppt_energy_implemented=True,
    )
    values = inverter.values()
    assert values["DCWH_1"] == 4321
    assert values["DCSt_1"] == 4


async def test_no_sunspec_marker(unit: MockModbusUnit) -> None:
    with pytest.raises(SunSpecError):
        await FimerModbusInverter(unit).discover()


async def test_no_inverter_model(unit: MockModbusUnit) -> None:
    unit.holding.update(
        build_register_map(
            include_inverter_model=False, include_mppt_model=False, include_vendor_model=False
        )
    )
    with pytest.raises(FimerUnsupportedDeviceError, match="models \\[1\\]"):
        await FimerModbusInverter(unit).discover()


async def test_map_shift_is_detected_and_recovered(unit: MockModbusUnit) -> None:
    inverter = await discovered(unit)
    unit.holding.clear()
    unit.holding.update(
        build_register_map(serial_number=SERIAL_NUMBER, inverter=INVERTER_SPEC, three_phase=False)
    )
    with pytest.raises(SunSpecMapShiftError):
        await inverter.async_update()
    await inverter.discover()
    await inverter.async_update()
    assert inverter.phases == 1
    assert inverter.values()["W"] == 1500


def test_builder_specs_default_to_not_implemented() -> None:
    registers = build_register_map(inverter=InverterSpec(), vendor=VendorSpec())
    assert registers[70] == 103
    assert registers[70 + 2] == 0xFFFF  # A not implemented
    assert registers[172 + 1] == 124
    assert registers[registers[1 + 1] and 298] == 0xFFFF  # end marker
