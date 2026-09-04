"""Aurora protocol tables shared by every FIMER (ABB / Power-One) transport.

The inverters speak Power-One's Aurora protocol internally. Both the SunSpec
vendor model 64061 over Modbus and the VSN datalogger REST feeds expose the
same raw Aurora state and alarm codes, so the tables live here once.

Sources: ABB_SunSpec_Modbus.xlsx (2013, "Status and Events" sheet), the
Aurora Communication Protocol 4.2 document, and the tables carried by the
earlier ha-abb-fimer-pvi-vsn-rest and ha-abb-powerone-pvi-sunspec
integrations.
"""

from __future__ import annotations

from typing import Final

# Aurora system time counts seconds from 2000-01-01T00:00:00Z. Add this to
# get a Unix timestamp.
AURORA_EPOCH_OFFSET: Final = 946684800

# GlobalSt: inverter global state (Aurora command 50, byte "Global State").
GLOBAL_STATES: Final[dict[int, str]] = {
    0: "Sending Parameters",
    1: "Wait Sun / Grid",
    2: "Checking Grid",
    3: "Measuring Riso",
    4: "DcDc Start",
    5: "Inverter Start",
    6: "Run",
    7: "Recovery",
    8: "Pause",
    9: "Ground Fault",
    10: "OTH Fault",
    11: "Address Setting",
    12: "Self Test",
    13: "Self Test Fail",
    14: "Sensor Test + Measure Riso",
    15: "Leak Fault",
    16: "Waiting for manual reset",
    17: "Internal Error E026",
    18: "Internal Error E027",
    19: "Internal Error E028",
    20: "Internal Error E029",
    21: "Internal Error E030",
    22: "Sending Wind Table",
    23: "Failed Sending table",
    24: "UTH Fault",
    25: "Remote OFF",
    26: "Interlock Fail",
    27: "Executing Autotest",
    30: "Waiting Sun",
    31: "Temperature Fault",
    32: "Fan Stuck",
    33: "Int. Com. Fault",
    34: "Slave Insertion",
    35: "DC Switch Open",
    36: "TRAS Switch Open",
    37: "MASTER Exclusion",
    38: "Auto Exclusion",
    98: "Erasing Internal EEprom",
    99: "Erasing External EEprom",
    100: "Counting EEprom",
    101: "Freeze",
    116: "Standby",
    200: "Dsp Programming",
}

# InverterSt: inverter (DC/AC stage) state.
INVERTER_STATES: Final[dict[int, str]] = {
    0: "Stand By",
    1: "Checking Grid",
    2: "Run",
    3: "Bulk OV",
    4: "Out OC",
    5: "IGBT Sat",
    6: "Bulk UV",
    7: "Degauss Error",
    8: "No Parameters",
    9: "Bulk Low",
    10: "Grid OV",
    11: "Communication Error",
    12: "Degaussing",
    13: "Starting",
    14: "Bulk Cap Fail",
    15: "Leak Fail",
    16: "DcDc Fail",
    17: "Ileak Sensor Fail",
    18: "SelfTest: relay inverter",
    19: "SelfTest: wait for sensor test",
    20: "SelfTest: test relay DcDc + sensor",
    21: "SelfTest: relay inverter fail",
    22: "SelfTest timeout fail",
    23: "SelfTest: relay DcDc fail",
    24: "Self Test 1",
    25: "Waiting self test start",
    26: "Dc Injection",
    27: "Self Test 2",
    28: "Self Test 3",
    29: "Self Test 4",
    30: "Internal Error",
    31: "Internal Error",
    40: "Forbidden State",
    41: "Input UC",
    42: "Zero Power",
    43: "Grid Not Present",
    44: "Waiting Start",
    45: "MPPT",
    46: "Grid Fail",
    47: "Input OC",
    255: "Inverter Dsp not programmed",
}

