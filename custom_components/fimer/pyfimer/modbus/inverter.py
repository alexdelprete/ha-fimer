"""High-level access to one FIMER inverter over a Modbus unit."""

# ruff: noqa: TID252 - parent-relative imports keep the package movable to PyPI

from __future__ import annotations

from dataclasses import dataclass
import logging
from typing import Any

from modbus_connection import ModbusUnit
from modbus_connection.model import ComponentGroup

from ..aurora import inverter_model_from_options
from ..exceptions import FimerNotDiscoveredError, FimerUnsupportedDeviceError
from .models import (
    Common,
    Controls,
    FimerComponent,
    FixedComponent,
    Inverter,
    InverterFloat,
    Mppt,
    Nameplate,
    Settings,
    Storage,
)
from .registers import ModbusRegisters
from .sunspec import (
    ABB_VENDOR_MODEL_ID,
    ABB_VENDOR_MODEL_LENGTH,
    BASE_ADDRESS_DATALOGGER,
    COMMON_MODEL_ID,
    CONTROLS_MODEL_ID,
    INVERTER_MODEL_IDS,
    INVERTER_MODEL_IDS_FLOAT,
    MPPT_MODEL_ID,
    NAMEPLATE_MODEL_ID,
    SETTINGS_MODEL_ID,
    STORAGE_MODEL_ID,
    STRING_COMBINER_MODEL_ID,
    TRIO_COMM_BOARD_MODEL_ID,
    TRIO_FUSE_BOARD_MODEL_ID,
    SunSpecModel,
    SunSpecModels,
    scan,
)
from .trio import StringCombiner, TrioCommBoard, TrioFuseBoard
from .vendor import AbbVendor

_LOGGER = logging.getLogger(__name__)

_PHASES_BY_MODEL_ID = {101: 1, 102: 2, 103: 3, 111: 1, 112: 2, 113: 3}


@dataclass(frozen=True, slots=True)
class DeviceIdentity:
    """What the common model says about the device."""

    manufacturer: str
    device_model: str
    """The ``Md`` string: the datalogger's own model when one is in the way."""
    options: str
    firmware_version: str
    serial_number: str
    inverter_model: str | None
    """The inverter model decoded from ``Opt``, when the code is known."""

    @property
    def model(self) -> str:
        """The best available model name."""
        return self.inverter_model or self.device_model


