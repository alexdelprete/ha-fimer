"""DataUpdateCoordinator for ABB/FIMER PVI VSN Modbus."""

from __future__ import annotations

from datetime import timedelta
import logging
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)
SCAN_INTERVAL = 30


class AbbFimerPviVsnModbusCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    """Coordinator for ABB/FIMER PVI VSN Modbus."""

    def __init__(self, hass: HomeAssistant) -> None:
        """Initialize the coordinator."""
        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=timedelta(seconds=SCAN_INTERVAL),
        )

    async def _async_update_data(self) -> dict[str, Any]:
        """Fetch data from the device."""
        try:
            # TODO: Implement data fetching
            return {}
        except Exception as err:
            raise UpdateFailed(f"Error communicating with device: {err}") from err
