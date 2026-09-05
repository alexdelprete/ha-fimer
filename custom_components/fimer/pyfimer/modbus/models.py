"""SunSpec models 1, 101/102/103, 111/112/113, 120, 121, 123, 124 and 160 as read from FIMER inverters.

Attribute names are the point names of :mod:`pyfimer.points`, not Python
style, so a component's readings can be emitted without a rename table.
Register offsets are relative to the model header and follow the official
SunSpec model definitions; the ``PhVph*`` spelling of the phase-to-phase
voltages follows the VSN REST mapping rather than the register names.
"""

# ruff: noqa: TID252 - attribute names are the shared SunSpec point vocabulary;
# parent-relative imports keep the package movable to PyPI

from __future__ import annotations

from enum import IntEnum, IntFlag
import math
from typing import Any, ClassVar

from modbus_connection import ModbusExceptionError
from modbus_connection.model import Component, repeating_group
from modbus_connection.model.sunspec import (
    SunSpecComponent,
    acc32,
    bitfield16,
    bitfield32,
    enum16,
    float32,
    int16,
    string,
    uint16,
    uint32,
)

from ..exceptions import FimerWriteError
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


class FixedComponent(Component):
    """A register layout at absolute addresses, outside any SunSpec model.

    Declare fields at their absolute register addresses (or pass
    ``base_offset`` at construction to place a relative layout), name the
    attributes after vocabulary points, and hand an instance to
    :meth:`FimerModbusInverter.add_component` to have it polled with the
    SunSpec models::

        class UnoDmMppt(FixedComponent):
            POINT_NAMES = ("DCV_1",)
            DCV_1 = uint16(1104, scale_register=1103, unit="V")


        inverter.add_component(UnoDmMppt(unit))
    """

    max_span = MAX_READ_SPAN

    POINT_NAMES: ClassVar[tuple[str, ...]] = ()
    """The attributes :meth:`values` emits."""

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
        values["Events"] = event_names(values["Evt1"])
        return values


def event_names(events: Any) -> list[str]:
    """Return the names of the SunSpec events set in an ``Evt1`` bitfield."""
    if not events:
        return []
    bits = int(events)
    return [flag.name.lower() for flag in Event1 if flag.name and bits & flag]


class InverterFloat(FimerComponent):
    """SunSpec models 111, 112 and 113: the float inverter models.

    Natively Modbus inverters can serve these instead of the integer ones;
    the points are the same, so :attr:`POINT_NAMES` matches :class:`Inverter`.
    """

    POINT_NAMES = Inverter.POINT_NAMES

    A = float32(2, unit="A")
    AphA = float32(4, unit="A")
    AphB = float32(6, unit="A")
    AphC = float32(8, unit="A")
    PhVphAB = float32(10, unit="V")
    PhVphBC = float32(12, unit="V")
    PhVphCA = float32(14, unit="V")
    PhVphA = float32(16, unit="V")
    PhVphB = float32(18, unit="V")
    PhVphC = float32(20, unit="V")
    W = float32(22, unit="W")
    Hz = float32(24, unit="Hz")
    VA = float32(26, unit="VA")
    VAr = float32(28, unit="var")
    PF = float32(30, unit="%")
    WH = float32(32, unit="Wh")
    DCA = float32(34, unit="A")
    DCV = float32(36, unit="V")
    DCW = float32(38, unit="W")
    TmpCab = float32(40, unit="°C")
    TmpSnk = float32(42, unit="°C")
    TmpTrns = float32(44, unit="°C")
    TmpOt = float32(46, unit="°C")
    St = enum16(48, OperatingState)
    StVnd = enum16(49)
    Evt1 = bitfield32(50, Event1)
    Evt2 = bitfield32(52)
    EvtVnd1 = bitfield32(54)
    EvtVnd2 = bitfield32(56)
    EvtVnd3 = bitfield32(58)
    EvtVnd4 = bitfield32(60)

    def values(self) -> dict[str, Any]:
        """Return the readings trimmed to the seven significant digits of a float32."""
        values = {
            name: float(f"{value:.7g}") if isinstance(value, float) else value
            for name, value in super().values().items()
        }
        values["Events"] = event_names(values["Evt1"])
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


class ReactivePowerMode(IntEnum):
    """Which reference the reactive power setpoint is a percentage of (``VArPct_Mod``)."""

    NONE = 0
    WMAX = 1
    VAR_MAX = 2
    VAR_AVAL = 3


