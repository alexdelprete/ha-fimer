"""HTTP transport for the VSN300 and VSN700 datalogger REST API.

Consumes an ``aiohttp.ClientSession`` handed in by the caller; the session
lifecycle stays with the caller (in Home Assistant, the shared session).
"""

# ruff: noqa: TID252 - parent-relative imports keep the package movable to PyPI

from __future__ import annotations

from enum import StrEnum
import json
import logging
import re
from typing import Any, Final

import aiohttp

from ..exceptions import (
    FimerAuthenticationError,
    FimerConnectionError,
    FimerDetectionError,
    FimerUnsupportedDeviceError,
)
from .auth import basic_credentials, build_digest_header, parse_digest_challenge

_LOGGER = logging.getLogger(__name__)

ENDPOINT_STATUS: Final = "/v1/status"
ENDPOINT_LIVEDATA: Final = "/v1/livedata"
ENDPOINT_FEEDS: Final = "/v1/feeds"

DEFAULT_USERNAME: Final = "guest"
DEFAULT_TIMEOUT: Final = 10

_VSN300_SERIAL = re.compile(r"^\d{6}-\w{4}-\d{4}$")
_MAC_ADDRESS = re.compile(r"^([0-9a-fA-F]{2}:){5}[0-9a-fA-F]{2}$")


class VsnModel(StrEnum):
    """The datalogger card families."""

    VSN300 = "VSN300"
    VSN700 = "VSN700"


class VsnRestClient:
    """Raw access to the datalogger's REST endpoints.

    :meth:`detect` identifies the card and whether it wants credentials;
    the fetch methods then authenticate accordingly on every request, since
    the VSN300 issues a fresh digest challenge each time.
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
        """Set up for a host name, IP address or full base URL."""
        self._session = session
        self.base_url = host.rstrip("/") if "://" in host else f"http://{host}"
        self._username = username
        self._password = password
        self._timeout = aiohttp.ClientTimeout(total=timeout)
        self.model = model
        self.requires_auth = requires_auth

    async def detect(self) -> VsnModel:
        """Identify the card and its authentication from the status endpoint.

        A 401 with a digest challenge is a VSN300; a 401 that accepts basic
        credentials is a VSN700; a 200 without credentials is an open card,
        identified from the status keys; a 404 is not a VSN datalogger.
        """
        url = f"{self.base_url}{ENDPOINT_STATUS}"
        try:
            async with self._session.get(url, timeout=self._timeout) as response:
                if response.status == 401:
                    challenge = response.headers.get("WWW-Authenticate", "")
                    if "digest" in challenge.lower():
                        self.model, self.requires_auth = VsnModel.VSN300, True
                        return self.model
                elif response.status == 200:
                    self.model = _model_from_status(await _read_json(response))
                    self.requires_auth = False
                    return self.model
                elif response.status == 404:
                    raise FimerUnsupportedDeviceError(
                        f"{self.base_url} has no VSN REST API (HTTP 404)"
                    )
                else:
                    raise FimerDetectionError(
                        f"Unexpected HTTP {response.status} from {url} during detection"
                    )
            # not a digest challenge: try the VSN700's preemptive basic credentials
            headers = {
                "Authorization": f"Basic {basic_credentials(self._username, self._password)}"
            }
            async with self._session.get(url, headers=headers, timeout=self._timeout) as response:
                if response.status in (200, 204):
                    self.model, self.requires_auth = VsnModel.VSN700, True
                    return self.model
                raise FimerDetectionError(
                    f"Neither digest nor basic authentication accepted by {url} "
                    f"(HTTP {response.status})"
                )
        except aiohttp.ClientError as err:
            raise FimerConnectionError(f"Cannot reach {url}: {err}") from err

    async def get_status(self) -> dict[str, Any]:
        """Return the status endpoint: logger identity, firmware, network."""
        return await self._get(ENDPOINT_STATUS)

    async def get_livedata(self) -> dict[str, Any]:
        """Return the livedata endpoint: every device's latest points."""
        return await self._get(ENDPOINT_LIVEDATA)

    async def get_feeds(self) -> dict[str, Any]:
        """Return the feeds endpoint: datastream definitions with history."""
        return await self._get(ENDPOINT_FEEDS)

    async def _get(self, uri: str) -> dict[str, Any]:
        if self.model is None:
            await self.detect()
        url = f"{self.base_url}{uri}"
        try:
            headers = await self._auth_headers(uri)
            async with self._session.get(url, headers=headers, timeout=self._timeout) as response:
                if response.status == 200:
                    return await _read_json(response)
                if response.status == 401:
                    raise FimerAuthenticationError(f"{self.model} rejected the credentials")
                raise FimerConnectionError(f"HTTP {response.status} from {url}")
        except aiohttp.ClientError as err:
            raise FimerConnectionError(f"Request to {url} failed: {err}") from err

    async def _auth_headers(self, uri: str) -> dict[str, str]:
        if not self.requires_auth:
            return {}
        if self.model is VsnModel.VSN700:
            return {"Authorization": f"Basic {basic_credentials(self._username, self._password)}"}
        # VSN300: fetch the challenge for this very URI, then answer it
        url = f"{self.base_url}{uri}"
        async with self._session.get(url, timeout=self._timeout) as response:
            if response.status != 401:
                raise FimerAuthenticationError(
                    f"Expected a digest challenge from {url}, got HTTP {response.status}"
                )
            www_authenticate = response.headers.get("WWW-Authenticate", "")
        if "digest" not in www_authenticate.lower():
            raise FimerAuthenticationError(f"{url} did not issue a digest challenge")
        challenge = parse_digest_challenge(www_authenticate)
        digest = build_digest_header(self._username, self._password, challenge, "GET", uri)
        return {"Authorization": f"X-Digest {digest}"}


async def _read_json(response: aiohttp.ClientResponse) -> Any:
    """Parse a JSON body, tolerating the firmware's wrong charset declarations.

    VSN300 bodies can carry non-UTF-8 bytes in user-entered labels while
    claiming UTF-8, so fall back to latin-1, which never fails.
    """
    raw = await response.read()
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError:
        text = raw.decode("latin-1")
    try:
        return json.loads(text)
    except json.JSONDecodeError as err:
        raise FimerConnectionError(f"Malformed JSON from {response.url}: {err}") from err


def _model_from_status(status: dict[str, Any]) -> VsnModel:
    """Tell the card family from the status keys of an unauthenticated card."""
    keys = status.get("keys", {})
    if keys.get("logger.board_model", {}).get("value") == "WIFI LOGGER CARD":
        return VsnModel.VSN300
    if _VSN300_SERIAL.match(keys.get("logger.sn", {}).get("value", "")):
        return VsnModel.VSN300
    if _MAC_ADDRESS.match(keys.get("logger.loggerId", {}).get("value", "")):
        return VsnModel.VSN700
    if len(keys) > 10:
        return VsnModel.VSN300
    if len(keys) <= 3:
        return VsnModel.VSN700
    raise FimerDetectionError(f"Cannot tell the card family from status keys {sorted(keys)}")
