"""Sensor platform for the FIMER (ABB / Power-One) integration."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from homeassistant.components.sensor import (
    DOMAIN as SENSOR_DOMAIN,
    RestoreSensor,
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.components.sensor.const import DEVICE_CLASS_STATE_CLASSES, DEVICE_CLASS_UNITS
from homeassistant.const import (
    EntityCategory,
    UnitOfApparentPower,
    UnitOfElectricCurrent,
    UnitOfElectricPotential,
    UnitOfEnergy,
    UnitOfFrequency,
    UnitOfInformation,
    UnitOfPower,
    UnitOfRatio,
    UnitOfReactivePower,
    UnitOfTemperature,
    UnitOfTime,
)
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.typing import StateType

from . import FimerConfigEntry
from .const import DOMAIN
from .devices import FimerDevice
from .pyfimer import ALARM_CODES, DCDC_STATES, GLOBAL_STATES, INVERTER_STATES
from .pyfimer.modbus import Enabled, OperatingState
from .pyfimer.points import MPPT_INPUTS
from .pyfimer.rest import REST_POINTS, RestPoint

PARALLEL_UPDATES = 0

MEGA_OHM = "MΩ"
REVOLUTIONS_PER_MINUTE = "rpm"

type ValueFn = Callable[[Any], StateType | datetime]


@dataclass(frozen=True, kw_only=True)
class FimerSensorEntityDescription(SensorEntityDescription):
    """Describes a sensor reading one pyfimer point."""

    value_fn: ValueFn | None = None
    invalid_when_zero: bool = False
    """A lifetime counter reads 0 while the inverter boots; report unknown instead."""


def _aurora_state(states: dict[int, str]) -> ValueFn:
    """Return a converter from an Aurora state code to its name."""

    def convert(value: Any) -> str:
        return states.get(int(value), f"Unknown ({value})")

    return convert


def _operating_state(value: Any) -> str | None:
    return value.name.lower() if isinstance(value, OperatingState) else None


def _enabled_state(value: Any) -> str | None:
    return value.name.lower() if isinstance(value, Enabled) else None


def _timestamp(value: Any) -> datetime:
    return datetime.fromtimestamp(int(value), tz=UTC)


def _alarms(value: Any) -> str:
    return ", ".join(value) if value else "No alarm"


def _names(value: Any) -> str:
    return ", ".join(value) if value else "None"


WLAN_MODES = {0: "Access point", 1: "Station"}


def _measurement(
    key: str,
    translation_key: str,
    *,
    unit: str | None,
    device_class: SensorDeviceClass | None,
    precision: int,
    category: EntityCategory | None = None,
    enabled: bool = True,
    value_fn: ValueFn | None = None,
) -> FimerSensorEntityDescription:
    return FimerSensorEntityDescription(
        key=key,
        translation_key=translation_key,
        native_unit_of_measurement=unit,
        device_class=device_class,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=precision,
        entity_category=category,
        entity_registry_enabled_default=enabled,
        value_fn=value_fn,
    )


def _energy(
    key: str, translation_key: str, *, invalid_when_zero: bool = False, enabled: bool = True
) -> FimerSensorEntityDescription:
    return FimerSensorEntityDescription(
        key=key,
        translation_key=translation_key,
        native_unit_of_measurement=UnitOfEnergy.WATT_HOUR,
        suggested_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL_INCREASING,
        suggested_display_precision=3,
        entity_registry_enabled_default=enabled,
        invalid_when_zero=invalid_when_zero,
    )


def _aurora(key: str, translation_key: str, states: dict[int, str]) -> FimerSensorEntityDescription:
    return FimerSensorEntityDescription(
        key=key, translation_key=translation_key, value_fn=_aurora_state(states)
    )


def _current(key: str, translation_key: str, **kwargs: Any) -> FimerSensorEntityDescription:
    return _measurement(
        key,
        translation_key,
        unit=UnitOfElectricCurrent.AMPERE,
        device_class=SensorDeviceClass.CURRENT,
        precision=2,
        **kwargs,
    )


def _voltage(key: str, translation_key: str, **kwargs: Any) -> FimerSensorEntityDescription:
    return _measurement(
        key,
        translation_key,
        unit=UnitOfElectricPotential.VOLT,
        device_class=SensorDeviceClass.VOLTAGE,
        precision=1,
        **kwargs,
    )


def _power(key: str, translation_key: str, **kwargs: Any) -> FimerSensorEntityDescription:
    return _measurement(
        key,
        translation_key,
        unit=UnitOfPower.WATT,
        device_class=SensorDeviceClass.POWER,
        precision=0,
        **kwargs,
    )


def _temperature(key: str, translation_key: str, **kwargs: Any) -> FimerSensorEntityDescription:
    return _measurement(
        key,
        translation_key,
        unit=UnitOfTemperature.CELSIUS,
        device_class=SensorDeviceClass.TEMPERATURE,
        precision=1,
        **kwargs,
    )


def _mppt_descriptions(number: int) -> tuple[FimerSensorEntityDescription, ...]:
    return (
        _current(f"DCA_{number}", f"dc_current_input_{number}"),
        _voltage(f"DCV_{number}", f"dc_voltage_input_{number}"),
        _power(f"DCW_{number}", f"dc_power_input_{number}"),
        _energy(f"DCWH_{number}", f"dc_energy_input_{number}", invalid_when_zero=True),
    )


SENSOR_DESCRIPTIONS: tuple[FimerSensorEntityDescription, ...] = (
    # SunSpec inverter model
    _power("W", "ac_power"),
    _current("A", "ac_current"),
    _current("AphA", "ac_current_phase_a"),
    _current("AphB", "ac_current_phase_b"),
    _current("AphC", "ac_current_phase_c"),
    _voltage("PhVphA", "ac_voltage_phase_a"),
    _voltage("PhVphB", "ac_voltage_phase_b"),
    _voltage("PhVphC", "ac_voltage_phase_c"),
    _voltage("PhVphAB", "ac_voltage_phase_ab"),
    _voltage("PhVphBC", "ac_voltage_phase_bc"),
    _voltage("PhVphCA", "ac_voltage_phase_ca"),
    _measurement(
        "Hz",
        "ac_frequency",
        unit=UnitOfFrequency.HERTZ,
        device_class=SensorDeviceClass.FREQUENCY,
        precision=2,
    ),
    _measurement(
        "VA",
        "apparent_power",
        unit=UnitOfApparentPower.VOLT_AMPERE,
        device_class=SensorDeviceClass.APPARENT_POWER,
        precision=0,
    ),
    _measurement(
        "VAr",
        "reactive_power",
        unit=UnitOfReactivePower.VOLT_AMPERE_REACTIVE,
        device_class=SensorDeviceClass.REACTIVE_POWER,
        precision=0,
    ),
    _measurement(
        "PF",
        "power_factor",
        unit=UnitOfRatio.PERCENTAGE,
        device_class=SensorDeviceClass.POWER_FACTOR,
        precision=1,
    ),
    _energy("WH", "ac_energy_total", invalid_when_zero=True),
    _current("DCA", "dc_current"),
    _voltage("DCV", "dc_voltage"),
    _power("DCW", "dc_power"),
    _temperature("TmpCab", "cabinet_temperature"),
    _temperature("TmpSnk", "heat_sink_temperature"),
    _temperature("TmpTrns", "transformer_temperature"),
    _temperature("TmpOt", "other_temperature"),
    FimerSensorEntityDescription(
        key="St",
        translation_key="operating_state",
        device_class=SensorDeviceClass.ENUM,
        options=[state.name.lower() for state in OperatingState],
        value_fn=_operating_state,
    ),
    FimerSensorEntityDescription(
        key="StVnd",
        translation_key="vendor_operating_state",
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
    ),
    FimerSensorEntityDescription(
        key="Events",
        translation_key="events",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=_names,
    ),
    # SunSpec multiple MPPT model
    *(
        description
        for number in range(1, MPPT_INPUTS + 1)
        for description in _mppt_descriptions(number)
    ),
    # SunSpec nameplate and immediate controls models
    FimerSensorEntityDescription(
        key="WRtg",
        translation_key="rated_power",
        native_unit_of_measurement=UnitOfPower.WATT,
        device_class=SensorDeviceClass.POWER,
        suggested_display_precision=0,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    _measurement(
        "WMaxLimPct",
        "power_limit",
        unit=UnitOfRatio.PERCENTAGE,
        device_class=None,
        precision=0,
        category=EntityCategory.DIAGNOSTIC,
    ),
    FimerSensorEntityDescription(
        key="WMaxLim_Ena",
        translation_key="power_limit_enabled",
        device_class=SensorDeviceClass.ENUM,
        options=[state.name.lower() for state in Enabled],
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=_enabled_state,
    ),
    # ABB vendor model, over Modbus or REST
    _aurora("GlobalSt", "global_state", GLOBAL_STATES),
    _aurora("InverterSt", "inverter_state", INVERTER_STATES),
    _aurora("DcSt1", "dc_input_1_state", DCDC_STATES),
    _aurora("DcSt2", "dc_input_2_state", DCDC_STATES),
    _aurora("DcSt3", "dc_input_3_state", DCDC_STATES),
    _aurora("AlarmSt", "alarm_state", ALARM_CODES),
    FimerSensorEntityDescription(key="Alarms", translation_key="alarms", value_fn=_alarms),
    FimerSensorEntityDescription(
        key="SysTime",
        translation_key="system_time",
        device_class=SensorDeviceClass.TIMESTAMP,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=_timestamp,
    ),
    _energy("DayWH", "energy_today"),
    _energy("WeekWH", "energy_this_week"),
    _energy("MonthWH", "energy_this_month"),
    _energy("YearWH", "energy_this_year"),
    _energy("TotalWH", "energy_total_vendor", invalid_when_zero=True, enabled=False),
    _energy("PartialWH", "energy_partial", enabled=False),
    _temperature("Tmp", "inverter_temperature"),
    _temperature("Booster_Tmp", "booster_temperature"),
    _measurement(
        "Isolation_Ohm1",
        "isolation_resistance_input_1",
        unit=MEGA_OHM,
        device_class=None,
        precision=2,
    ),
    _measurement(
        "Isolation_Ohm2",
        "isolation_resistance_input_2",
        unit=MEGA_OHM,
        device_class=None,
        precision=2,
    ),
    _measurement(
        "Inverter_CosPhi",
        "cos_phi",
        unit=None,
        device_class=SensorDeviceClass.POWER_FACTOR,
        precision=3,
    ),
    _measurement(
        "OutputW_Perm",
        "power_limit_permanent",
        unit=UnitOfRatio.PERCENTAGE,
        device_class=None,
        precision=0,
        category=EntityCategory.DIAGNOSTIC,
    ),
    _measurement(
        "OutputW_Dynamic",
        "power_limit_dynamic",
        unit=UnitOfRatio.PERCENTAGE,
        device_class=None,
        precision=0,
        category=EntityCategory.DIAGNOSTIC,
    ),
    # datalogger points that carry a state table
    FimerSensorEntityDescription(
        key="wlan0_mode",
        translation_key="wlan0_mode",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=_aurora_state(WLAN_MODES),
    ),
)

_REST_UNITS: dict[str, str | None] = {
    "W": UnitOfPower.WATT,
    "Wh": UnitOfEnergy.WATT_HOUR,
    "V": UnitOfElectricPotential.VOLT,
    "A": UnitOfElectricCurrent.AMPERE,
    "mA": UnitOfElectricCurrent.MILLIAMPERE,
    "Hz": UnitOfFrequency.HERTZ,
    "var": UnitOfReactivePower.VOLT_AMPERE_REACTIVE,
    "%": UnitOfRatio.PERCENTAGE,
    "°C": UnitOfTemperature.CELSIUS,
    "MB": UnitOfInformation.MEGABYTES,
    "RPM": REVOLUTIONS_PER_MINUTE,
    "MΩ": MEGA_OHM,
    "s": UnitOfTime.SECONDS,
    "VAh": "VAh",
    "kVAh": "kVAh",
    "channels": None,
}
_REST_CATEGORIES = {
    "diagnostic": EntityCategory.DIAGNOSTIC,
    "config": EntityCategory.CONFIG,
}


def _rest_description(point: RestPoint) -> FimerSensorEntityDescription:
    """Build a description for a point only the REST feeds provide, from the mapping."""
    unit = _REST_UNITS.get(point.unit or "", point.unit)
    device_class: SensorDeviceClass | None = None
    if point.device_class:
        try:
            device_class = SensorDeviceClass(point.device_class)
        except ValueError:
            device_class = None
    if device_class is not None and (
        (device_class in DEVICE_CLASS_UNITS and unit not in DEVICE_CLASS_UNITS[device_class])
        or (device_class is SensorDeviceClass.ENUM)
    ):
        device_class = None
    state_class: SensorStateClass | None = None
    if point.state_class:
        try:
            state_class = SensorStateClass(point.state_class)
        except ValueError:
            state_class = None
    if (
        state_class is not None
        and device_class is not None
        and device_class in DEVICE_CLASS_STATE_CLASSES
        and state_class not in DEVICE_CLASS_STATE_CLASSES[device_class]
    ):
        state_class = None
    energy = device_class is SensorDeviceClass.ENERGY
    numeric = unit is not None or state_class is not None or device_class is not None
    return FimerSensorEntityDescription(
        key=point.name,
        translation_key=point.ha_name,
        native_unit_of_measurement=unit,
        suggested_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR if energy else None,
        device_class=device_class,
        state_class=state_class,
        suggested_display_precision=(3 if energy else point.precision) if numeric else None,
        entity_category=_REST_CATEGORIES.get(point.entity_category or ""),
        invalid_when_zero=energy and point.scope == "lifetime",
    )


_HAND_WRITTEN = {description.key for description in SENSOR_DESCRIPTIONS}
REST_SENSOR_DESCRIPTIONS: tuple[FimerSensorEntityDescription, ...] = tuple(
    _rest_description(point) for point in REST_POINTS if point.name not in _HAND_WRITTEN
)
ALL_DESCRIPTIONS: tuple[FimerSensorEntityDescription, ...] = (
    *SENSOR_DESCRIPTIONS,
    *REST_SENSOR_DESCRIPTIONS,
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: FimerConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Add a sensor for every point each device reports, as it reports it.

    An inverter only implements some of the SunSpec points, and a point
    can appear later (a counter that reads as not implemented until the
    inverter has fully booted), so sensors are created for the points seen
    so far and every later refresh adds the newly seen ones. Sensors
    registered by an earlier run come back right away, so an energy counter
    not yet reported shows its restored value.
    """
    entity_registry = er.async_get(hass)
    for device in entry.runtime_data.devices:
        pending = {description.key: description for description in ALL_DESCRIPTIONS}
        known = {
            key
            for key in pending
            if entity_registry.async_get_entity_id(
                SENSOR_DOMAIN, DOMAIN, f"{device.unique_id}_{key}"
            )
        }

        @callback
        def _async_add_seen_sensors(
            device: FimerDevice = device,
            pending: dict[str, FimerSensorEntityDescription] = pending,
            known: set[str] = known,
        ) -> None:
            seen = [key for key in pending if key in known or device.value(key) is not None]
            if seen:
                async_add_entities(_sensor_for(device, pending.pop(key)) for key in seen)

        _async_add_seen_sensors()
        entry.async_on_unload(device.async_add_listener(_async_add_seen_sensors))