class Controls(FimerComponent):
    """SunSpec model 123: immediate controls, the standard way to limit power.

    A VSN300 in front of a PVI implements the power limit (``WMaxLimPct``
    with its revert and ramp times and enable flag) and leaves the power
    factor and reactive power setpoints unimplemented.

    Tested live on a PVI-10.0-OUTD (firmware C008) behind a VSN300 on
    firmware 2.0.1: the card stores the limit and the enable flag, and
    reads them back, but answers every write of the enable flag with a
    Modbus negative acknowledge (exception 7) and the inverter keeps
    producing at full power. Treat the write helpers as functional only
    on devices that have been seen to honour them.
    """

    POINT_NAMES = (
        "Conn",
        "WMaxLimPct",
        "WMaxLimPct_RvrtTms",
        "WMaxLimPct_RmpTms",
        "WMaxLim_Ena",
        "OutPFSet",
        "OutPFSet_Ena",
        "VArWMaxPct",
        "VArMaxPct",
        "VArAvalPct",
        "VArPct_RvrtTms",
        "VArPct_RmpTms",
        "VArPct_Mod",
        "VArPct_Ena",
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
    VArWMaxPct = int16(15, scale_register=25, writable=True, unit="%")
    VArMaxPct = int16(16, scale_register=25, writable=True, unit="%")
    VArAvalPct = int16(17, scale_register=25, writable=True, unit="%")
    VArPct_WinTms = uint16(18, writable=True)
    VArPct_RvrtTms = uint16(19, writable=True)
    VArPct_RmpTms = uint16(20, writable=True)
    VArPct_Mod = enum16(21, ReactivePowerMode, writable=True)
    VArPct_Ena = enum16(22, Enabled, writable=True)

    async def apply_power_limit(
        self, *, percent: float | None = None, enabled: bool | None = None
    ) -> None:
        """Write the power limit and/or its enable flag, verified by readback.

        ``percent`` sets ``WMaxLimPct``; ``enabled`` sets ``WMaxLim_Ena``.
        Either may be left out to keep the current value. The model is
        refreshed first so the scale factor is known and a shifted register
        map is caught before anything is written.
        """
        writes: dict[str, Any] = {}
        if percent is not None:
            if not 0 <= percent <= 100:
                raise ValueError(f"percent must be 0..100, got {percent}")
            writes["WMaxLimPct"] = percent
        if enabled is not None:
            writes["WMaxLim_Ena"] = Enabled.ENABLED if enabled else Enabled.DISABLED
        await self._write_verified(writes)

    async def set_power_limit(self, percent: float | None) -> None:
        """Limit the output to ``percent`` of the rated power, or lift the limit."""
        if percent is None:
            await self.apply_power_limit(enabled=False)
        else:
            await self.apply_power_limit(percent=percent, enabled=True)

    async def set_power_factor(self, cos_phi: float | None) -> None:
        """Set the power factor setpoint, or lift it.

        Raises ``ValueError`` when the inverter does not implement the
        setpoint's scale factor, as a PVI behind a VSN300 does not.
        """
        if cos_phi is None:
            await self._write_verified({"OutPFSet_Ena": Enabled.DISABLED})
            return
        if not -1.0 <= cos_phi <= 1.0:
            raise ValueError(f"cos phi must be -1..1, got {cos_phi}")
        await self._write_verified({"OutPFSet": cos_phi, "OutPFSet_Ena": Enabled.ENABLED})

    async def _write_verified(self, writes: dict[str, Any]) -> None:
        """Write points and confirm them by reading the model back.

        A VSN300 datalogger applies control writes but answers them with
        Modbus exception 7 (negative acknowledge), so that reply is not an
        error by itself: the readback decides. Any other exception response
        propagates, and a readback that does not match raises
        :class:`FimerWriteError`.
        """
        if not writes:
            return
        await self.async_update()
        for name, value in writes.items():
            try:
                await self.write(name, value)
            except ModbusExceptionError as err:
                if err.exception_code != NEGATIVE_ACKNOWLEDGE:
                    raise
        await self.async_update()
        for name, value in writes.items():
            actual = getattr(self, name)
            if not _matches(actual, value):
                raise FimerWriteError(f"{name} reads {actual!r} after writing {value!r}")


NEGATIVE_ACKNOWLEDGE = 7
"""Modbus exception code a VSN300 returns for control writes it applies anyway."""


def _matches(actual: Any, expected: Any) -> bool:
    if actual is None:
        return False
    if isinstance(expected, float) or isinstance(actual, float):
        return math.isclose(float(actual), float(expected), abs_tol=1e-3)
    return int(actual) == int(expected)


class StorageControlMode(IntFlag):
    """Which storage controls are active (``StorCtl_Mod``)."""

    CHARGE = 1 << 0
    DISCHARGE = 1 << 1


class ChargeState(IntEnum):
    """Battery charge status (``ChaSt``)."""

    OFF = 1
    EMPTY = 2
    DISCHARGING = 3
    CHARGING = 4
    FULL = 5
    HOLDING = 6
    TESTING = 7


class ChargeSource(IntEnum):
    """Whether the battery may charge from the grid (``ChaGriSet``)."""

    PV = 0
    GRID = 1


class Storage(FimerComponent):
    """SunSpec model 124: basic storage controls, served by REACT2 hybrids.

    Read-only here beyond :meth:`FimerModbusInverter.async_write`; a
    storage-capable inverter with no battery reports ``WChaMax`` as 0.
    """

    POINT_NAMES = (
        "WChaMax",
        "WChaGra",
        "WDisChaGra",
        "StorCtl_Mod",
        "VAChaMax",
        "MinRsvPct",
        "ChaState",
        "StorAval",
        "InBatV",
        "ChaSt",
        "OutWRte",
        "InWRte",
        "InOutWRte_RvrtTms",
        "ChaGriSet",
    )

    WChaMax = uint16(2, scale_register=18, writable=True, unit="W")
    WChaGra = uint16(3, scale_register=19, writable=True, unit="%")
    WDisChaGra = uint16(4, scale_register=19, writable=True, unit="%")
    StorCtl_Mod = bitfield16(5, StorageControlMode, writable=True)
    VAChaMax = uint16(6, scale_register=20, writable=True, unit="VA")
    MinRsvPct = uint16(7, scale_register=21, writable=True, unit="%")
    ChaState = uint16(8, scale_register=22, unit="%")
    StorAval = uint16(9, scale_register=23, unit="Ah")
    InBatV = uint16(10, scale_register=24, unit="V")
    ChaSt = enum16(11, ChargeState)
    OutWRte = int16(12, scale_register=25, writable=True, unit="%")
    InWRte = int16(13, scale_register=25, writable=True, unit="%")
    InOutWRte_WinTms = uint16(14, writable=True)
    InOutWRte_RvrtTms = uint16(15, writable=True)
    InOutWRte_RmpTms = uint16(16, writable=True)
    ChaGriSet = enum16(17, ChargeSource, writable=True)
