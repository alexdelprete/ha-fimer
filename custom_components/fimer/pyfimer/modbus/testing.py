"""SunSpec register map builder for tests.

Builds holding-register maps in the layout a VSN300 serves for a PVI
inverter, for ``modbus_connection.mock.MockModbusUnit``::

    unit.holding.update(build_register_map(inverter=InverterSpec(ac_power=1500)))

Scale factors are fixed, so values must be representable: currents in
hundredths, voltages and temperatures in tenths, powers and energies as
integers, frequency in hundredths, power factor in tenths of a percent.
``None`` encodes the type's not-implemented sentinel.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import math
import struct

from .sunspec import (
    ABB_VENDOR_MODEL_ID,
    ABB_VENDOR_MODEL_LENGTH,
    BASE_ADDRESS_DATALOGGER,
    COMMON_MODEL_ID,
    CONTROLS_MODEL_ID,
    MPPT_MODEL_ID,
    NAMEPLATE_MODEL_ID,
    SETTINGS_MODEL_ID,
)

NOT_IMPLEMENTED_UINT16 = 0xFFFF
NOT_IMPLEMENTED_INT16 = 0x8000
NOT_IMPLEMENTED_ACC32 = 0
NOT_IMPLEMENTED_ENUM16 = 0xFFFF
NOT_IMPLEMENTED_BITFIELD32 = 0xFFFFFFFF
NOT_IMPLEMENTED_UINT32 = 0xFFFFFFFF

SF_CURRENT = -2
SF_VOLTAGE = -1
SF_POWER = 0
SF_FREQUENCY = -2
SF_POWER_FACTOR = -1
SF_ENERGY = 0
SF_TEMPERATURE = -1


@dataclass
class InverterSpec:
    """Engineering values for SunSpec model 101/103."""

    ac_current: float | None = None
    ac_current_phase_a: float | None = None
    ac_current_phase_b: float | None = None
    ac_current_phase_c: float | None = None
    voltage_ab: float | None = None
    voltage_bc: float | None = None
    voltage_ca: float | None = None
    voltage_a: float | None = None
    voltage_b: float | None = None
    voltage_c: float | None = None
    ac_power: float | None = None
    frequency: float | None = None
    apparent_power: float | None = None
    reactive_power: float | None = None
    power_factor: float | None = None
    energy_total: int | None = None
    dc_current: float | None = None
    dc_voltage: float | None = None
    dc_power: float | None = None
    cabinet_temperature: float | None = None
    heat_sink_temperature: float | None = None
    transformer_temperature: float | None = None
    other_temperature: float | None = None
    operating_state: int | None = None
    vendor_operating_state: int | None = None
    events: int = 0
    vendor_events: int = 0


@dataclass
class MpptInputSpec:
    """Engineering values for one input of SunSpec model 160."""

    id_str: str = ""
    current: float | None = None
    voltage: float | None = None
    power: float | None = None
    energy: int | None = None
    operating_state: int | None = None


@dataclass
class VendorSpec:
    """Values for the ABB vendor model 64061."""

    hardware_version: str = "0001"
    parent: str = ""
    device_presence: int = 0b1000
    global_state: int | None = None
    inverter_state: int | None = None
    dc_state_1: int | None = None
    dc_state_2: int | None = None
    sys_time: int | None = None
    """Seconds since the Aurora epoch (2000-01-01)."""
    alarms: list[int] = field(default_factory=list)
    """Active Aurora alarm codes, set as bits in Alarm1..Alarm3."""
    day_wh: float | None = None
    total_wh: float | None = None
    partial_wh: float | None = None
    week_wh: float | None = None
    month_wh: float | None = None
    year_wh: float | None = None
    ac_voltage: float | None = None
    ac_current: float | None = None
    ac_power: float | None = None
    ac_frequency: float | None = None
    dc1_power: float | None = None
    dc1_voltage: float | None = None
    dc1_current: float | None = None
    dc2_power: float | None = None
    dc2_voltage: float | None = None
    dc2_current: float | None = None
    temperature: float | None = None
    booster_temperature: float | None = None
    isolation_1: float | None = None
    isolation_2: float | None = None
    wind_generator_frequency: float | None = None
    cos_phi: float | None = None
    output_power_permanent: int | None = None
    output_power_dynamic: int | None = None
    pf_permanent: float | None = None
    pf_dynamic: float | None = None


def _string_words(value: str, register_count: int) -> list[int]:
    raw = value.encode("ascii").ljust(register_count * 2, b"\x00")
    return [int.from_bytes(raw[i : i + 2], "big") for i in range(0, len(raw), 2)]


def _float32_words(value: float | None) -> list[int]:
    raw = struct.pack(">f", math.nan if value is None else value)
    return [int.from_bytes(raw[:2], "big"), int.from_bytes(raw[2:], "big")]


def _scaled_word(value: float | None, exponent: int, *, signed: bool = False) -> int:
    if value is None:
        return NOT_IMPLEMENTED_INT16 if signed else NOT_IMPLEMENTED_UINT16
    return round(value * 10.0**-exponent) & 0xFFFF


def _uint32_words(value: int) -> list[int]:
    return [(value >> 16) & 0xFFFF, value & 0xFFFF]


def _sf_word(exponent: int) -> int:
    return exponent & 0xFFFF


def _enum_word(value: int | None) -> int:
    return NOT_IMPLEMENTED_ENUM16 if value is None else value


def _common_model_data(
    manufacturer: str, device_model: str, options: str, version: str, serial_number: str
) -> list[int]:
    return [
        *_string_words(manufacturer, 16),
        *_string_words(device_model, 16),
        *_string_words(options, 8),
        *_string_words(version, 8),
        *_string_words(serial_number, 16),
        2,  # DA
        0,  # pad
    ]


def _inverter_model_data(spec: InverterSpec) -> list[int]:
    return [
        _scaled_word(spec.ac_current, SF_CURRENT),
        _scaled_word(spec.ac_current_phase_a, SF_CURRENT),
        _scaled_word(spec.ac_current_phase_b, SF_CURRENT),
        _scaled_word(spec.ac_current_phase_c, SF_CURRENT),
        _sf_word(SF_CURRENT),  # A_SF
        _scaled_word(spec.voltage_ab, SF_VOLTAGE),
        _scaled_word(spec.voltage_bc, SF_VOLTAGE),
        _scaled_word(spec.voltage_ca, SF_VOLTAGE),
        _scaled_word(spec.voltage_a, SF_VOLTAGE),
        _scaled_word(spec.voltage_b, SF_VOLTAGE),
        _scaled_word(spec.voltage_c, SF_VOLTAGE),
        _sf_word(SF_VOLTAGE),  # V_SF
        _scaled_word(spec.ac_power, SF_POWER, signed=True),
        _sf_word(SF_POWER),  # W_SF
        _scaled_word(spec.frequency, SF_FREQUENCY),
        _sf_word(SF_FREQUENCY),  # Hz_SF
        _scaled_word(spec.apparent_power, SF_POWER, signed=True),
        _sf_word(SF_POWER),  # VA_SF
        _scaled_word(spec.reactive_power, SF_POWER, signed=True),
        _sf_word(SF_POWER),  # VAr_SF
        _scaled_word(spec.power_factor, SF_POWER_FACTOR, signed=True),
        _sf_word(SF_POWER_FACTOR),  # PF_SF
        *_uint32_words(NOT_IMPLEMENTED_ACC32 if spec.energy_total is None else spec.energy_total),
        _sf_word(SF_ENERGY),  # WH_SF
        _scaled_word(spec.dc_current, SF_CURRENT),
        _sf_word(SF_CURRENT),  # DCA_SF
        _scaled_word(spec.dc_voltage, SF_VOLTAGE),
        _sf_word(SF_VOLTAGE),  # DCV_SF
        _scaled_word(spec.dc_power, SF_POWER, signed=True),
        _sf_word(SF_POWER),  # DCW_SF
        _scaled_word(spec.cabinet_temperature, SF_TEMPERATURE, signed=True),
        _scaled_word(spec.heat_sink_temperature, SF_TEMPERATURE, signed=True),
        _scaled_word(spec.transformer_temperature, SF_TEMPERATURE, signed=True),
        _scaled_word(spec.other_temperature, SF_TEMPERATURE, signed=True),
        _sf_word(SF_TEMPERATURE),  # Tmp_SF
        _enum_word(spec.operating_state),
        _enum_word(spec.vendor_operating_state),
        *_uint32_words(spec.events),  # Evt1
        *_uint32_words(0),  # Evt2
        *_uint32_words(spec.vendor_events),  # EvtVnd1
        *_uint32_words(0),  # EvtVnd2
        *_uint32_words(0),  # EvtVnd3
        *_uint32_words(0),  # EvtVnd4
    ]


def _mppt_model_data(inputs: list[MpptInputSpec], *, energy_implemented: bool) -> list[int]:
    data = [
        _sf_word(SF_CURRENT),  # DCA_SF
        _sf_word(SF_VOLTAGE),  # DCV_SF
        _sf_word(SF_POWER),  # DCW_SF
        _sf_word(SF_ENERGY) if energy_implemented else NOT_IMPLEMENTED_INT16,  # DCWH_SF
        *_uint32_words(0),  # Evt
        len(inputs),  # N
        NOT_IMPLEMENTED_UINT16,  # TmsPer
    ]
    for number, mppt_input in enumerate(inputs, start=1):
        energy = mppt_input.energy if energy_implemented and mppt_input.energy else 0
        data += [
            number,  # ID
            *_string_words(mppt_input.id_str, 8),
            _scaled_word(mppt_input.current, SF_CURRENT),
            _scaled_word(mppt_input.voltage, SF_VOLTAGE),
            _scaled_word(mppt_input.power, SF_POWER),
            *_uint32_words(energy),  # DCWH
            *_uint32_words(NOT_IMPLEMENTED_UINT32),  # Tms
            NOT_IMPLEMENTED_INT16,  # Tmp
            _enum_word(mppt_input.operating_state),  # DCSt
            *_uint32_words(0),  # DCEvt
        ]
    return data


# Models 120, 121 and 123 exactly as a VSN300 (firmware 2.0.1) serves them
# for a PVI-10.0-OUTD, captured 2026-09-05: nearly everything unimplemented.
_NAMEPLATE_TEMPLATE = [
    NOT_IMPLEMENTED_ENUM16, 10000, 0, 0xFFFF, 0x8000, 0x8000, 0x8000, 0x8000, 0x8000, 0x8000,
    0xFFFF, 0x8000, 0x8000, 0x8000, 0x8000, 0x8000, 0x8000, 0xFFFF, 0x8000, 0xFFFF,
    0x8000, 0xFFFF, 0x8000, 0xFFFF, 0x8000, 0xFFFF,
]  # fmt: skip
_SETTINGS_TEMPLATE = [
    0, 0xFFFF, 0x8000, 0xFFFF, 0xFFFF, 0xFFFF, 0x8000, 0x8000, 0x8000, 0x8000,
    0xFFFF, 0x8000, 0x8000, 0x8000, 0x8000, 0xFFFF, 0xFFFF, 0xFFFF, 0xFFFF, 0xFFFF,
    0, 0x8000, 0x8000, 0x8000, 0x8000, 0x8000, 0x8000, 0x8000, 0x8000, 0x8000,
]  # fmt: skip
_CONTROLS_TEMPLATE = [
    0xFFFF, 0xFFFF, 0xFFFF, 100, 0xFFFF, 60, 60, 0, 0x8000, 0xFFFF,
    0xFFFF, 0xFFFF, 0xFFFF, 0x8000, 0x8000, 0x8000, 0xFFFF, 0xFFFF, 0xFFFF, 0xFFFF,
    0xFFFF, 0, 0x8000, 0x8000,
]  # fmt: skip


def _nameplate_model_data(rated_power: int | None, der_type: int | None) -> list[int]:
    data = list(_NAMEPLATE_TEMPLATE)
    data[0] = _enum_word(der_type)
    data[1] = NOT_IMPLEMENTED_UINT16 if rated_power is None else rated_power
    return data


def _controls_model_data(
    power_limit_pct: int | None, power_limit_enabled: bool, pf_implemented: bool
) -> list[int]:
    data = list(_CONTROLS_TEMPLATE)
    data[3] = NOT_IMPLEMENTED_UINT16 if power_limit_pct is None else power_limit_pct
    data[7] = int(power_limit_enabled)
    if pf_implemented:
        data[8] = 1000  # OutPFSet: cos phi 1.000
        data[12] = 0  # OutPFSet_Ena: disabled
        data[22] = _sf_word(-3)  # OutPFSet_SF
    return data


def _alarm_words(codes: list[int]) -> list[int]:
    registers = [0, 0, 0]
    for code in codes:
        registers[code // 31] |= 1 << (code % 31)
    words: list[int] = []
    for register in registers:
        words += _uint32_words(register)
    return words


def _vendor_model_data(spec: VendorSpec, length: int) -> list[int]:
    data = [
        NOT_IMPLEMENTED_UINT16,  # Version
        *_string_words(spec.hardware_version, 4),
        *_string_words(spec.parent, 8),
        spec.device_presence,
        _enum_word(spec.global_state),
        _enum_word(spec.inverter_state),
        _enum_word(spec.dc_state_1),
        _enum_word(spec.dc_state_2),
        *_uint32_words(NOT_IMPLEMENTED_UINT32 if spec.sys_time is None else spec.sys_time),
        *_alarm_words(spec.alarms),
        *_uint32_words(NOT_IMPLEMENTED_BITFIELD32) * 5,  # Alarm4..Alarm8
        *_float32_words(spec.day_wh),
        *_float32_words(spec.total_wh),
        *_float32_words(spec.partial_wh),
        *_float32_words(spec.week_wh),
        *_float32_words(spec.month_wh),
        *_float32_words(spec.year_wh),
        *_float32_words(spec.ac_voltage),
        *_float32_words(spec.ac_current),
        *_float32_words(spec.ac_power),
        *_float32_words(spec.ac_frequency),
        *_float32_words(spec.dc1_power),
        *_float32_words(spec.dc1_voltage),
        *_float32_words(spec.dc1_current),
        *_float32_words(spec.dc2_power),
        *_float32_words(spec.dc2_voltage),
        *_float32_words(spec.dc2_current),
        *_float32_words(spec.temperature),
        *_float32_words(spec.booster_temperature),
        *_float32_words(spec.isolation_1),
        *_float32_words(spec.isolation_2),
        *_float32_words(spec.wind_generator_frequency),
        *_float32_words(spec.cos_phi),
        0,
        0,
        0,
        0,  # pad 82..85
        NOT_IMPLEMENTED_UINT16,  # OutputW_Ramp
        NOT_IMPLEMENTED_UINT16,  # OutputW_Timeout
        NOT_IMPLEMENTED_UINT16,  # PF_Ramp
        NOT_IMPLEMENTED_UINT16,  # PF_Timeout
        NOT_IMPLEMENTED_ENUM16,  # Remote_Shutdown
        0,
        0,
        0,  # pad 91..93
        _enum_word(spec.output_power_permanent),  # OutputW_Perm
        NOT_IMPLEMENTED_ENUM16,  # OutputW_Perm_St
        *_float32_words(spec.pf_permanent),
        NOT_IMPLEMENTED_ENUM16,  # PF_Perm_St
        0,
        0,
        0,
        0,
        0,  # pad 99..103
        _enum_word(spec.output_power_dynamic),  # OutputW_Dynamic
        NOT_IMPLEMENTED_ENUM16,  # OutputW_Dynamic_St
        *_float32_words(spec.pf_dynamic),
        NOT_IMPLEMENTED_ENUM16,  # PF_Dynamic_St
        0,
        0,
        0,
        0,
        0,  # pad 109..113
        NOT_IMPLEMENTED_ENUM16,  # OutputW_Reset
        NOT_IMPLEMENTED_ENUM16,  # OutputW_Reset_St
        NOT_IMPLEMENTED_ENUM16,  # PF_Reset
        NOT_IMPLEMENTED_ENUM16,  # PF_Reset_St
    ]
    data += [0] * (ABB_VENDOR_MODEL_LENGTH - len(data))  # reserved tail
    if length < len(data):
        return data[:length]
    return data + [0] * (length - len(data))


def build_register_map(
    *,
    base_address: int = BASE_ADDRESS_DATALOGGER,
    manufacturer: str = "ABB",
    device_model: str = "VSN300",
    options: str = "X",
    version: str = "1.9.2",
    serial_number: str = "123456-3N01-1234",
    inverter: InverterSpec | None = None,
    three_phase: bool = True,
    mppt_inputs: list[MpptInputSpec] | None = None,
    mppt_energy_implemented: bool = False,
    include_mppt_model: bool = True,
    include_nameplate_model: bool = True,
    rated_power: int | None = 10000,
    der_type: int | None = 4,
    include_settings_model: bool = True,
    include_controls_model: bool = True,
    power_limit_pct: int | None = 100,
    power_limit_enabled: bool = False,
    power_factor_implemented: bool = False,
    vendor: VendorSpec | None = None,
    include_vendor_model: bool = False,
    vendor_model_length: int = ABB_VENDOR_MODEL_LENGTH,
    include_inverter_model: bool = True,
) -> dict[int, int]:
    """Build the holding registers of a SunSpec chain as a VSN300 serves it.

    The default chain is the one a VSN300 on firmware 2.0.1 serves for a
    PVI: models 1, 103, 160, 120, 121 and 123. The ABB vendor model 64061
    from the 2013 map is added only on request.

    The default ``options`` "X" decodes to a PVI-10.0-OUTD; pass ``"0x01"``
    for an UNO-DM-4.0-TL-PLUS, ``"0x0D"`` for a REACT2-UNO-5.0-TL, or an
    unknown code such as ``"?"`` to leave the inverter model undecoded.
    """
    registers: dict[int, int] = {
        base_address: 0x5375,  # "Su"
        base_address + 1: 0x6E53,  # "nS"
    }
    address = base_address + 2

    def add_model(model_id: int, data: list[int]) -> None:
        nonlocal address
        registers[address] = model_id
        registers[address + 1] = len(data)
        for offset, word in enumerate(data):
            registers[address + 2 + offset] = word
        address += 2 + len(data)

    add_model(
        COMMON_MODEL_ID,
        _common_model_data(manufacturer, device_model, options, version, serial_number),
    )
    if include_inverter_model:
        add_model(103 if three_phase else 101, _inverter_model_data(inverter or InverterSpec()))
    if include_mppt_model:
        inputs = (
            mppt_inputs
            if mppt_inputs is not None
            else [MpptInputSpec("String 1"), MpptInputSpec("String 2")]
        )
        add_model(
            MPPT_MODEL_ID, _mppt_model_data(inputs, energy_implemented=mppt_energy_implemented)
        )
    if include_nameplate_model:
        add_model(NAMEPLATE_MODEL_ID, _nameplate_model_data(rated_power, der_type))
    if include_settings_model:
        add_model(SETTINGS_MODEL_ID, list(_SETTINGS_TEMPLATE))
    if include_controls_model:
        add_model(
            CONTROLS_MODEL_ID,
            _controls_model_data(power_limit_pct, power_limit_enabled, power_factor_implemented),
        )
    if include_vendor_model:
        add_model(
            ABB_VENDOR_MODEL_ID, _vendor_model_data(vendor or VendorSpec(), vendor_model_length)
        )

    registers[address] = 0xFFFF  # end marker
    registers[address + 1] = 0
    return registers


__all__ = [
    "InverterSpec",
    "MpptInputSpec",
    "VendorSpec",
    "build_register_map",
]
