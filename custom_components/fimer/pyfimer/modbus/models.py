"""SunSpec models 1, 101/102/103 and 160 as read from FIMER inverters.

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
