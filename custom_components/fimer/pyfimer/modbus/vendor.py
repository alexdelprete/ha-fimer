"""SunSpec vendor model 64061: the ABB / Power-One inverter block.

Hand-written from the 2013 Power-One "ABB SunSpec Inverter Modbus Map"
workbook (model length 124). The VSN300 REST feed names further points in
this model (``VBulk``, ``VBulkMid``, ``VGnd``, ``ILeakDcAc``, ``ILeakDcDc``,
``AlarmSt``) that the workbook does not know; they are left out until a
register capture from current firmware shows where they live.

Offsets are relative to the model header (ID at 0, L at 1), so the
workbook's data offsets are shifted by two.
"""

# ruff: noqa: TID252 - attribute names are the shared SunSpec point vocabulary;
# parent-relative imports keep the package movable to PyPI

from __future__ import annotations

from enum import IntFlag
from typing import Any

from modbus_connection.model.sunspec import (
    bitfield16,
    bitfield32,
    enum16,
    float32,
    string,
    uint16,
    uint32,
)

from ..aurora import AURORA_EPOCH_OFFSET, decode_alarms
from .models import FimerComponent


class DevicePresence(IntFlag):
    """Boards the inverter reports as fitted (``DevicePresence``)."""

    DISPLAY = 1 << 0
    COMM_BOARD = 1 << 1
    FUSE_CONTROL_BOARD = 1 << 2
    INVERTER = 1 << 3


class AbbVendor(FimerComponent):
    """The ABB vendor model: Aurora states, alarms, energy counters, extras."""

    POINT_NAMES = (
        "HwVersion",
        "Parent",
        "DevicePresence",
        "GlobalSt",
        "InverterSt",
        "DcSt1",
        "DcSt2",
        "Alarm1",
        "Alarm2",
        "Alarm3",
        "DayWH",
        "TotalWH",
        "PartialWH",
        "WeekWH",
        "MonthWH",
        "YearWH",
        "AC_V",
        "AC_A",
        "AC_W",
        "AC_Hz",
        "DC1_W",
        "DC1_V",
        "DC1_A",
        "DC2_W",
        "DC2_V",
        "DC2_A",
        "Tmp",
        "Booster_Tmp",
        "Isolation_Ohm1",
        "Isolation_Ohm2",
        "WindGen_Hz",
        "Inverter_CosPhi",
        "OutputW_Perm",
        "OutputW_Dynamic",
        "PF_Perm",
        "PF_Dynamic",
    )

    # Status block
    Version = uint16(2)
    HwVersion = string(3, 4)
    Parent = string(7, 8)
    DevicePresence = bitfield16(15, DevicePresence)
    GlobalSt = enum16(16)
    InverterSt = enum16(17)
    DcSt1 = enum16(18)
    DcSt2 = enum16(19)
    SysTime = uint32(20, writable=True)
    Alarm1 = bitfield32(22)
    Alarm2 = bitfield32(24)
    Alarm3 = bitfield32(26)
    # Alarm4..Alarm8 at 28..36 are unused in practice and not declared.

    # Measurement block: IEEE-754 floats, SunSpec (big-endian) word order.
    DayWH = float32(38, unit="Wh")
    TotalWH = float32(40, unit="Wh")
    PartialWH = float32(42, unit="Wh")
    WeekWH = float32(44, unit="Wh")
    MonthWH = float32(46, unit="Wh")
    YearWH = float32(48, unit="Wh")
    AC_V = float32(50, unit="V")
    AC_A = float32(52, unit="A")
    AC_W = float32(54, unit="W")
    AC_Hz = float32(56, unit="Hz")
    DC1_W = float32(58, unit="W")
    DC1_V = float32(60, unit="V")
    DC1_A = float32(62, unit="A")
    DC2_W = float32(64, unit="W")
    DC2_V = float32(66, unit="V")
    DC2_A = float32(68, unit="A")
    Tmp = float32(70, unit="°C")
    Booster_Tmp = float32(72, unit="°C")
    Isolation_Ohm1 = float32(74, unit="MΩ")
    Isolation_Ohm2 = float32(76, unit="MΩ")
    WindGen_Hz = float32(78, unit="Hz")
    Inverter_CosPhi = float32(80)

    # Control block. Writable per the 2013 map; writes are not yet verified on
    # hardware, so treat :meth:`set_output_power_limit` and friends as
    # experimental until a device has acknowledged them.
    OutputW_Ramp = uint16(86, writable=True)
    OutputW_Timeout = uint16(87, writable=True)
    PF_Ramp = uint16(88, writable=True)
    PF_Timeout = uint16(89, writable=True)
    OutputW_Perm = uint16(94, unit="%", writable=True)
    OutputW_Perm_St = enum16(95)
    PF_Perm = float32(96, writable=True)
    PF_Perm_St = enum16(98)
    OutputW_Dynamic = uint16(104, unit="%", writable=True)
    OutputW_Dynamic_St = enum16(105)
    PF_Dynamic = float32(106, writable=True)
    PF_Dynamic_St = enum16(108)
    OutputW_Reset = enum16(114, writable=True)
    OutputW_Reset_St = enum16(115)
    PF_Reset = enum16(116, writable=True)
    PF_Reset_St = enum16(117)

    async def set_output_power_limit(self, percent: int, *, permanent: bool = False) -> None:
        """Limit the output power to ``percent`` of nominal, dynamically or permanently."""
        if not 0 <= percent <= 100:
            raise ValueError(f"percent must be 0..100, got {percent}")
        await self.write("OutputW_Perm" if permanent else "OutputW_Dynamic", percent)

    async def reset_output_power_limit(self) -> None:
        """Return the output power to nominal."""
        await self.write("OutputW_Reset", 1)

    async def set_power_factor(self, cos_phi: float, *, permanent: bool = False) -> None:
        """Set the power factor setpoint, dynamically or permanently."""
        if not -1.0 <= cos_phi <= 1.0:
            raise ValueError(f"cos phi must be -1..1, got {cos_phi}")
        await self.write("PF_Perm" if permanent else "PF_Dynamic", cos_phi)

    async def reset_power_factor(self) -> None:
        """Return the power factor to nominal."""
        await self.write("PF_Reset", 1)

    async def set_system_time(self, unix_time: int) -> None:
        """Set the inverter clock from a Unix timestamp."""
        if unix_time < AURORA_EPOCH_OFFSET:
            raise ValueError("time is before the Aurora epoch (2000-01-01)")
        await self.write("SysTime", unix_time - AURORA_EPOCH_OFFSET)

    def values(self) -> dict[str, Any]:
        """Return the readings plus the decoded alarms and a Unix system time.

        Floats are trimmed to the seven significant digits a float32 carries,
        so 0.995 does not surface as 0.995000004768372.
        """
        values = {
            name: float(f"{value:.7g}") if isinstance(value, float) else value
            for name, value in super().values().items()
        }
        values["Alarms"] = decode_alarms(self.Alarm1, self.Alarm2, self.Alarm3)
        sys_time = self.SysTime
        values["SysTime"] = None if sys_time is None else sys_time + AURORA_EPOCH_OFFSET
        return values
