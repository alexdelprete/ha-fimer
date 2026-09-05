"""SunSpec models 1, 101/102/103, 120, 121, 123 and 160 as read from FIMER inverters.

Attribute names are the point names of :mod:`pyfimer.points`, not Python
style, so a component's readings can be emitted without a rename table.
Register offsets are relative to the model header and follow the official
SunSpec model definitions; the ``PhVph*`` spelling of the phase-to-phase
voltages follows the VSN REST mapping rather than the register names.
"""

from __future__ import annotations

from enum import IntEnum, IntFlag
from typing import Any, ClassVar

from modbus_connection.model import Component, repeating_group
from modbus_connection.model.sunspec import (
    SunSpecComponent,
    acc32,
    bitfield32,
    enum16,
    int16,
    string,
    uint16,
    uint32,
)

from .sunspec import MAX_READ_SPAN

TMP_CAB_PLAUSIBLE_MAX: float = 70.0
"""Cabinet temperatures above this are read with the wrong scale factor.

Some PVI firmwares report ``Tmp_SF`` as -1 while encoding the cabinet
temperature with -2, which shows up as a tenfold reading. A cabinet hotter
than this is not plausible, so such readings are divided by ten.
"""


class OperatingState(IntEnum):
    """SunSpec inverter operating state (``St``)."""

    OFF = 1
    SLEEPING = 2
    STARTING = 3
    MPPT = 4
    THROTTLED = 5
    SHUTTING_DOWN = 6
    FAULT = 7
    STANDBY = 8


class Event1(IntFlag):
    """SunSpec inverter events (``Evt1``)."""

    GROUND_FAULT = 1 << 0
    DC_OVER_VOLT = 1 << 1
    AC_DISCONNECT = 1 << 2
    DC_DISCONNECT = 1 << 3
    GRID_DISCONNECT = 1 << 4
    CABINET_OPEN = 1 << 5
    MANUAL_SHUTDOWN = 1 << 6
    OVER_TEMP = 1 << 7
    OVER_FREQUENCY = 1 << 8
    UNDER_FREQUENCY = 1 << 9
    AC_OVER_VOLT = 1 << 10
    AC_UNDER_VOLT = 1 << 11
    BLOWN_STRING_FUSE = 1 << 12
    UNDER_TEMP = 1 << 13
    MEMORY_LOSS = 1 << 14
    HW_TEST_FAILURE = 1 << 15


class MpptOperatingState(IntEnum):
    """SunSpec MPPT input operating state (``DCSt``)."""

    OFF = 1
    SLEEPING = 2
    STARTING = 3
    MPPT = 4
    THROTTLED = 5
    SHUTTING_DOWN = 6
    FAULT = 7
    STANDBY = 8
    TEST = 9


class FimerComponent(SunSpecComponent):
    """A SunSpec model that reports its readings by point name."""

    max_span = MAX_READ_SPAN

    POINT_NAMES: ClassVar[tuple[str, ...]] = ()
    """The attributes :meth:`values` emits, in vocabulary order."""

    def values(self) -> dict[str, Any]:
        """Return the last readings keyed by point name."""
        return {name: getattr(self, name) for name in self.POINT_NAMES}


class Common(FimerComponent):
    """SunSpec model 1: device identification.

    Behind a VSN datalogger the card answers for itself here (``Mn`` "ABB",
    ``Md`` "VSN300"); the inverter model is encoded in ``Opt``.
    """

    POINT_NAMES = ("Mn", "Md", "Opt", "Vr", "SN", "DA")

    Mn = string(2, 16)
    Md = string(18, 16)
    Opt = string(34, 8)
    Vr = string(42, 8)
    SN = string(50, 16)
    DA = uint16(66)