def _sensor_for(device: FimerDevice, description: FimerSensorEntityDescription) -> FimerSensor:
    if description.state_class is SensorStateClass.TOTAL_INCREASING:
        return FimerEnergySensor(device, description)
    return FimerSensor(device, description)


class FimerSensor(SensorEntity):
    """A sensor reading one point of a device, from whichever source has it."""

    entity_description: FimerSensorEntityDescription
    _attr_has_entity_name = True
    _attr_should_poll = False

    def __init__(self, device: FimerDevice, description: FimerSensorEntityDescription) -> None:
        """Set up the sensor for a point of the device."""
        self.device = device
        self.entity_description = description
        self._attr_unique_id = f"{device.unique_id}_{description.key}"
        self._attr_device_info = device.device_info

    async def async_added_to_hass(self) -> None:
        """Refresh whenever either source of the device refreshes."""
        await super().async_added_to_hass()
        self.async_on_remove(self.device.async_add_listener(self.async_write_ha_state))

    @property
    def available(self) -> bool:
        """Available while a working source reports the point."""
        return self.device.provides(self.entity_description.key)

    @property
    def native_value(self) -> StateType | datetime:
        """Return the point's last reading."""
        description = self.entity_description
        value = self.device.value(description.key)
        if value is None or (description.invalid_when_zero and not value):
            return None
        if description.value_fn is not None:
            return description.value_fn(value)
        return value


class FimerEnergySensor(FimerSensor, RestoreSensor):
    """An energy counter that keeps its last value while the device sleeps.

    A PVI without grid power at night answers nothing, and an energy
    sensor going unavailable every evening would leave gaps in the
    long-term statistics. The last reading is kept instead, restored across
    restarts.
    """

    _last_value: float | None = None

    async def async_added_to_hass(self) -> None:
        """Restore the last reading if no source has one yet."""
        await super().async_added_to_hass()
        if (
            self._last_value is not None
            or (data := await self.async_get_last_sensor_data()) is None
        ):
            return
        if isinstance(data.native_value, (int, float)):
            self._last_value = data.native_value

    @property
    def available(self) -> bool:
        """Stay available with the last reading while the device is offline."""
        return super().available or self._last_value is not None

    @property
    def native_value(self) -> float | None:
        """Return the latest reading, or the last one while the device is offline."""
        if isinstance(value := super().native_value, (int, float)):
            self._last_value = value
        return self._last_value