# DcSt1 / DcSt2: DC/DC converter (MPPT channel) state.
DCDC_STATES: Final[dict[int, str]] = {
    0: "DcDc OFF",
    1: "Ramp Start",
    2: "MPPT",
    3: "Not Used",
    4: "Input OC",
    5: "Input UV",
    6: "Input OV",
    7: "Input Low",
    8: "No Parameters",
    9: "Bulk OV",
    10: "Communication Error",
    11: "Ramp Fail",
    12: "Internal Error",
    13: "Input mode Error",
    14: "Ground Fault",
    15: "Inverter Fail",
    16: "DcDc IGBT Sat",
    17: "DcDc ILEAK Fail",
    18: "DcDc Grid Fail",
    19: "DcDc Comm. Error",
}

# Aurora alarm codes. The VSN REST feed reports the current code as
# ``AlarmSt``; the SunSpec vendor model packs them into the Alarm1..Alarm3
# bitfields at 31 codes per register (bit 31 stays clear so 0xFFFFFFFF can
# mean "not implemented"): code ``n`` is bit ``n % 31`` of register ``n // 31``.
ALARM_CODES: Final[dict[int, str]] = {
    0: "No Alarm",
    1: "Sun Low",
    2: "Input OC",
    3: "Input UV",
    4: "Input OV",
    5: "Sun Low",
    6: "No Parameters",
    7: "Bulk OV",
    8: "Comm. Error",
    9: "Output OC",
    10: "IGBT Sat",
    11: "Bulk UV",
    12: "Internal error",
    13: "Grid Fail",
    14: "Bulk Low",
    15: "Ramp Fail",
    16: "Dc/Dc Fail",
    17: "Wrong Mode",
    18: "Ground Fault",
    19: "Over Temp.",
    20: "Bulk Cap Fail",
    21: "Inverter Fail",
    22: "Start Timeout",
    23: "Ground Fault",
    24: "AC feed forward",
    25: "Ileak sens. fail",
    26: "DcDc Fail",
    27: "Self Test Error 1",
    28: "Self Test Error 2",
    29: "Self Test Error 3",
    30: "Self Test Error 4",
    31: "DC inj error",
    32: "Grid OV",
    33: "Grid UV",
    34: "Grid OF",
    35: "Grid UF",
    36: "Z grid Hi",
    37: "Internal error",
    38: "Riso Low",
    39: "Vref Error",
    40: "Error Meas V",
    41: "Error Meas F",
    42: "Error Meas Z",
    43: "Error Meas Ileak",
    44: "Error Read V",
    45: "Error Read I",
    46: "Table fail",
    47: "Fan Fail",
    48: "UTH",
    49: "Interlock fail",
    50: "Remote Off",
    51: "Vout Avg error",
    52: "Battery low",
    53: "Clk fail",
    54: "Input UC",
    55: "Zero Power",
    56: "Fan Stuck",
    57: "DC Switch Open",
    58: "Tras Switch Open",
    59: "AC Switch Open",
    60: "Bulk UV",
    61: "Autoexclusion",
    62: "Grid df/dt",
    63: "Den switch Open",
    64: "Jbox fail",
    65: "DC Door Open",
    66: "AC Door Open",
    67: "Anti islanding",
    68: "Fuse DC Fail",
    69: "Liquid Cooler Fail",
    70: "SPD AC protection open",
    71: "SPD DC protection open",
    72: "String selftest fail",
    73: "Power reduction start",
    74: "Power reduction end",
    75: "React. power mode changed",
    76: "date/time changed",
    77: "Energy data reset",
}

_ALARM_BITS_PER_REGISTER: Final = 31


def decode_alarms(*registers: int | None) -> list[str]:
    """Return the alarm names set in the vendor model's Alarm1..AlarmN bitfields.

    Registers are given in order; ``None`` (not implemented) reads as empty.
    The "No Alarm" code in bit 0 of the first register is not an alarm and is
    left out.
    """
    alarms: list[str] = []
    for index, register in enumerate(registers):
        if not register:
            continue
        for bit in range(_ALARM_BITS_PER_REGISTER):
            if not register & (1 << bit):
                continue
            code = index * _ALARM_BITS_PER_REGISTER + bit
            if code == 0:
                continue
            alarms.append(ALARM_CODES.get(code, f"Alarm {code}"))
    return alarms