class Inverter(FimerComponent):
    """SunSpec models 101, 102 and 103: the integer + scale factor inverter.

    The three models share one layout; a single-phase inverter leaves the
    phase B and C points unimplemented.
    """

    POINT_NAMES = (
        "A",
        "AphA",
        "AphB",
        "AphC",
        "PhVphAB",
        "PhVphBC",
        "PhVphCA",
        "PhVphA",
        "PhVphB",
        "PhVphC",
        "W",
        "Hz",
        "VA",
        "VAr",
        "PF",
        "WH",
        "DCA",
        "DCV",
        "DCW",
        "TmpCab",
        "TmpSnk",
        "TmpTrns",
        "TmpOt",
        "St",
        "StVnd",
        "Evt1",
        "EvtVnd1",
        "EvtVnd2",
        "EvtVnd3",
        "EvtVnd4",
    )

    A = uint16(2, scale_register=6, unit="A")
    AphA = uint16(3, scale_register=6, unit="A")
    AphB = uint16(4, scale_register=6, unit="A")
    AphC = uint16(5, scale_register=6, unit="A")
    PhVphAB = uint16(7, scale_register=13, unit="V")
    PhVphBC = uint16(8, scale_register=13, unit="V")
    PhVphCA = uint16(9, scale_register=13, unit="V")
    PhVphA = uint16(10, scale_register=13, unit="V")
    PhVphB = uint16(11, scale_register=13, unit="V")
    PhVphC = uint16(12, scale_register=13, unit="V")
    W = int16(14, scale_register=15, unit="W")
    Hz = uint16(16, scale_register=17, unit="Hz")
    VA = int16(18, scale_register=19, unit="VA")
    VAr = int16(20, scale_register=21, unit="var")
    PF = int16(22, scale_register=23, unit="%")
    WH = acc32(24, scale_register=26, unit="Wh")
    DCA = uint16(27, scale_register=28, unit="A")
    DCV = uint16(29, scale_register=30, unit="V")
    DCW = int16(31, scale_register=32, unit="W")
    TmpCab = int16(33, scale_register=37, unit="°C")
    TmpSnk = int16(34, scale_register=37, unit="°C")
    TmpTrns = int16(35, scale_register=37, unit="°C")
    TmpOt = int16(36, scale_register=37, unit="°C")
    St = enum16(38, OperatingState)
    StVnd = enum16(39)
    Evt1 = bitfield32(40, Event1)
    Evt2 = bitfield32(42)
    EvtVnd1 = bitfield32(44)
    EvtVnd2 = bitfield32(46)
    EvtVnd3 = bitfield32(48)
    EvtVnd4 = bitfield32(50)

    def values(self) -> dict[str, Any]:
        """Return the readings, correcting the known cabinet temperature quirk."""
        values = super().values()
        tmp_cab = values["TmpCab"]
        if tmp_cab is not None and tmp_cab > TMP_CAB_PLAUSIBLE_MAX:
            values["TmpCab"] = tmp_cab / 10
        return values


class MpptInput(Component):
    """One input block of SunSpec model 160, declared at the first block.

    The scale factors are shared by every input and sit in the model's
    fixed block.
    """

    ID = uint16(10)
    IDStr = string(11, 8)
    DCA = uint16(19, scale_register=2, unit="A")
    DCV = uint16(20, scale_register=3, unit="V")
    DCW = uint16(21, scale_register=4, unit="W")
    DCWH = acc32(22, scale_register=5, unit="Wh")
    Tms = uint32(24)
    Tmp = int16(26, unit="°C")
    DCSt = enum16(27, MpptOperatingState)
    DCEvt = bitfield32(28)


class Mppt(FimerComponent):
    """SunSpec model 160: per-input DC readings.

    On PVI and TRIO inverters behind a VSN card ``DCWH`` reads 0 (not
    implemented) and ``DCWH_SF`` is unimplemented, so per-input energy is
    not available over Modbus.
    """

    POINT_NAMES = ("N",)
    INPUT_POINT_NAMES: ClassVar[tuple[str, ...]] = ("DCA", "DCV", "DCW", "DCWH", "DCSt")

    Evt = bitfield32(6)
    N = uint16(8)
    TmsPer = uint16(9)
    inputs = repeating_group(uint16(8), MpptInput, stride=20)

    def values(self) -> dict[str, Any]:
        """Return the readings with the inputs numbered from 1."""
        values = super().values()
        for number, mppt_input in enumerate(self.inputs, start=1):
            for name in self.INPUT_POINT_NAMES:
                values[f"{name}_{number}"] = getattr(mppt_input, name)
        return values


class DerType(IntEnum):
    """SunSpec DER type (``DERTyp``)."""

    PV = 4
    PV_STORAGE = 82


