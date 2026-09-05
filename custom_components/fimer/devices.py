"""The devices of a config entry and the sources each one reads from.

A physical device can be reported by both sources: the inverter over
Modbus and over the datalogger's REST API. Its :class:`FimerDevice` reads a
point from Modbus when that source has it, and from REST otherwise, so an
entity never needs to know which transport delivered a value.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from homeassistant.core import CALLBACK_TYPE, callback
from homeassistant.helpers.device_registry import DeviceInfo

from .const import (
    DEVICE_TYPE_BATTERY,
    DEVICE_TYPE_DATALOGGER,
    DEVICE_TYPE_INVERTER,
    DEVICE_TYPE_METER,
    DOMAIN,
    MANUFACTURER,
)
from .pyfimer.rest import DEVICE_TYPE_DATALOGGER as REST_DATALOGGER

if TYPE_CHECKING:
    from .coordinator import FimerCoordinator, FimerRestCoordinator


@dataclass
class FimerDevice:
    """One Home Assistant device and the coordinators that report on it."""

    unique_id: str
    device_type: str
    device_info: DeviceInfo
    modbus: FimerCoordinator | None = None
    rest: FimerRestCoordinator | None = None
    rest_device_id: str | None = None
    """The key of this device in the REST coordinator's data."""
    listeners: list[Callable[[], None]] = field(default_factory=list, repr=False)

    @property
    def is_inverter(self) -> bool:
        """Whether this is the inverter, the device Modbus can report on."""
        return self.device_type == DEVICE_TYPE_INVERTER

    def _rest_values(self) -> dict[str, Any]:
        if self.rest is None or self.rest_device_id is None or not self.rest.last_update_success:
            return {}
        return self.rest.data.get(self.rest_device_id, {})

    def _modbus_values(self) -> dict[str, Any]:
        if self.modbus is None or not self.modbus.last_update_success:
            return {}
        return self.modbus.data

    def keys(self) -> set[str]:
        """Every point either source currently reports with a value."""
        keys = {key for key, value in self._modbus_values().items() if value is not None}
        keys |= {key for key, value in self._rest_values().items() if value is not None}
        return keys

    def value(self, key: str) -> Any:
        """The point's reading, Modbus first, REST when Modbus lacks it."""
        if (value := self._modbus_values().get(key)) is not None:
            return value
        return self._rest_values().get(key)

    def provides(self, key: str) -> bool:
        """Whether a working source reports this point at all, even as None."""
        return key in self._modbus_values() or key in self._rest_values()

    @property
    def available(self) -> bool:
        """Whether at least one source of this device is answering."""
        return bool(self._modbus_values()) or bool(self._rest_values())

    @callback
    def async_add_listener(self, update_callback: CALLBACK_TYPE) -> CALLBACK_TYPE:
        """Call back when either source refreshes; returns the unsubscribe."""
        removers = [
            coordinator.async_add_listener(update_callback)
            for coordinator in (self.modbus, self.rest)
            if coordinator is not None
        ]

        @callback
        def remove() -> None:
            for remover in removers:
                remover()

        return remove


def build_devices(
    entry_title: str,
    entry_unique_id: str,
    modbus: FimerCoordinator | None,
    rest: FimerRestCoordinator | None,
) -> list[FimerDevice]:
    """Describe the devices the sources report on, the inverter first."""
    devices: list[FimerDevice] = []
    datalogger_identifier: tuple[str, str] | None = None

    if rest is not None and rest.logger.discovered:
        identity = rest.logger.identity
        datalogger_identifier = (DOMAIN, identity.unique_id)
        devices.append(
            FimerDevice(
                unique_id=identity.unique_id,
                device_type=DEVICE_TYPE_DATALOGGER,
                device_info=DeviceInfo(
                    identifiers={datalogger_identifier},
                    name=str(identity.model),
                    manufacturer=MANUFACTURER,
                    model=identity.board_model or str(identity.model),
                    serial_number=identity.serial_number,
                    sw_version=identity.firmware_version,
                    configuration_url=f"http://{identity.hostname}" if identity.hostname else None,
                ),
                rest=rest,
                rest_device_id=_rest_datalogger_id(rest),
            )
        )

    inverter = _inverter_device(entry_title, entry_unique_id, modbus, rest)
    if inverter is not None:
        devices.insert(0, inverter)

    if rest is not None and rest.logger.discovered:
        for device_id, readings in rest.logger.devices.items():
            if readings.device_type == REST_DATALOGGER or readings.device_type.startswith(
                "inverter"
            ):
                continue
            device_type = (
                DEVICE_TYPE_BATTERY if readings.device_type == "battery" else DEVICE_TYPE_METER
            )
            devices.append(
                FimerDevice(
                    unique_id=device_id,
                    device_type=device_type,
                    device_info=DeviceInfo(
                        identifiers={(DOMAIN, device_id)},
                        name=f"{device_type.title()} {device_id}",
                        manufacturer=MANUFACTURER,
                        model=readings.model,
                        serial_number=device_id,
                    ),
                    rest=rest,
                    rest_device_id=device_id,
                )
            )
    return devices


def _rest_datalogger_id(rest: FimerRestCoordinator) -> str | None:
    return next(
        (
            device_id
            for device_id, readings in rest.logger.devices.items()
            if readings.device_type == REST_DATALOGGER
        ),
        None,
    )


def _inverter_device(
    entry_title: str,
    entry_unique_id: str,
    modbus: FimerCoordinator | None,
    rest: FimerRestCoordinator | None,
) -> FimerDevice | None:
    rest_id = None
    rest_readings = None
    if rest is not None and rest.logger.discovered:
        rest_id, rest_readings = next(
            (
                (device_id, readings)
                for device_id, readings in rest.logger.devices.items()
                if readings.device_type.startswith("inverter")
            ),
            (None, None),
        )
    if modbus is not None:
        identity = modbus.inverter.identity
        manufacturer = identity.manufacturer or MANUFACTURER
        model: str | None = identity.model or None
        firmware = identity.firmware_version or None
        serial = identity.serial_number or None
    elif rest_readings is not None:
        manufacturer = rest_readings.values.get("Mn") or MANUFACTURER
        model = rest_readings.model
        firmware = rest_readings.values.get("Vr")
        serial = rest_id
    else:
        return None

    return FimerDevice(
        unique_id=entry_unique_id,
        device_type=DEVICE_TYPE_INVERTER,
        device_info=DeviceInfo(
            identifiers={(DOMAIN, entry_unique_id)},
            name=entry_title,
            manufacturer=manufacturer,
            model=model,
            sw_version=firmware,
            serial_number=serial,
        ),
        modbus=modbus,
        rest=rest,
        rest_device_id=rest_id,
    )


def iter_device_points(devices: list[FimerDevice]) -> Iterator[tuple[FimerDevice, str]]:
    """Yield every (device, point) pair currently reported."""
    for device in devices:
        for key in sorted(device.keys()):
            yield device, key
