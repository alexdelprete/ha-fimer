"""High-level access to a VSN300 or VSN700 datalogger over its REST API."""

# ruff: noqa: TID252 - parent-relative imports keep the package movable to PyPI

from __future__ import annotations

from dataclasses import dataclass
import logging
from typing import Any, Final

import aiohttp

from ..exceptions import (
    FimerConnectionError,
    FimerDataError,
    FimerNotDiscoveredError,
    FimerUnsupportedFirmwareError,
)
from .client import DEFAULT_TIMEOUT, DEFAULT_USERNAME, VsnModel, VsnRestClient
from .normalizer import DeviceReadings, normalize_livedata

_LOGGER = logging.getLogger(__name__)
UNSUPPORTED_VSN300_FIRMWARE: Final = "2.0.0"
"""Drops the TCP connection on every livedata request; fixed in 2.0.1."""


@dataclass(frozen=True, slots=True)
class LoggerIdentity:
    """What the status endpoint says about the datalogger."""

    model: VsnModel
    serial_number: str
    """The VSN300's serial, or the VSN700's MAC address."""
    firmware_version: str | None
    board_model: str | None
    hostname: str | None

    @property
    def unique_id(self) -> str:
        """A registry-safe identifier: the serial, or the MAC without colons."""
        return self.serial_number.replace(":", "")


class FimerRestLogger:
    """A datalogger and the devices behind it, read over REST.

    Call :meth:`discover` once: it identifies the card, reads its status
    and a first livedata response, and fills :attr:`identity` and
    :attr:`devices`. Then :meth:`async_update` refreshes the readings and
    :meth:`values` returns them per device, keyed by vocabulary point name::

        logger = FimerRestLogger(session, "192.0.2.10", password="secret")
        await logger.discover()
        await logger.async_update()
        logger.values()["077909-3G82-3112"]["W"]
    """

    def __init__(
        self,
        session: aiohttp.ClientSession,
        host: str,
        *,
        username: str = DEFAULT_USERNAME,
        password: str = "",
        timeout: float = DEFAULT_TIMEOUT,
        model: VsnModel | None = None,
        requires_auth: bool = True,
    ) -> None:
        """Set up for a host; ``model`` and ``requires_auth`` skip detection when known."""
        self.client = VsnRestClient(
            session,
            host,
            username=username,
            password=password,
            timeout=timeout,
            model=model,
            requires_auth=requires_auth,
        )
        self._identity: LoggerIdentity | None = None
        self._status: dict[str, Any] = {}
        self._readings: dict[str, DeviceReadings] = {}

    @property
    def discovered(self) -> bool:
        """Whether :meth:`discover` has succeeded."""
        return self._identity is not None

    @property
    def identity(self) -> LoggerIdentity:
        """The datalogger identification read during discovery."""
        if self._identity is None:
            raise FimerNotDiscoveredError("Logger not discovered; call discover() first")
        return self._identity

    @property
    def model(self) -> VsnModel | None:
        """The card family, once detected."""
        return self.client.model

    @property
    def requires_auth(self) -> bool:
        """Whether the card wants credentials, once detected."""
        return self.client.requires_auth

    @property
    def devices(self) -> dict[str, DeviceReadings]:
        """The devices seen in the last livedata response, by device ID."""
        return self._readings

    @property
    def status(self) -> dict[str, Any]:
        """The last status response, for diagnostics."""
        return self._status

    async def discover(self) -> None:
        """Identify the card, read its status and a first set of readings."""
        model = await self.client.detect()
        self._status = await self.client.get_status()
        try:
            keys = self._status.get("keys", {})
            firmware = keys.get("fw.release_number", {}).get("value")
        except (AttributeError, TypeError) as err:
            raise FimerDataError(f"Unreadable status from {self.client.base_url}: {err}") from err
        try:
            livedata = await self.client.get_livedata()
        except FimerConnectionError as err:
            if model is VsnModel.VSN300 and firmware == UNSUPPORTED_VSN300_FIRMWARE:
                raise FimerUnsupportedFirmwareError(
                    f"VSN300 firmware {firmware} cannot serve livedata; update to 2.0.1 or later",
                    firmware_version=firmware,
                ) from err
            raise
        try:
            serial = keys.get("logger.sn", {}).get("value") or keys.get("logger.loggerId", {}).get(
                "value", ""
            )
            self._identity = LoggerIdentity(
                model=model,
                serial_number=serial,
                firmware_version=firmware,
                board_model=keys.get("logger.board_model", {}).get("value"),
                hostname=keys.get("logger.hostname", {}).get("value"),
            )
            self._readings = _normalize(model, livedata, self._status)
        except (AttributeError, TypeError) as err:
            raise FimerDataError(f"Unreadable status from {self.client.base_url}: {err}") from err
        _LOGGER.info(
            "Discovered %s %s (firmware %s) at %s serving %s",
            model,
            serial,
            firmware,
            self.client.base_url,
            _describe_devices(self._readings),
        )

    async def async_update(self) -> None:
        """Refresh every device's readings."""
        identity = self.identity
        livedata = await self.client.get_livedata()
        if identity.model is VsnModel.VSN300:
            # the datalogger's WiFi state lives only in the status endpoint
            self._status = await self.client.get_status()
        self._readings = _normalize(identity.model, livedata, self._status)
        _LOGGER.debug(
            "Updated %s at %s: %s",
            identity.model,
            self.client.base_url,
            _describe_devices(self._readings),
        )

    def values(self) -> dict[str, dict[str, Any]]:
        """Return the last readings of every device keyed by device ID, then point name."""
        return {device_id: dict(device.values) for device_id, device in self._readings.items()}


def _normalize(
    model: VsnModel, livedata: Any, status: dict[str, Any] | None
) -> dict[str, DeviceReadings]:
    """Normalise a livedata payload, turning a malformed one into a data error."""
    try:
        return normalize_livedata(model, livedata, status)
    except (AttributeError, KeyError, TypeError, ValueError) as err:
        raise FimerDataError(f"Unreadable livedata: {err}") from err


def _describe_devices(readings: dict[str, DeviceReadings]) -> str:
    """A one-line summary of the devices and their point counts for the log."""
    if not readings:
        return "no devices"
    return ", ".join(
        f"{device_id} ({device.device_type}, {len(device.values)} points)"
        for device_id, device in readings.items()
    )
