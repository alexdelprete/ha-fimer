"""Lookups over the generated REST point table."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final

from ._mapping_data import REST_POINT_ROWS


@dataclass(frozen=True, slots=True)
class RestPoint:
    """One row of the VSN-SunSpec mapping, as the REST client uses it."""

    name: str
    """The vocabulary point name."""
    vsn300_name: str | None
    vsn700_name: str | None
    unit: str | None
    kind: str
    category: str
    models: tuple[str, ...]
    display_name: str
    device_class: str | None
    state_class: str | None
    entity_category: str | None
    precision: int | None
    icon: str | None
    scope: str | None
    accumulation: str | None
    ha_name: str
    """The entity key the earlier REST integration used, for migrating its entities."""


REST_POINTS: Final[tuple[RestPoint, ...]] = tuple(
    RestPoint(
        name=row[0],
        vsn300_name=row[1],
        vsn700_name=row[2],
        unit=row[3],
        kind=row[4],
        category=row[5],
        models=tuple(row[6].split(",")) if row[6] else (),
        display_name=row[7],
        device_class=row[8],
        state_class=row[9],
        entity_category=row[10],
        precision=row[11],
        icon=row[12],
        scope=row[13],
        accumulation=row[14],
        ha_name=row[15],
    )
    for row in REST_POINT_ROWS
)

SHARED_NAME_ALIASES: Final[dict[str, str]] = {
    # VSN700 names for quantities the VSN300 and the Modbus client report
    # under SunSpec names: emitted under the shared name so a caller cannot
    # tell the cards apart.
    "GlobState": "GlobalSt",
    "InvState": "InverterSt",
    "DC1State": "DcSt1",
    "DC2State": "DcSt2",
    "DC3State": "DcSt3",
    "AlarmState": "AlarmSt",
    "Iin1": "DCA_1",
    "Vin1": "DCV_1",
    "Pin1": "DCW_1",
    "Iin2": "DCA_2",
    "Vin2": "DCV_2",
    "Pin2": "DCW_2",
    "Iin3": "DCA_3",
    "Vin3": "DCV_3",
    "Pin3": "DCW_3",
    "Pin": "DCW",
    "Temp1": "TmpCab",
    "TempBst": "Booster_Tmp",
    "TempInv": "Tmp",
    "Ein1": "DCWH_1",
    "Ein2": "DCWH_2",
    "Ein3": "DCWH_3",
    "cosPhi": "Inverter_CosPhi",
}
"""Mapping names that are aliases of another vocabulary point."""

BY_NAME: Final[dict[str, RestPoint]] = {point.name: point for point in REST_POINTS}
BY_VSN300_NAME: Final[dict[str, RestPoint]] = {
    point.vsn300_name: point for point in REST_POINTS if point.vsn300_name
}
BY_VSN700_NAME: Final[dict[str, RestPoint]] = {
    point.vsn700_name: point for point in REST_POINTS if point.vsn700_name
}