class Nameplate(FimerComponent):
    """SunSpec model 120: the inverter's ratings.

    A VSN300 in front of a PVI implements only the rated power.
    """

    POINT_NAMES = ("DERTyp", "WRtg", "VARtg", "ARtg", "WhRtg")

    DERTyp = enum16(2, DerType)
    WRtg = uint16(3, scale_register=4, unit="W")
    VARtg = uint16(5, scale_register=6, unit="VA")
    ARtg = uint16(12, scale_register=13, unit="A")
    WhRtg = uint16(19, scale_register=20, unit="Wh")


class Settings(FimerComponent):
    """SunSpec model 121: basic settings, largely unimplemented on PVI inverters."""

    POINT_NAMES = ("WMax", "VRef", "VMax", "VMin", "VAMax", "WGra", "ECPNomHz")

    WMax = uint16(2, scale_register=22, writable=True, unit="W")
    VRef = uint16(3, scale_register=23, writable=True, unit="V")
    VMax = uint16(5, scale_register=25, writable=True, unit="V")
    VMin = uint16(6, scale_register=25, writable=True, unit="V")
    VAMax = uint16(7, scale_register=26, writable=True, unit="VA")
    WGra = uint16(12, scale_register=28, writable=True, unit="%")
    ECPNomHz = uint16(20, scale_register=31, writable=True, unit="Hz")


class Connection(IntEnum):
    """Grid connection command and state (``Conn``)."""

    DISCONNECT = 0
    CONNECT = 1


class Enabled(IntEnum):
    """Enable flag of a control (``WMaxLim_Ena``, ``OutPFSet_Ena``)."""

    DISABLED = 0
    ENABLED = 1


class Controls(FimerComponent):
    """SunSpec model 123: immediate controls, the standard way to limit power.

    A VSN300 in front of a PVI implements the power limit (``WMaxLimPct``
    with its revert and ramp times and enable flag) and leaves the power
    factor and reactive power setpoints unimplemented.
    """

    POINT_NAMES = (
        "Conn",
        "WMaxLimPct",
        "WMaxLimPct_RvrtTms",
        "WMaxLimPct_RmpTms",
        "WMaxLim_Ena",
        "OutPFSet",
        "OutPFSet_Ena",
    )

    Conn = enum16(4, Connection, writable=True)
    WMaxLimPct = uint16(5, scale_register=23, writable=True, unit="%")
    WMaxLimPct_WinTms = uint16(6, writable=True)
    WMaxLimPct_RvrtTms = uint16(7, writable=True)
    WMaxLimPct_RmpTms = uint16(8, writable=True)
    WMaxLim_Ena = enum16(9, Enabled, writable=True)
    OutPFSet = int16(10, scale_register=24, writable=True)
    OutPFSet_WinTms = uint16(11, writable=True)
    OutPFSet_RvrtTms = uint16(12, writable=True)
    OutPFSet_RmpTms = uint16(13, writable=True)
    OutPFSet_Ena = enum16(14, Enabled, writable=True)

    async def set_power_limit(self, percent: float | None) -> None:
        """Limit the output to ``percent`` of the rated power, or lift the limit.

        The model is refreshed first so the scale factor is known and a
        shifted register map is caught before anything is written.
        """
        await self.async_update()
        if percent is None:
            await self.write("WMaxLim_Ena", Enabled.DISABLED)
            return
        if not 0 <= percent <= 100:
            raise ValueError(f"percent must be 0..100, got {percent}")
        await self.write("WMaxLimPct", percent)
        await self.write("WMaxLim_Ena", Enabled.ENABLED)

    async def set_power_factor(self, cos_phi: float | None) -> None:
        """Set the power factor setpoint, or lift it.

        Raises ``ValueError`` when the inverter does not implement the
        setpoint's scale factor, as a PVI behind a VSN300 does not.
        """
        await self.async_update()
        if cos_phi is None:
            await self.write("OutPFSet_Ena", Enabled.DISABLED)
            return
        if not -1.0 <= cos_phi <= 1.0:
            raise ValueError(f"cos phi must be -1..1, got {cos_phi}")
        await self.write("OutPFSet", cos_phi)
        await self.write("OutPFSet_Ena", Enabled.ENABLED)