class FimerModbusInverter:
    """A FIMER inverter's SunSpec models on one Modbus unit.

    Call :meth:`discover` once: it walks the model chain, builds a component
    per supported model (``None`` for models the device lacks) and reads the
    common model so :attr:`identity` is available. Then :meth:`async_update`
    refreshes every model in as few reads as possible and :meth:`values`
    returns the readings keyed by point name::

        inverter = FimerModbusInverter(unit, base_address=0)
        await inverter.discover()
        await inverter.async_update()
        inverter.values()["W"]

    The power limit is set through ``controls.set_power_limit()``. Any
    writable point goes through :meth:`async_write`. Register layouts
    outside the SunSpec map are polled alongside through
    :meth:`add_component`, and ad hoc reads and writes go through
    :attr:`registers`.

    Every component verifies its model header on each read and raises
    ``SunSpecMapShiftError`` when the map moved (a firmware update, a
    changed datalogger setting). Recover by calling :meth:`discover` again
    on this object, which rebuilds the components at the new addresses.
    """

    def __init__(self, unit: ModbusUnit, base_address: int = BASE_ADDRESS_DATALOGGER) -> None:
        """Initialize with a unit addressing the inverter and its SunSpec base."""
        self._unit = unit
        self._base_address = base_address
        self._registers = ModbusRegisters(unit)
        self._models = SunSpecModels()
        self._group: ComponentGroup | None = None
        self.common: Common | None = None
        self.inverter: Inverter | InverterFloat | None = None
        self.mppt: Mppt | None = None
        self.nameplate: Nameplate | None = None
        self.settings: Settings | None = None
        self.controls: Controls | None = None
        self.storage: Storage | None = None
        self.combiners: list[StringCombiner] = []
        self.comm_board: TrioCommBoard | None = None
        self.fuse_board: TrioFuseBoard | None = None
        self.vendor: AbbVendor | None = None
        self.vendor_model_length: int | None = None
        self._extras: list[FixedComponent] = []
        """The length the device reports for model 64061, for diagnostics."""

    @property
    def registers(self) -> ModbusRegisters:
        """Classic register access on the same unit, for what SunSpec does not cover.

        Usable before and without :meth:`discover`.
        """
        return self._registers

    @property
    def base_address(self) -> int:
        """The SunSpec base address this inverter was discovered at."""
        return self._base_address

    @property
    def discovered(self) -> bool:
        """Whether :meth:`discover` has succeeded."""
        return self._group is not None

    async def discover(self) -> None:
        """Discover the SunSpec models, build their components, read identity.

        Raises ``SunSpecError`` when no SunSpec marker sits at the base
        address, ``ModbusError`` on a transport failure, and
        :class:`FimerUnsupportedDeviceError` when the chain has no common or
        inverter model.
        """
        self._models = await scan(self._unit, self._base_address)
        common = self._models.first(COMMON_MODEL_ID)
        inverter = self._models.first(
            *sorted(INVERTER_MODEL_IDS), *sorted(INVERTER_MODEL_IDS_FLOAT)
        )
        if common is None or inverter is None:
            found = [model.model_id for model in self.model_chain_of(self._models)]
            raise FimerUnsupportedDeviceError(
                f"No SunSpec inverter at base address {self._base_address}: models {found}"
            )
        unit = self._unit
        self.common = Common(unit, common)
        self.inverter = (
            InverterFloat(unit, inverter)
            if inverter.model_id in INVERTER_MODEL_IDS_FLOAT
            else Inverter(unit, inverter)
        )
        mppt = self._models.first(MPPT_MODEL_ID)
        self.mppt = Mppt(unit, mppt) if mppt else None
        nameplate = self._models.first(NAMEPLATE_MODEL_ID)
        self.nameplate = Nameplate(unit, nameplate) if nameplate else None
        settings = self._models.first(SETTINGS_MODEL_ID)
        self.settings = Settings(unit, settings) if settings else None
        controls = self._models.first(CONTROLS_MODEL_ID)
        self.controls = Controls(unit, controls) if controls else None
        storage = self._models.first(STORAGE_MODEL_ID)
        self.storage = Storage(unit, storage) if storage else None
        self.combiners = [
            StringCombiner(unit, model, number=number)
            for number, model in enumerate(self._models.get(STRING_COMBINER_MODEL_ID, []), start=1)
        ]
        comm_board = self._models.first(TRIO_COMM_BOARD_MODEL_ID)
        self.comm_board = TrioCommBoard(unit, comm_board) if comm_board else None
        fuse_board = self._models.first(TRIO_FUSE_BOARD_MODEL_ID)
        self.fuse_board = TrioFuseBoard(unit, fuse_board) if fuse_board else None
        vendor = self._models.first(ABB_VENDOR_MODEL_ID)
        self.vendor_model_length = vendor.length if vendor else None
        if vendor is not None and vendor.length != ABB_VENDOR_MODEL_LENGTH:
            _LOGGER.warning(
                "Vendor model %s has length %s, expected %s; its points are skipped",
                ABB_VENDOR_MODEL_ID,
                vendor.length,
                ABB_VENDOR_MODEL_LENGTH,
            )
            vendor = None
        self.vendor = AbbVendor(unit, vendor) if vendor else None
        self._rebuild_group()
        await self.common.async_update()

    def add_component(self, component: FixedComponent) -> None:
        """Poll a register layout outside the SunSpec map along with the models.

        Usable before or after :meth:`discover`; the component is read on
        every :meth:`async_update` and its points appear in :meth:`values`.
        """
        self._extras.append(component)
        if self._group is not None:
            self._rebuild_group()

    def _rebuild_group(self) -> None:
        self._group = ComponentGroup(self._unit, [*self.components, *self._extras])

    @property
    def components(self) -> tuple[FimerComponent, ...]:
        """Every discovered model component, in chain order."""
        return tuple(
            component
            for component in (
                self.common,
                self.inverter,
                self.mppt,
                self.nameplate,
                self.settings,
                self.controls,
                self.storage,
                *self.combiners,
                self.comm_board,
                self.fuse_board,
                self.vendor,
            )
            if component is not None
        )

    async def async_update(self) -> None:
        """Refresh every discovered model in as few Modbus reads as possible."""
        if self._group is None:
            raise FimerNotDiscoveredError("No models discovered; call discover() first")
        await self._group.async_update()

    async def async_write(self, point: str, value: Any) -> None:
        """Write a writable SunSpec point by name, whichever model owns it.

        Raises :class:`FimerNotDiscoveredError` before discovery,
        ``AttributeError`` for an unknown or read-only point and
        ``ValueError`` for a value the point cannot encode.
        """
        if self._group is None:
            raise FimerNotDiscoveredError("No models discovered; call discover() first")
        for component in (*self.components, *self._extras):
            if point in component.declared_fields:
                await component.write(point, value)
                return
        raise AttributeError(f"No discovered model has a point named {point!r}")

    async def async_read_raw(self) -> dict[str, dict[int, int | bool]]:
        """Return every register of every discovered model, for diagnostics."""
        if self._group is None:
            raise FimerNotDiscoveredError("No models discovered; call discover() first")
        return await self._group.async_read_raw()

    @staticmethod
    def model_chain_of(models: SunSpecModels) -> list[SunSpecModel]:
        """Return the models of a scan result in address order."""
        return sorted(
            (model for found in models.values() for model in found),
            key=lambda model: model.address,
        )

    @property
    def model_chain(self) -> list[SunSpecModel]:
        """The discovered SunSpec models in address order."""
        return self.model_chain_of(self._models)

    @property
    def float_models(self) -> bool | None:
        """Whether the inverter serves the float models (111 to 113)."""
        if self.inverter is None:
            return None
        return isinstance(self.inverter, InverterFloat)

    @property
    def phases(self) -> int | None:
        """The number of AC phases, from the inverter model found."""
        if self.inverter is None:
            return None
        return _PHASES_BY_MODEL_ID.get(self.inverter.model_id)

    @property
    def identity(self) -> DeviceIdentity:
        """The device identification read during discovery."""
        if self.common is None:
            raise FimerNotDiscoveredError("No models discovered; call discover() first")
        options = self.common.Opt or ""
        return DeviceIdentity(
            manufacturer=self.common.Mn or "",
            device_model=self.common.Md or "",
            options=options,
            firmware_version=self.common.Vr or "",
            serial_number=self.common.SN or "",
            inverter_model=inverter_model_from_options(options),
        )

    @property
    def extra_components(self) -> tuple[FixedComponent, ...]:
        """The register layouts added with :meth:`add_component`."""
        return tuple(self._extras)

    def values(self) -> dict[str, Any]:
        """Return the last readings of every model and extra layout keyed by point name."""
        values: dict[str, Any] = {}
        for component in (*self.components, *self._extras):
            values.update(component.values())
        return values
