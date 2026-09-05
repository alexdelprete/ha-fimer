"""REST client for the VSN300 and VSN700 datalogger cards.

Consumes an ``aiohttp.ClientSession``; the session lifecycle stays with the
caller (in Home Assistant, the shared client session).

:class:`FimerRestLogger` discovers the card and the devices behind it and
reports their readings under the same point names as the Modbus client;
:class:`VsnRestClient` is the raw transport underneath.
"""

from .client import (
    DEFAULT_TIMEOUT,
    DEFAULT_USERNAME,
    ENDPOINT_FEEDS,
    ENDPOINT_LIVEDATA,
    ENDPOINT_STATUS,
    VsnModel,
    VsnRestClient,
)
from .logger import UNSUPPORTED_VSN300_FIRMWARE, FimerRestLogger, LoggerIdentity
from .mapping import BY_NAME, BY_VSN300_NAME, BY_VSN700_NAME, REST_POINTS, RestPoint
from .normalizer import DEVICE_TYPE_DATALOGGER, DeviceReadings, normalize_livedata

__all__ = [
    "BY_NAME",
    "BY_VSN300_NAME",
    "BY_VSN700_NAME",
    "DEFAULT_TIMEOUT",
    "DEFAULT_USERNAME",
    "DEVICE_TYPE_DATALOGGER",
    "ENDPOINT_FEEDS",
    "ENDPOINT_LIVEDATA",
    "ENDPOINT_STATUS",
    "REST_POINTS",
    "UNSUPPORTED_VSN300_FIRMWARE",
    "DeviceReadings",
    "FimerRestLogger",
    "LoggerIdentity",
    "RestPoint",
    "VsnModel",
    "VsnRestClient",
    "normalize_livedata",
]
