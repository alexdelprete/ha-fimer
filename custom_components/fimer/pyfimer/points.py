"""The point vocabulary shared by every pyfimer transport.

A point is one reading with a fixed name and native unit. Names are the
SunSpec normalized names the VSN REST mapping already uses (which for the
standard models are the SunSpec register names, with the mapping's
``PhVphAB`` spelling for the phase-to-phase voltages). Every client emits
readings as ``dict[str, value]`` keyed by these names, so the same key
means the same quantity in the same unit whatever the transport.

Native units are the SunSpec register units: watts, watt-hours, volts,
amperes, hertz, percent, degrees Celsius. A client that receives other
units (the VSN REST feed reports leakage currents in microamperes) converts
before emitting.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Final

from ._rest_points import rest_point_rows


class PointKind(StrEnum):
    """What a point's value represents."""

    MEASUREMENT = "measurement"
    """An instantaneous quantity."""

    TOTAL = "total"
    """A monotonically increasing counter, possibly reset on a schedule."""

    STATE = "state"
    """An integer code from an Aurora or SunSpec state table."""

    BITFIELD = "bitfield"
    """An integer bitfield of flags."""

    INFO = "info"
    """A static identification string or number."""

    TIMESTAMP = "timestamp"
    """Seconds since the Unix epoch."""


@dataclass(frozen=True, slots=True)
class Point:
    """One named reading and its native unit."""

    name: str
    kind: PointKind
    unit: str | None = None
    model: int | None = None
    """SunSpec model the point comes from; ``100`` for the 101/102/103 family."""
    description: str = ""


MODEL_COMMON: Final = 1
MODEL_INVERTER: Final = 100
MODEL_NAMEPLATE: Final = 120
MODEL_SETTINGS: Final = 121
MODEL_CONTROLS: Final = 123
MODEL_STORAGE: Final = 124
MODEL_MPPT: Final = 160
MODEL_ABB_VENDOR: Final = 64061
MODEL_STRING_COMBINER: Final = 403
MODEL_TRIO_COMM_BOARD: Final = 64062
MODEL_TRIO_FUSE_BOARD: Final = 64063

STRING_COMBINERS: Final = 2
"""DC inputs with a string combiner on a TRIO."""
COMBINER_STRINGS: Final = 5
"""Strings per combiner on a TRIO."""

MPPT_INPUTS: Final = 3
"""Highest number of MPPT inputs any supported inverter reports (TRIO-TM)."""


def _combiner_points() -> tuple[Point, ...]:
    points: list[Point] = []
    for number in range(1, STRING_COMBINERS + 1):
        suffix = f"_C{number}"
        points += [
            Point(
                f"DCAMax{suffix}",
                PointKind.INFO,
                "A",
                MODEL_STRING_COMBINER,
                f"Combiner {number} rated current",
            ),
            Point(
                f"N{suffix}",
                PointKind.INFO,
                None,
                MODEL_STRING_COMBINER,
                f"Combiner {number} string count",
            ),
            Point(
                f"DCA{suffix}",
                PointKind.MEASUREMENT,
                "A",
                MODEL_STRING_COMBINER,
                f"Combiner {number} current",
            ),
            Point(
                f"DCAhr{suffix}",
                PointKind.TOTAL,
                "Ah",
                MODEL_STRING_COMBINER,
                f"Combiner {number} amp-hours",
            ),
            Point(
                f"DCV{suffix}",
                PointKind.MEASUREMENT,
                "V",
                MODEL_STRING_COMBINER,
                f"Combiner {number} voltage",
            ),
            Point(
                f"Tmp{suffix}",
                PointKind.MEASUREMENT,
                "°C",
                MODEL_STRING_COMBINER,
                f"Combiner {number} temperature",
            ),
        ]
        for index in range(1, COMBINER_STRINGS + 1):
            points += [
                Point(
                    f"InDCA{suffix}_{index}",
                    PointKind.MEASUREMENT,
                    "A",
                    MODEL_STRING_COMBINER,
                    f"Combiner {number} string {index} current",
                ),
                Point(
                    f"InDCAhr{suffix}_{index}",
                    PointKind.TOTAL,
                    "Ah",
                    MODEL_STRING_COMBINER,
                    f"Combiner {number} string {index} amp-hours",
                ),
                Point(
                    f"InEvt{suffix}_{index}",
                    PointKind.BITFIELD,
                    None,
                    MODEL_STRING_COMBINER,
                    f"Combiner {number} string {index} events",
                ),
            ]
    return tuple(points)