# Inverter model by the Aurora product code the SunSpec common model carries
# as the first character of its ``Opt`` string (Aurora command 58, "Part
# Number / model"). Behind a VSN datalogger ``Md`` names the logger, so this
# is the only Modbus source of the inverter model.
INVERTER_MODELS: Final[dict[int, str]] = {
    0: "UNO-DM-3.3-TL-PLUS",
    1: "UNO-DM-4.0-TL-PLUS",
    3: "UNO-DM-4.6-TL-PLUS",
    4: "UNO-DM-5.0-TL-PLUS",
    5: "UNO-DM-6.0-TL-PLUS",
    10: "UNO-DM-1.2-TL-PLUS",
    11: "UNO-DM-2.0-TL-PLUS",
    12: "UNO-DM-3.0-TL-PLUS",
    13: "REACT2-UNO-5.0-TL",
    14: "REACT2-UNO-3.6-TL",
    15: "UNO-DM-5.0-TL-PLUS",
    16: "UNO-DM-6.0-TL-PLUS",
    19: "REACT2-5.0-TL",
    49: "PVI-3.0-OUTD",
    50: "PVI-3.3-OUTD",
    51: "PVI-3.6-OUTD",
    52: "PVI-4.2-OUTD",
    53: "PVI-5000-OUTD",
    54: "PVI-6000-OUTD",
    65: "PVI-CENTRAL-350",
    66: "PVI-CENTRAL-350",
    67: "PVI-CENTRAL-50",
    68: "PVI-12.5-OUTD",
    69: "PVI-CENTRAL-67",
    70: "TRIO-27.6-TL-OUTD",
    71: "UNO-2.5-OUTD",
    72: "PVI-4.6-OUTD-I",
    74: "PVI-1700-OUTD",
    76: "PVI-CENTRAL-350",
    77: "PVI-CENTRAL-250",
    78: "PVI-12.5-OUTD",
    79: "PVI-3600-OUTD",
    80: "3-phase interface (3G74)",
    81: "PVI-8.0-OUTD-PLUS",
    82: "TRIO-8.5-TL-OUTD-S",
    83: "PVS-12.5-TL",
    84: "PVI-12.5-OUTD-I",
    85: "PVI-12.5-OUTD-I",
    86: "PVI-12.5-OUTD-I",
    88: "PVI-10.0-OUTD",
    89: "TRIO-27.6-TL-OUTD",
    90: "PVI-12.5-OUTD-I",
    99: "CDD",
    102: "TRIO-20-TL-OUTD",
    103: "UNO-2.0-OUTD",
    104: "PVI-3.8-OUTD-I",
    105: "PVI-2000-IND",
    106: "PVI-1700-IND",
    107: "TRIO-7.5-OUTD",
    108: "PVI-3600-IND",
    110: "PVI-10.0-OUTD",
    111: "PVI-2000-OUTD",
    113: "PVI-8.0-OUTD",
    114: "TRIO-5.8-OUTD",
    116: "PVI-10.0-OUTD-I",
    117: "PVI-10.0-OUTD-I",
    118: "PVI-10.0-OUTD-I",
    119: "PVI-10.0-I-OUTD",
    121: "TRIO-20-TL-OUTD",
    122: "PVI-10.0-OUTD-I",
    224: "UNO-2.0-TL-OUTD",
    242: "UNO-3.0-TL-OUTD",
}


def inverter_model_from_options(options: str | None) -> str | None:
    """Return the inverter model named by a common model ``Opt`` string.

    The product code is the first character, or a ``0x..`` hex prefix when
    the code is not printable (some firmwares render it as ``0x0D/0xFFFF``).
    Returns ``None`` for an empty string or an unknown code.
    """
    if not options:
        return None
    if options.startswith(("0x", "0X")):
        try:
            code = int(options[:4], 16)
        except ValueError:
            return None
    else:
        code = ord(options[0])
    return INVERTER_MODELS.get(code)
