"""Models a TRIO inverter adds to the chain: string combiners and its boards.

From the 2013 Power-One register map: the standard SunSpec string combiner
model 403 once per DC input, vendor model 64062 for the communication
board with its temperature probes and analogue inputs, and vendor model
64063 for the fuse control board. Written from the sheet and not yet seen
on hardware; a chain scan of a TRIO would confirm them.
"""

from __future__ import annotations

from enum import IntFlag
from typing import Any, ClassVar

from modbus_connection.model import Component, repeating_group
from modbus_connection.model.sunspec import (
    acc32,
    bitfield16,
    bitfield32,
    float32,
    int16,
    string,
    uint16,
)

from .models import FimerComponent


class StringInputEvent(IntFlag):
    """String input events (``InEvt``)."""

    LOW_VOLTAGE = 1 << 0
    LOW_POWER = 1 << 1
    LOW_EFFICIENCY = 1 << 2
    REVERSE_CURRENT = 1 << 3
    REVERSE_VOLTAGE = 1 << 4
    OPEN_FUSE = 1 << 5


class CombinerEvent(IntFlag):
    """String combiner events (``Evt``)."""

    LOW_VOLTAGE = 1 << 0
    LOW_POWER = 1 << 1
    LOW_EFFICIENCY = 1 << 2
    REVERSE_CURRENT = 1 << 3
    REVERSE_VOLTAGE = 1 << 4
    OPEN_FUSE = 1 << 5
    COMMUNICATION_ERROR = 1 << 6


class StringInput(Component):
    """One string of a combiner, declared at the first string block."""

    InID = uint16(18)
    InEvt = bitfield32(19, StringInputEvent)
    InEvtVnd = bitfield32(21)
    InDCA = int16(23, scale_register=16, unit="A")
    InDCAhr = acc32(24, scale_register=17, unit="Ah")


class StringCombiner(FimerComponent):
    """SunSpec model 403: a DC string combiner, one per TRIO DC input.

    Points are emitted with the combiner's number so two combiners do not
    collide: ``DCA_C1``, ``InDCA_C1_1`` and so on.
    """

    POINT_NAMES = ("DCAMax", "N", "DCA", "DCAhr", "DCV", "Tmp")
    STRING_POINT_NAMES: ClassVar[tuple[str, ...]] = ("InDCA", "InDCAhr", "InEvt")

    DCAMax = uint16(5, scale_register=2, unit="A")
    N = uint16(6)
    Evt = bitfield32(7, CombinerEvent)
    EvtVnd = bitfield32(9)
    DCA = int16(11, scale_register=2, unit="A")
    DCAhr = acc32(12, scale_register=3, unit="Ah")
    DCV = int16(14, scale_register=4, unit="V")
    Tmp = int16(15, unit="°C")
    strings = repeating_group(uint16(6), StringInput, stride=8)

    def __init__(self, *args: Any, number: int = 1, **kwargs: Any) -> None:
        """``number`` is the combiner's position in the chain, from 1."""
        super().__init__(*args, **kwargs)
        self.number = number

    def values(self) -> dict[str, Any]:
        """Return the readings suffixed with the combiner and string numbers."""
        suffix = f"_C{self.number}"
        values = {f"{name}{suffix}": getattr(self, name) for name in self.POINT_NAMES}
        for index, string_input in enumerate(self.strings, start=1):
            for name in self.STRING_POINT_NAMES:
                values[f"{name}{suffix}_{index}"] = getattr(string_input, name)
        return values


class TrioCommBoard(FimerComponent):
    """Vendor model 64062: the TRIO communication board."""

    POINT_NAMES = (
        "CommBoard_SN",
        "CommBoard_FwVersion",
        "PT100",
        "PT1000",
        "Analog1",
        "Analog2",
        "CommBoard_Tmp",
    )

    CommBoard_SN = string(2, 8)
    CommBoard_FwVersion = string(10, 4)
    St4 = bitfield16(14)
    St5 = bitfield16(15)
    PT100 = float32(16, unit="°C")
    PT1000 = float32(18, unit="°C")
    Analog1 = float32(20)
    Analog2 = float32(22)
    CommBoard_Tmp = float32(24, unit="°C")
    Analog1Gain = float32(26, writable=True)
    Analog1Offset = float32(28, writable=True)
    Analog1Units = string(30, 2, writable=True)
    Analog2Gain = float32(32, writable=True)
    Analog2Offset = float32(34, writable=True)
    Analog2Units = string(36, 2, writable=True)


class TrioFuseBoard(FimerComponent):
    """Vendor model 64063: the TRIO fuse control board."""

    POINT_NAMES = ("FuseBoard_SN", "FuseBoard_FwVersion", "FuseBoard_St")

    FuseBoard_SN = string(2, 8)
    FuseBoard_FwVersion = string(10, 4)
    St0 = bitfield16(14)
    St1 = bitfield16(15)
    St2 = bitfield16(16)
    St3 = bitfield16(17)
    St4 = bitfield16(18)
    St5 = bitfield16(19)

    @property
    def FuseBoard_St(self) -> list[int | None]:  # noqa: N802 - a vocabulary point name
        """The six state bytes as a list."""
        return [self.St0, self.St1, self.St2, self.St3, self.St4, self.St5]