def _mppt_points() -> tuple[Point, ...]:
    points: list[Point] = []
    for number in range(1, MPPT_INPUTS + 1):
        points += [
            Point(
                f"DCA_{number}",
                PointKind.MEASUREMENT,
                "A",
                MODEL_MPPT,
                f"DC current input {number}",
            ),
            Point(
                f"DCV_{number}",
                PointKind.MEASUREMENT,
                "V",
                MODEL_MPPT,
                f"DC voltage input {number}",
            ),
            Point(
                f"DCW_{number}", PointKind.MEASUREMENT, "W", MODEL_MPPT, f"DC power input {number}"
            ),
            Point(f"DCWH_{number}", PointKind.TOTAL, "Wh", MODEL_MPPT, f"DC energy input {number}"),
            Point(
                f"DCSt_{number}",
                PointKind.STATE,
                None,
                MODEL_MPPT,
                f"Operating state input {number}",
            ),
        ]
    return tuple(points)


SUNSPEC_POINTS: Final[tuple[Point, ...]] = (
    # SunSpec common model (1)
    Point("Mn", PointKind.INFO, None, MODEL_COMMON, "Manufacturer"),
    Point("Md", PointKind.INFO, None, MODEL_COMMON, "Model"),
    Point("Opt", PointKind.INFO, None, MODEL_COMMON, "Options"),
    Point("Vr", PointKind.INFO, None, MODEL_COMMON, "Firmware version"),
    Point("SN", PointKind.INFO, None, MODEL_COMMON, "Serial number"),
    Point("DA", PointKind.INFO, None, MODEL_COMMON, "Modbus device address"),
    # SunSpec inverter models (101 single phase, 102 split phase, 103 three phase)
    Point("A", PointKind.MEASUREMENT, "A", MODEL_INVERTER, "AC current"),
    Point("AphA", PointKind.MEASUREMENT, "A", MODEL_INVERTER, "AC current phase A"),
    Point("AphB", PointKind.MEASUREMENT, "A", MODEL_INVERTER, "AC current phase B"),
    Point("AphC", PointKind.MEASUREMENT, "A", MODEL_INVERTER, "AC current phase C"),
    Point("PhVphAB", PointKind.MEASUREMENT, "V", MODEL_INVERTER, "AC voltage phase A-B"),
    Point("PhVphBC", PointKind.MEASUREMENT, "V", MODEL_INVERTER, "AC voltage phase B-C"),
    Point("PhVphCA", PointKind.MEASUREMENT, "V", MODEL_INVERTER, "AC voltage phase C-A"),
    Point("PhVphA", PointKind.MEASUREMENT, "V", MODEL_INVERTER, "AC voltage phase A-N"),
    Point("PhVphB", PointKind.MEASUREMENT, "V", MODEL_INVERTER, "AC voltage phase B-N"),
    Point("PhVphC", PointKind.MEASUREMENT, "V", MODEL_INVERTER, "AC voltage phase C-N"),
    Point("W", PointKind.MEASUREMENT, "W", MODEL_INVERTER, "AC power"),
    Point("Hz", PointKind.MEASUREMENT, "Hz", MODEL_INVERTER, "AC frequency"),
    Point("VA", PointKind.MEASUREMENT, "VA", MODEL_INVERTER, "AC apparent power"),
    Point("VAr", PointKind.MEASUREMENT, "var", MODEL_INVERTER, "AC reactive power"),
    Point("PF", PointKind.MEASUREMENT, "%", MODEL_INVERTER, "AC power factor"),
    Point("WH", PointKind.TOTAL, "Wh", MODEL_INVERTER, "AC lifetime energy"),
    Point("DCA", PointKind.MEASUREMENT, "A", MODEL_INVERTER, "DC current"),
    Point("DCV", PointKind.MEASUREMENT, "V", MODEL_INVERTER, "DC voltage"),
    Point("DCW", PointKind.MEASUREMENT, "W", MODEL_INVERTER, "DC power"),
    Point("TmpCab", PointKind.MEASUREMENT, "°C", MODEL_INVERTER, "Cabinet temperature"),
    Point("TmpSnk", PointKind.MEASUREMENT, "°C", MODEL_INVERTER, "Heat sink temperature"),
    Point("TmpTrns", PointKind.MEASUREMENT, "°C", MODEL_INVERTER, "Transformer temperature"),
    Point("TmpOt", PointKind.MEASUREMENT, "°C", MODEL_INVERTER, "Other temperature"),
    Point("St", PointKind.STATE, None, MODEL_INVERTER, "SunSpec operating state"),
    Point("StVnd", PointKind.STATE, None, MODEL_INVERTER, "Vendor operating state"),
    Point("Evt1", PointKind.BITFIELD, None, MODEL_INVERTER, "SunSpec events"),
    Point("Events", PointKind.INFO, None, MODEL_INVERTER, "Active SunSpec event names"),
    Point("EvtVnd1", PointKind.BITFIELD, None, MODEL_INVERTER, "Vendor events 1"),
    Point("EvtVnd2", PointKind.BITFIELD, None, MODEL_INVERTER, "Vendor events 2"),
    Point("EvtVnd3", PointKind.BITFIELD, None, MODEL_INVERTER, "Vendor events 3"),
    Point("EvtVnd4", PointKind.BITFIELD, None, MODEL_INVERTER, "Vendor events 4"),
    # SunSpec multiple MPPT model (160)
    Point("N", PointKind.INFO, None, MODEL_MPPT, "Number of MPPT inputs"),
    *_mppt_points(),
    # SunSpec nameplate model (120)
    Point("DERTyp", PointKind.STATE, None, MODEL_NAMEPLATE, "DER type"),
    Point("WRtg", PointKind.INFO, "W", MODEL_NAMEPLATE, "Rated power"),
    Point("VARtg", PointKind.INFO, "VA", MODEL_NAMEPLATE, "Rated apparent power"),
    Point("ARtg", PointKind.INFO, "A", MODEL_NAMEPLATE, "Rated current"),
    Point("WhRtg", PointKind.INFO, "Wh", MODEL_NAMEPLATE, "Rated energy"),
    # SunSpec basic settings model (121)
    Point("WMax", PointKind.INFO, "W", MODEL_SETTINGS, "Maximum power"),
    Point("VRef", PointKind.INFO, "V", MODEL_SETTINGS, "Reference voltage"),
    Point("VMax", PointKind.INFO, "V", MODEL_SETTINGS, "Maximum voltage"),
    Point("VMin", PointKind.INFO, "V", MODEL_SETTINGS, "Minimum voltage"),
    Point("VAMax", PointKind.INFO, "VA", MODEL_SETTINGS, "Maximum apparent power"),
    Point("WGra", PointKind.INFO, "%", MODEL_SETTINGS, "Power ramp rate"),
    Point("ECPNomHz", PointKind.INFO, "Hz", MODEL_SETTINGS, "Nominal frequency"),
    # SunSpec immediate controls model (123)
    Point("Conn", PointKind.STATE, None, MODEL_CONTROLS, "Grid connection"),
    Point("WMaxLimPct", PointKind.MEASUREMENT, "%", MODEL_CONTROLS, "Power limit"),
    Point(
        "WMaxLimPct_RvrtTms", PointKind.MEASUREMENT, "s", MODEL_CONTROLS, "Power limit revert time"
    ),
    Point("WMaxLimPct_RmpTms", PointKind.MEASUREMENT, "s", MODEL_CONTROLS, "Power limit ramp time"),
    Point("WMaxLim_Ena", PointKind.STATE, None, MODEL_CONTROLS, "Power limit enabled"),
    Point("OutPFSet", PointKind.MEASUREMENT, None, MODEL_CONTROLS, "Power factor setpoint"),
    Point("OutPFSet_Ena", PointKind.STATE, None, MODEL_CONTROLS, "Power factor setpoint enabled"),
    Point(
        "VArWMaxPct",
        PointKind.MEASUREMENT,
        "%",
        MODEL_CONTROLS,
        "Reactive power setpoint (of WMax)",
    ),
    Point(
        "VArMaxPct",
        PointKind.MEASUREMENT,
        "%",
        MODEL_CONTROLS,
        "Reactive power setpoint (of VArMax)",
    ),
    Point(
        "VArAvalPct",
        PointKind.MEASUREMENT,
        "%",
        MODEL_CONTROLS,
        "Reactive power setpoint (of VArAval)",
    ),
    Point(
        "VArPct_RvrtTms",
        PointKind.MEASUREMENT,
        "s",
        MODEL_CONTROLS,
        "Reactive power setpoint revert time",
    ),
    Point(
        "VArPct_RmpTms",
        PointKind.MEASUREMENT,
        "s",
        MODEL_CONTROLS,
        "Reactive power setpoint ramp time",
    ),
    Point("VArPct_Mod", PointKind.STATE, None, MODEL_CONTROLS, "Reactive power setpoint mode"),
    Point("VArPct_Ena", PointKind.STATE, None, MODEL_CONTROLS, "Reactive power setpoint enabled"),
    # SunSpec basic storage controls model (124)
    Point("WChaMax", PointKind.INFO, "W", MODEL_STORAGE, "Maximum charge rate"),
    Point("WChaGra", PointKind.INFO, "%", MODEL_STORAGE, "Charge ramp rate"),
    Point("WDisChaGra", PointKind.INFO, "%", MODEL_STORAGE, "Discharge ramp rate"),
    Point("StorCtl_Mod", PointKind.BITFIELD, None, MODEL_STORAGE, "Active storage controls"),
    Point("VAChaMax", PointKind.INFO, "VA", MODEL_STORAGE, "Maximum charge apparent power"),
    Point("MinRsvPct", PointKind.MEASUREMENT, "%", MODEL_STORAGE, "Minimum reserve"),
    Point("ChaState", PointKind.MEASUREMENT, "%", MODEL_STORAGE, "State of charge"),
    Point("StorAval", PointKind.MEASUREMENT, "Ah", MODEL_STORAGE, "Available storage"),
    Point("InBatV", PointKind.MEASUREMENT, "V", MODEL_STORAGE, "Battery voltage"),
    Point("ChaSt", PointKind.STATE, None, MODEL_STORAGE, "Charge status"),
    Point("OutWRte", PointKind.MEASUREMENT, "%", MODEL_STORAGE, "Discharge rate setpoint"),
    Point("InWRte", PointKind.MEASUREMENT, "%", MODEL_STORAGE, "Charge rate setpoint"),
    Point(
        "InOutWRte_RvrtTms", PointKind.MEASUREMENT, "s", MODEL_STORAGE, "Rate setpoint revert time"
    ),
    Point("ChaGriSet", PointKind.STATE, None, MODEL_STORAGE, "Charge source"),
    # TRIO string combiners (403) and boards (64062, 64063)
    *_combiner_points(),
    Point(
        "CommBoard_SN", PointKind.INFO, None, MODEL_TRIO_COMM_BOARD, "Communication board serial"
    ),
    Point(
        "CommBoard_FwVersion",
        PointKind.INFO,
        None,
        MODEL_TRIO_COMM_BOARD,
        "Communication board firmware",
    ),
    Point("PT100", PointKind.MEASUREMENT, "°C", MODEL_TRIO_COMM_BOARD, "PT100 probe"),
    Point("PT1000", PointKind.MEASUREMENT, "°C", MODEL_TRIO_COMM_BOARD, "PT1000 probe"),
    Point("Analog1", PointKind.MEASUREMENT, None, MODEL_TRIO_COMM_BOARD, "Analogue input 1"),
    Point("Analog2", PointKind.MEASUREMENT, None, MODEL_TRIO_COMM_BOARD, "Analogue input 2"),
    Point(
        "CommBoard_Tmp",
        PointKind.MEASUREMENT,
        "°C",
        MODEL_TRIO_COMM_BOARD,
        "Communication board temperature",
    ),
    Point("FuseBoard_SN", PointKind.INFO, None, MODEL_TRIO_FUSE_BOARD, "Fuse board serial"),
    Point(
        "FuseBoard_FwVersion", PointKind.INFO, None, MODEL_TRIO_FUSE_BOARD, "Fuse board firmware"
    ),
    Point("FuseBoard_St", PointKind.INFO, None, MODEL_TRIO_FUSE_BOARD, "Fuse board state bytes"),
    # ABB vendor model (64061)
    Point("HwVersion", PointKind.INFO, None, MODEL_ABB_VENDOR, "Hardware version"),
    Point("Parent", PointKind.INFO, None, MODEL_ABB_VENDOR, "Parent device"),
    Point("DevicePresence", PointKind.BITFIELD, None, MODEL_ABB_VENDOR, "Boards present"),
    Point("GlobalSt", PointKind.STATE, None, MODEL_ABB_VENDOR, "Aurora global state"),
    Point("InverterSt", PointKind.STATE, None, MODEL_ABB_VENDOR, "Aurora inverter state"),
    Point("DcSt1", PointKind.STATE, None, MODEL_ABB_VENDOR, "Aurora DC/DC 1 state"),
    Point("DcSt2", PointKind.STATE, None, MODEL_ABB_VENDOR, "Aurora DC/DC 2 state"),
    Point("DcSt3", PointKind.STATE, None, MODEL_ABB_VENDOR, "Aurora DC/DC 3 state"),
    Point("SysTime", PointKind.TIMESTAMP, "s", MODEL_ABB_VENDOR, "Inverter clock"),
    Point("Alarm1", PointKind.BITFIELD, None, MODEL_ABB_VENDOR, "Aurora alarms 0-30"),
    Point("Alarm2", PointKind.BITFIELD, None, MODEL_ABB_VENDOR, "Aurora alarms 31-61"),
    Point("Alarm3", PointKind.BITFIELD, None, MODEL_ABB_VENDOR, "Aurora alarms 62-92"),
    Point("Alarms", PointKind.INFO, None, MODEL_ABB_VENDOR, "Active alarm names"),
    Point("DayWH", PointKind.TOTAL, "Wh", MODEL_ABB_VENDOR, "Energy today"),
    Point("TotalWH", PointKind.TOTAL, "Wh", MODEL_ABB_VENDOR, "Lifetime energy"),
    Point("PartialWH", PointKind.TOTAL, "Wh", MODEL_ABB_VENDOR, "Partial energy counter"),
    Point("WeekWH", PointKind.TOTAL, "Wh", MODEL_ABB_VENDOR, "Energy this week"),
    Point("MonthWH", PointKind.TOTAL, "Wh", MODEL_ABB_VENDOR, "Energy this month"),
    Point("YearWH", PointKind.TOTAL, "Wh", MODEL_ABB_VENDOR, "Energy this year"),
    Point("AC_V", PointKind.MEASUREMENT, "V", MODEL_ABB_VENDOR, "AC voltage (vendor)"),
    Point("AC_A", PointKind.MEASUREMENT, "A", MODEL_ABB_VENDOR, "AC current (vendor)"),
    Point("AC_W", PointKind.MEASUREMENT, "W", MODEL_ABB_VENDOR, "AC power (vendor)"),
    Point("AC_Hz", PointKind.MEASUREMENT, "Hz", MODEL_ABB_VENDOR, "AC frequency (vendor)"),
    Point("DC1_W", PointKind.MEASUREMENT, "W", MODEL_ABB_VENDOR, "DC power input 1 (vendor)"),
    Point("DC1_V", PointKind.MEASUREMENT, "V", MODEL_ABB_VENDOR, "DC voltage input 1 (vendor)"),
    Point("DC1_A", PointKind.MEASUREMENT, "A", MODEL_ABB_VENDOR, "DC current input 1 (vendor)"),
    Point("DC2_W", PointKind.MEASUREMENT, "W", MODEL_ABB_VENDOR, "DC power input 2 (vendor)"),
    Point("DC2_V", PointKind.MEASUREMENT, "V", MODEL_ABB_VENDOR, "DC voltage input 2 (vendor)"),
    Point("DC2_A", PointKind.MEASUREMENT, "A", MODEL_ABB_VENDOR, "DC current input 2 (vendor)"),
    Point("Tmp", PointKind.MEASUREMENT, "°C", MODEL_ABB_VENDOR, "Inverter temperature"),
    Point("Booster_Tmp", PointKind.MEASUREMENT, "°C", MODEL_ABB_VENDOR, "Booster temperature"),
    Point(
        "Isolation_Ohm1",
        PointKind.MEASUREMENT,
        "MΩ",
        MODEL_ABB_VENDOR,
        "Isolation resistance input 1",
    ),
    Point(
        "Isolation_Ohm2",
        PointKind.MEASUREMENT,
        "MΩ",
        MODEL_ABB_VENDOR,
        "Isolation resistance input 2",
    ),
    Point("WindGen_Hz", PointKind.MEASUREMENT, "Hz", MODEL_ABB_VENDOR, "Wind generator frequency"),
    Point(
        "Inverter_CosPhi", PointKind.MEASUREMENT, None, MODEL_ABB_VENDOR, "Power factor (cos phi)"
    ),
    Point(
        "OutputW_Perm", PointKind.MEASUREMENT, "%", MODEL_ABB_VENDOR, "Permanent output power limit"
    ),
    Point(
        "OutputW_Dynamic",
        PointKind.MEASUREMENT,
        "%",
        MODEL_ABB_VENDOR,
        "Dynamic output power limit",
    ),
    Point(
        "PF_Perm", PointKind.MEASUREMENT, None, MODEL_ABB_VENDOR, "Permanent power factor setpoint"
    ),
    Point(
        "PF_Dynamic", PointKind.MEASUREMENT, None, MODEL_ABB_VENDOR, "Dynamic power factor setpoint"
    ),
)


def _rest_only_points() -> tuple[Point, ...]:
    """Points the VSN REST feeds add on top of the SunSpec ones.

    Where a REST point shares a name with a SunSpec point, the SunSpec
    definition above is the one that counts.
    """
    known = {point.name for point in SUNSPEC_POINTS}
    points: list[Point] = []
    for name, unit, kind, models, description in rest_point_rows():
        if name in known:
            continue
        model = MODEL_ABB_VENDOR if "M64061" in models else None
        points.append(Point(name, PointKind(kind), unit, model, description))
    return tuple(points)


REST_POINTS: Final[tuple[Point, ...]] = _rest_only_points()
"""Points only the REST feeds provide: datalogger, meter, battery, energy counters."""

POINTS: Final[tuple[Point, ...]] = SUNSPEC_POINTS + REST_POINTS
"""Every point any transport can report."""

POINTS_BY_NAME: Final[dict[str, Point]] = {point.name: point for point in POINTS}
