"""Tests for the pyfimer REST client against a fake datalogger."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
import json
from pathlib import Path
from typing import Any

from aiohttp import ClientSession, web
import pytest

from custom_components.fimer.pyfimer import (
    POINTS_BY_NAME,
    FimerAuthenticationError,
    FimerConnectionError,
    FimerDataError,
    FimerDetectionError,
    FimerNotDiscoveredError,
    FimerUnsupportedDeviceError,
    FimerUnsupportedFirmwareError,
)
from custom_components.fimer.pyfimer.rest import (
    BY_NAME,
    REST_POINTS,
    FimerRestLogger,
    VsnModel,
    VsnRestClient,
    normalize_livedata,
)
from custom_components.fimer.pyfimer.rest.auth import (
    build_digest_header,
    digest_response,
    parse_digest_challenge,
)
from custom_components.fimer.pyfimer.rest.client import _model_from_status

from .fake_vsn import FakeVsn

FIXTURES = Path(__file__).parent.parent / "fixtures" / "rest"
CREDENTIAL = "secret"
WRONG = "wrong"


def load(name: str) -> dict[str, Any]:
    return json.loads(FIXTURES.joinpath(f"{name}.json").read_text())


def vsn300() -> FakeVsn:
    return FakeVsn(
        "VSN300",
        load("alexdelprete_vsn300_fw201_status"),
        load("alexdelprete_vsn300_fw201_livedata"),
    )


def vsn700() -> FakeVsn:
    return FakeVsn(
        "VSN700",
        load("giannicoderani_vsn700_status"),
        load("giannicoderani_vsn700_livedata"),
    )


type Serve = Callable[[FakeVsn], Awaitable[str]]


@pytest.fixture(autouse=True)
def _loopback_sockets(socket_enabled: None) -> None:
    """Allow sockets for this module: the fake card listens on the loopback interface.

    The Home Assistant test plugin blocks sockets by default; its own HTTP
    fixtures opt back in through ``socket_enabled`` the same way.
    """


@pytest.fixture
async def serve(aiohttp_server: Callable[..., Awaitable[Any]]) -> Serve:
    """Start a fake card on the loopback interface and return its base URL."""

    async def start(fake: FakeVsn) -> str:
        server = await aiohttp_server(fake.app())
        return f"http://{server.host}:{server.port}"

    return start


@pytest.fixture
async def session() -> Any:
    """A client session for the fake card."""
    async with ClientSession() as client_session:
        yield client_session


# --- authentication helpers


def test_digest_helpers() -> None:
    challenge = parse_digest_challenge(
        'X-Digest realm="VSN300", nonce="abc", qop="auth", opaque=xyz'
    )
    assert challenge == {"realm": "VSN300", "nonce": "abc", "qop": "auth", "opaque": "xyz"}
    header = build_digest_header("guest", "pw", challenge, "GET", "/v1/livedata")
    assert 'username="guest"' in header
    assert 'uri="/v1/livedata"' in header
    assert "qop=auth" in header
    assert 'opaque="xyz"' in header
    simple = build_digest_header("guest", "pw", {"realm": "r", "nonce": "n"}, "GET", "/v1/status")
    assert "qop" not in simple
    assert digest_response("guest", "pw", "r", "n", "GET", "/v1/status") in simple


# --- transport


async def test_vsn300_detect_and_fetch(serve: Serve, session: ClientSession) -> None:
    fake = vsn300()
    client = VsnRestClient(session, await serve(fake), password=CREDENTIAL)
    assert await client.detect() is VsnModel.VSN300
    assert client.requires_auth
    status = await client.get_status()
    assert status["keys"]["fw.release_number"]["value"] == "2.0.1"
    livedata = await client.get_livedata()
    assert "YYYYYY-3G82-XXXX" in livedata
    # each authenticated fetch costs a challenge round trip
    assert fake.requests.count("GET /v1/livedata") == 2


async def test_vsn700_detect_and_fetch(serve: Serve, session: ClientSession) -> None:
    fake = vsn700()
    client = VsnRestClient(session, await serve(fake), password=CREDENTIAL)
    assert await client.detect() is VsnModel.VSN700
    livedata = await client.get_livedata()
    assert "140842-3P81-2619" in livedata
    # preemptive basic auth: one request per fetch after detection
    assert fake.requests.count("GET /v1/livedata") == 1


async def test_open_cards_are_detected_from_status(serve: Serve, session: ClientSession) -> None:
    fake = vsn300()
    fake.requires_auth = False
    client = VsnRestClient(session, await serve(fake))
    assert await client.detect() is VsnModel.VSN300
    assert not client.requires_auth
    fake = vsn700()
    fake.requires_auth = False
    client = VsnRestClient(session, await serve(fake))
    assert await client.detect() is VsnModel.VSN700


async def test_wrong_password(serve: Serve, session: ClientSession) -> None:
    client = VsnRestClient(session, await serve(vsn300()), password=WRONG)
    assert await client.detect() is VsnModel.VSN300
    with pytest.raises(FimerAuthenticationError):
        await client.get_livedata()
    client = VsnRestClient(session, await serve(vsn700()), password=WRONG)
    with pytest.raises(FimerDetectionError):
        await client.detect()


async def test_not_a_datalogger(aiohttp_server: Any, session: ClientSession) -> None:
    server = await aiohttp_server(web.Application())
    client = VsnRestClient(session, f"http://{server.host}:{server.port}")
    with pytest.raises(FimerUnsupportedDeviceError):
        await client.detect()


async def test_unreachable_host(session: ClientSession) -> None:
    client = VsnRestClient(session, "http://127.0.0.1:1", timeout=1)
    with pytest.raises(FimerConnectionError):
        await client.detect()


async def test_base_url_forms(session: ClientSession) -> None:
    assert VsnRestClient(session, "192.0.2.10").base_url == "http://192.0.2.10"
    assert VsnRestClient(session, "https://card.local/").base_url == "https://card.local"


# --- normaliser


def test_vsn300_normalisation() -> None:
    readings = normalize_livedata(
        VsnModel.VSN300,
        load("alexdelprete_vsn300_fw201_livedata"),
        load("alexdelprete_vsn300_fw201_status"),
    )
    assert set(readings) == {"YYYYYY-3G82-XXXX", "LLLLLL-3N16-BBBB"}
    inverter = readings["YYYYYY-3G82-XXXX"]
    assert inverter.device_type == "inverter_3phases"
    assert inverter.model == "PVI-10.0-OUTD"
    assert inverter.unmapped == []
    assert inverter.values["W"] == pytest.approx(3194.016, abs=1e-3)
    assert inverter.values["WH"] == 114285600  # watt-hours, as the card sends them
    assert inverter.values["DCA_1"] == pytest.approx(5.8255, abs=1e-4)
    assert inverter.values["GlobalSt"] == 6
    assert inverter.values["TmpCab"] == pytest.approx(24.744, abs=1e-3)  # tenfold quirk corrected
    assert inverter.values["ILeakDcAc"] == 0.0  # microamperes to milliamperes
    assert inverter.values["Md"] == "3G82"  # dashes stripped
    assert inverter.values["SysTime"] == 839768821 + 946684800  # Unix time
    logger = readings["LLLLLL-3N16-BBBB"]
    assert logger.device_type == "datalogger"
    assert logger.model == "VSN300"
    assert logger.values["type"] == "Wifi Logger Card"
    assert logger.values["wlan0_link_quality"] == 100
    assert logger.values["flash_free"] == pytest.approx(3135.94, abs=0.01)  # bytes to MB
    assert logger.values["wlan_0_status"] == "connected"  # injected from status
    assert set(inverter.values) | set(logger.values) <= set(POINTS_BY_NAME)


def test_vsn700_normalisation() -> None:
    readings = normalize_livedata(
        VsnModel.VSN700,
        load("giannicoderani_vsn700_livedata"),
        load("giannicoderani_vsn700_status"),
    )
    assert set(readings) == {
        "113049-3P72-0221",
        "120730-3N52-3019",
        "140821-3P72-1319",
        "140842-3P81-2619",
        "0c1c57fdc62c",
    }
    inverter = readings["140842-3P81-2619"]
    assert inverter.device_type == "inverter_1phase"
    assert inverter.model == "REACT2-5.0-TL"
    assert "W" in inverter.values
    assert isinstance(inverter.values["GlobalSt"], int)  # VSN700 GlobState, cast to a code
    assert "GlobState" not in inverter.values
    assert inverter.values["DCV_1"] == pytest.approx(
        next(
            p["value"]
            for p in load("giannicoderani_vsn700_livedata")["140842-3P81-2619"]["points"]
            if p["name"] == "Vin1"
        )
    )
    assert "Inverter_CosPhi" in inverter.values
    assert inverter.values["WRtg"] == 5050.0
    assert inverter.values["ILeakDcAc"] == pytest.approx(
        next(
            p["value"]
            for p in load("giannicoderani_vsn700_livedata")["140842-3P81-2619"]["points"]
            if p["name"] == "IleakInv"
        )
        / 1000
    )
    battery = readings["113049-3P72-0221"]
    assert battery.device_type == "battery"
    assert "Soc" in battery.values
    meter = readings["120730-3N52-3019"]
    assert meter.device_type == "meter"
    assert "MeterPgrid_Tot" in meter.values
    logger = readings["0c1c57fdc62c"]
    assert logger.device_type == "datalogger"
    assert logger.values == {}
    for device in readings.values():
        assert set(device.values) <= set(POINTS_BY_NAME), device.device_id


def test_vsn700_aliases_and_single_phase_prefix() -> None:
    readings = normalize_livedata(
        VsnModel.VSN700,
        {"B1": {"device_type": "battery", "points": [{"name": "TSoc", "value": 55.0}]}},
    )
    assert readings["B1"].values["Soc"] == 55.0
    readings = normalize_livedata(
        VsnModel.VSN300,
        {
            "I1": {
                "device_type": "inverter_1phase",
                "points": [
                    {"name": "m101_1_W", "value": 10},
                    {"name": "C_Opt", "value": "X"},
                    {"name": "bogus", "value": 1},
                ],
            }
        },
    )
    assert readings["I1"].values["W"] == 10
    assert readings["I1"].model == "PVI-10.0-OUTD"  # from the options code without status
    assert readings["I1"].unmapped == ["bogus"]


def test_mapping_table_is_consistent() -> None:
    assert len(BY_NAME) == len(REST_POINTS)
    assert BY_NAME["W"].vsn300_name == "m103_1_W"
    assert BY_NAME["W"].vsn700_name == "Pgrid"
    assert BY_NAME["WH"].unit == "Wh"
    assert BY_NAME["Isolation_Ohm1"].unit == "MΩ"
    assert POINTS_BY_NAME["Soc"].kind == "measurement"
    assert POINTS_BY_NAME["GlobalSt"].model == 64061
    assert "GlobState" not in POINTS_BY_NAME  # aliased to GlobalSt


# --- logger facade


async def test_logger_vsn300(serve: Serve, session: ClientSession) -> None:
    fake = vsn300()
    logger = FimerRestLogger(session, await serve(fake), password=CREDENTIAL)
    assert not logger.discovered
    with pytest.raises(FimerNotDiscoveredError):
        _ = logger.identity
    await logger.discover()
    assert logger.discovered
    assert logger.model is VsnModel.VSN300
    assert logger.requires_auth
    identity = logger.identity
    assert identity.serial_number == "LLLLLL-3N16-BBBB"
    assert identity.unique_id == "LLLLLL-3N16-BBBB"
    assert identity.firmware_version == "2.0.1"
    assert identity.board_model == "WIFI LOGGER CARD"
    assert identity.hostname == "ABB-YYYYYY-3G82-XXXX.local"
    assert logger.status["keys"]["fw.release_number"]["value"] == "2.0.1"

    await logger.async_update()
    values = logger.values()
    assert values["YYYYYY-3G82-XXXX"]["W"] == pytest.approx(3194.016, abs=1e-3)
    assert values["LLLLLL-3N16-BBBB"]["wlan_0_status"] == "connected"
    assert logger.devices["YYYYYY-3G82-XXXX"].model == "PVI-10.0-OUTD"


async def test_logger_vsn700(serve: Serve, session: ClientSession) -> None:
    logger = FimerRestLogger(session, await serve(vsn700()), password=CREDENTIAL)
    await logger.discover()
    identity = logger.identity
    assert identity.model is VsnModel.VSN700
    assert identity.serial_number == "0c:1c:57:fd:c6:2c"
    assert identity.unique_id == "0c1c57fdc62c"
    assert identity.firmware_version is None
    await logger.async_update()
    assert set(logger.values()) == set(logger.devices)
    assert logger.devices["140842-3P81-2619"].model == "REACT2-5.0-TL"


async def test_logger_known_model_skips_detection(serve: Serve, session: ClientSession) -> None:
    fake = vsn700()
    logger = FimerRestLogger(
        session, await serve(fake), password=CREDENTIAL, model=VsnModel.VSN700, requires_auth=True
    )
    await logger.discover()
    assert fake.requests[0] == "GET /v1/status"
    assert logger.model is VsnModel.VSN700


async def test_logger_refuses_broken_firmware(serve: Serve, session: ClientSession) -> None:
    fake = vsn300()
    fake.status["keys"]["fw.release_number"]["value"] = "2.0.0"
    fake.livedata_status = 500
    logger = FimerRestLogger(session, await serve(fake), password=CREDENTIAL)
    with pytest.raises(FimerUnsupportedFirmwareError) as excinfo:
        await logger.discover()
    assert excinfo.value.firmware_version == "2.0.0"

    fake.status["keys"]["fw.release_number"]["value"] = "2.0.1"
    logger = FimerRestLogger(session, await serve(fake), password=CREDENTIAL)
    with pytest.raises(FimerConnectionError):
        await logger.discover()


async def test_transport_edge_cases(serve: Serve, session: ClientSession) -> None:
    # feeds endpoint, and fetching before an explicit detect()
    fake = vsn700()
    client = VsnRestClient(session, await serve(fake), password=CREDENTIAL)
    assert await client.get_feeds() == {"feeds": {}}
    assert client.model is VsnModel.VSN700

    # an open card answers every fetch without credentials
    fake = vsn300()
    fake.requires_auth = False
    client = VsnRestClient(session, await serve(fake))
    await client.detect()
    assert "YYYYYY-3G82-XXXX" in await client.get_livedata()

    # unexpected status during detection
    fake = vsn300()
    fake.status_status = 500
    with pytest.raises(FimerDetectionError):
        await VsnRestClient(session, await serve(fake)).detect()

    # a non-200, non-401 answer to a fetch
    fake = vsn700()
    fake.livedata_status = 503
    client = VsnRestClient(session, await serve(fake), password=CREDENTIAL)
    with pytest.raises(FimerConnectionError, match="503"):
        await client.get_livedata()

    # the card stops challenging after detection
    fake = vsn300()
    client = VsnRestClient(session, await serve(fake), password=CREDENTIAL)
    await client.detect()
    fake.requires_auth = False
    with pytest.raises(FimerAuthenticationError, match="Expected a digest challenge"):
        await client.get_livedata()

    # a VSN300 that challenges with a non-digest scheme
    fake = vsn300()
    fake.challenge_scheme = "Basic"
    client = VsnRestClient(
        session, await serve(fake), password=CREDENTIAL, model=VsnModel.VSN300, requires_auth=True
    )
    with pytest.raises(FimerAuthenticationError, match="did not issue a digest challenge"):
        await client.get_status()

    # a known VSN700 that is unreachable
    client = VsnRestClient(
        session, "http://127.0.0.1:1", timeout=1, model=VsnModel.VSN700, requires_auth=True
    )
    with pytest.raises(FimerConnectionError):
        await client.get_status()


async def test_lenient_json(serve: Serve, session: ClientSession) -> None:
    fake = vsn300()
    fake.requires_auth = False
    fake.raw_status = (
        b'{"keys": {"logger.board_model": {"value": "WIFI LOGGER CARD"}, "label": "\xe8"}}'
    )
    client = VsnRestClient(session, await serve(fake))
    assert await client.detect() is VsnModel.VSN300  # latin-1 fallback
    fake.raw_status = b"{not json"
    with pytest.raises(FimerConnectionError, match="Malformed JSON"):
        await client.get_status()


def test_model_from_status_heuristics() -> None:
    assert (
        _model_from_status({"keys": {"logger.sn": {"value": "111033-3N16-1421"}}})
        is VsnModel.VSN300
    )
    assert (
        _model_from_status({"keys": {"logger.loggerId": {"value": "0c:1c:57:fd:c6:2c"}}})
        is VsnModel.VSN700
    )
    assert (
        _model_from_status({"keys": {f"k{i}": {"value": i} for i in range(11)}}) is VsnModel.VSN300
    )
    assert _model_from_status({"keys": {"a": {"value": 1}}}) is VsnModel.VSN700
    with pytest.raises(FimerDetectionError):
        _model_from_status({"keys": {f"k{i}": {"value": i} for i in range(5)}})


def test_normaliser_skips_nameless_and_keeps_null_values() -> None:
    readings = normalize_livedata(
        VsnModel.VSN300,
        {
            "I1": {
                "device_type": "inverter_3phases",
                "points": [
                    {"name": "", "value": 1},
                    {"name": "m103_1_W", "value": None},
                    {"name": "m103_1_TmpCab", "value": 5.5},
                    {"name": "C_Mn", "value": "Power-One"},
                ],
            }
        },
    )
    assert readings["I1"].values == {"W": None, "TmpCab": 5.5, "Mn": "Power-One"}


async def test_hanging_card_is_a_connection_error(serve: Serve, session: ClientSession) -> None:
    """A card that never answers raises the library's error, not a raw timeout."""
    fake = vsn300()
    fake.delay = 2
    client = VsnRestClient(session, await serve(fake), password=CREDENTIAL, timeout=0.2)
    with pytest.raises(FimerConnectionError, match="Cannot reach"):
        await client.detect()
    client.model, client.requires_auth = VsnModel.VSN300, True
    with pytest.raises(FimerConnectionError, match="failed"):
        await client.get_livedata()


async def test_malformed_livedata_is_a_data_error(serve: Serve, session: ClientSession) -> None:
    """Valid JSON of the wrong shape is reported as unreadable data."""
    fake = vsn300()
    fake.livedata = ["not", "a", "device", "map"]
    logger = FimerRestLogger(session, await serve(fake), password=CREDENTIAL)
    with pytest.raises(FimerDataError, match="Unreadable livedata"):
        await logger.discover()


async def test_malformed_status_is_a_data_error(serve: Serve, session: ClientSession) -> None:
    """An open card whose status is not an object is reported as unreadable."""
    fake = vsn300()
    fake.requires_auth = False
    fake.status = ["nope"]
    client = VsnRestClient(session, await serve(fake))
    with pytest.raises(FimerDataError, match="Unreadable status"):
        await client.detect()
