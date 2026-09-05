"""Tests for the pyfimer Modbus client on the modbus-connection mock."""

from __future__ import annotations

import json
from pathlib import Path

from modbus_connection.mock import MockModbusConnection, MockModbusUnit
import pytest

from custom_components.fimer.pyfimer import (
    POINTS_BY_NAME,
    FimerNotDiscoveredError,
    FimerUnsupportedDeviceError,
)
from custom_components.fimer.pyfimer.modbus import (
    Enabled,
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

FIXTURES = Path(__file__).parent.parent / "fixtures"


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
        "include_vendor_model": True,
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
        (120, 172, 26),
        (121, 200, 30),
        (123, 232, 24),
        (64061, 258, 124),
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

    assert values["Inverter_CosPhi"] == 0.995

    raw = await inverter.async_read_raw()
    assert raw["holding"][2] == 1
    assert raw["holding"][258] == 64061


async def test_reads_are_pooled_and_capped(unit: MockModbusUnit) -> None:
    """One update reads every model in a few block reads no wider than 64 registers."""
    inverter = await discovered(unit)
    unit.read_events.clear()
    await inverter.async_update()
    assert 0 < len(unit.read_events) <= 10
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
            include_inverter_model=False,
            include_mppt_model=False,
            include_nameplate_model=False,
            include_settings_model=False,
            include_controls_model=False,
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
    registers = build_register_map(
        inverter=InverterSpec(), vendor=VendorSpec(), include_vendor_model=True
    )
    assert registers[70] == 103
    assert registers[70 + 2] == 0xFFFF  # A not implemented
    assert registers[258 + 1] == 124
    assert registers[258 + 2 + 124] == 0xFFFF  # end marker


async def test_write_points(unit: MockModbusUnit) -> None:
    inverter = FimerModbusInverter(unit)
    with pytest.raises(FimerNotDiscoveredError):
        await inverter.async_write("OutputW_Dynamic", 50)

    inverter = await discovered(unit)
    await inverter.async_write("OutputW_Dynamic", 50)
    assert unit.holding[258 + 104] == 50
    await inverter.async_write("PF_Perm", 0.5)
    assert (unit.holding[258 + 96], unit.holding[258 + 97]) == (0x3F00, 0)

    with pytest.raises(AttributeError):
        await inverter.async_write("W", 1)  # read-only
    with pytest.raises(AttributeError):
        await inverter.async_write("NoSuchPoint", 1)

    await inverter.async_update()
    assert inverter.values()["OutputW_Dynamic"] == 50
    assert inverter.values()["PF_Perm"] == 0.5


async def test_vendor_control_helpers(unit: MockModbusUnit) -> None:
    inverter = await discovered(unit)
    vendor = inverter.vendor
    assert vendor is not None

    await vendor.set_output_power_limit(80)
    await vendor.set_output_power_limit(60, permanent=True)
    await vendor.set_power_factor(0.9)
    await vendor.set_power_factor(-0.95, permanent=True)
    await vendor.set_system_time(946684800 + 100)
    assert unit.holding[258 + 104] == 80
    assert unit.holding[258 + 94] == 60
    assert (unit.holding[258 + 20], unit.holding[258 + 21]) == (0, 100)
    await inverter.async_update()
    values = inverter.values()
    assert values["OutputW_Dynamic"] == 80
    assert values["OutputW_Perm"] == 60
    assert values["PF_Dynamic"] == 0.9
    assert values["PF_Perm"] == -0.95
    assert values["SysTime"] == 946684800 + 100

    await vendor.reset_output_power_limit()
    await vendor.reset_power_factor()
    assert unit.holding[258 + 114] == 1
    assert unit.holding[258 + 116] == 1

    with pytest.raises(ValueError):
        await vendor.set_output_power_limit(101)
    with pytest.raises(ValueError):
        await vendor.set_power_factor(1.5)
    with pytest.raises(ValueError):
        await vendor.set_system_time(0)


async def test_registers_available_before_discovery(unit: MockModbusUnit) -> None:
    unit.holding[500] = 7
    inverter = FimerModbusInverter(unit)
    assert await inverter.registers.read_uint16(500) == 7
    await inverter.registers.write_uint16(501, 9)
    assert unit.holding[501] == 9


async def test_real_vsn300_capture(unit: MockModbusUnit) -> None:
    """The chain a VSN300 (firmware 2.0.1) serves for a PVI-10.0-OUTD, as captured."""
    fixture = json.loads(FIXTURES.joinpath("vsn300_pvi10_fw201.json").read_text())
    unit.load_raw(
        {"holding": {int(address): value for address, value in fixture["holding"].items()}}
    )
    inverter = FimerModbusInverter(unit, base_address=fixture["base_address"])
    await inverter.discover()
    await inverter.async_update()

    assert [model.model_id for model in inverter.model_chain] == [1, 103, 160, 120, 121, 123]
    assert inverter.vendor is None
    assert inverter.vendor_model_length is None
    identity = inverter.identity
    assert identity.manufacturer == "Power-One"
    assert identity.device_model == "-3G82-"
    assert identity.model == "PVI-10.0-OUTD"
    assert identity.firmware_version == "C008"
    assert inverter.phases == 3

    values = inverter.values()
    assert values["W"] == 3076
    assert values["WH"] == 114903600
    assert values["Hz"] == 50.02
    assert values["TmpCab"] == 24.82  # served with the wrong scale factor
    assert values["TmpOt"] == 48.6
    assert values["St"] is OperatingState.MPPT
    assert values["N"] == 2
    assert values["DCW_1"] == 1685
    assert values["DCW_2"] == 1487
    assert values["WRtg"] == 10000
    assert values["WMaxLimPct"] == 100
    assert values["WMaxLimPct_RvrtTms"] == 60
    assert values["WMaxLim_Ena"] is Enabled.DISABLED
    unimplemented = {name for name, value in values.items() if value is None}
    assert {
        "VA",
        "VAr",
        "PF",
        "DCA",
        "DCV",
        "TmpSnk",
        "TmpTrns",
        "DCWH_1",
        "OutPFSet",
    } <= unimplemented
    assert "GlobalSt" not in values


async def test_power_limit(unit: MockModbusUnit) -> None:
    inverter = await discovered(unit)
    controls = inverter.controls
    assert controls is not None
    assert inverter.nameplate is not None
    assert inverter.settings is not None

    await controls.set_power_limit(70)
    assert unit.holding[232 + 5] == 70
    assert unit.holding[232 + 9] == 1
    await inverter.async_update()
    assert inverter.values()["WMaxLimPct"] == 70
    assert inverter.values()["WMaxLim_Ena"] is Enabled.ENABLED

    await controls.set_power_limit(None)
    assert unit.holding[232 + 9] == 0

    with pytest.raises(ValueError):
        await controls.set_power_limit(101)
    # the PVI does not implement the power factor setpoint's scale factor
    with pytest.raises(ValueError):
        await controls.set_power_factor(0.9)
    with pytest.raises(ValueError):
        await controls.set_power_factor(1.5)
    await controls.set_power_factor(None)
    assert unit.holding[232 + 14] == 0


async def test_power_factor_when_implemented(unit: MockModbusUnit) -> None:
    inverter = await discovered(unit, power_factor_implemented=True)
    controls = inverter.controls
    assert controls is not None
    await controls.set_power_factor(0.95)
    assert unit.holding[232 + 10] == 950
    assert unit.holding[232 + 14] == 1
    await inverter.async_update()
    assert inverter.values()["OutPFSet"] == 0.95
