"""Base entity for the FIMER (ABB / Power-One) integration."""

from __future__ import annotations

from homeassistant.helpers.entity import EntityDescription
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .coordinator import FimerCoordinator


class FimerEntity(CoordinatorEntity[FimerCoordinator]):
    """An entity of one inverter, keyed by a pyfimer point name."""

    _attr_has_entity_name = True

    def __init__(self, coordinator: FimerCoordinator, description: EntityDescription) -> None:
        """Set up the entity for a point of the coordinator's inverter."""
        super().__init__(coordinator)
        self.entity_description = description
        self._attr_unique_id = f"{coordinator.device_unique_id}_{description.key}"
        self._attr_device_info = coordinator.device_info
