"""Turn a datalogger's livedata into vocabulary points per device.

The VSN300 names its points after the SunSpec registers with a model prefix
(``m103_1_W``); the VSN700 uses ABB's own names (``Pgrid``). Both are looked
up in the generated mapping and emitted under the vocabulary name (``W``),
in the vocabulary's native units, so the caller cannot tell which card the
readings came from.
"""

# ruff: noqa: TID252 - parent-relative imports keep the package movable to PyPI

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Final

from ..aurora import inverter_model_from_options
from .client import VsnModel
from .mapping import BY_VSN300_NAME, BY_VSN700_NAME, SHARED_NAME_ALIASES, RestPoint

# Leakage currents arrive in microamperes on both cards; the vocabulary says mA.
_MICROAMPERE_POINTS: Final = frozenset(
    {"m64061_1_ILeakDcAc", "m64061_1_ILeakDcDc", "IleakInv", "IleakDC"}
)
# The VSN300 reports WiFi link quality on the Linux wireless-extensions 0..70 scale.
_WEXT_QUALITY_POINTS: Final = frozenset({"wlan0_link_quality"})
_WEXT_QUALITY_MAX: Final = 70
# Cabinet temperature served with the wrong scale factor on some inverters.
_TEMPERATURE_QUIRK_POINTS: Final = frozenset({"m103_1_TmpCab", "m101_1_TmpCab", "Temp1"})
_TEMPERATURE_PLAUSIBLE_MAX: Final = 70.0
# Storage sizes arrive in bytes; the vocabulary says MB.
_BYTES_POINTS: Final = frozenset({"flash_free", "free_ram", "store_size"})
_MEGABYTE: Final = 1024 * 1024
# Identification strings the card pads with dashes.
_DASH_PADDED_POINTS: Final = frozenset({"pn", "C_Md"})
# State and flag codes the VSN700 sends as floats.
_STATE_POINTS: Final = frozenset(
    {
        "GlobState",
        "InvState",
        "DC1State",
        "DC2State",
        "DC3State",
        "AlarmState",
        "WarningFlags",
        "PACDeratingFlags",
        "QACDeratingFlags",
        "SACDeratingFlags",
        "m64061_1_GlobalSt",
        "m64061_1_InverterSt",
        "m64061_1_DcSt1",
        "m64061_1_DcSt2",
        "m64061_1_DcSt3",
        "m64061_1_AlarmState",
        "m64061_1_AlarmSt",
    }
)
# Names some VSN700 firmwares use for points the mapping knows under another name.
_VSN700_ALIASES: Final = {"TSoc": "Soc", "VgridR": "Vgrid"}
# Status keys of a VSN300 that describe the datalogger but never appear in livedata.
VSN300_STATUS_POINTS: Final = {
    "wlan.0.status": "wlan_0_status",
    "wlan.0.dhcpState": "wlan_0_dhcpState",
    "wlan.ap.status": "wlan_ap_status",
}

DEVICE_TYPE_DATALOGGER: Final = "datalogger"


@dataclass(slots=True)
class DeviceReadings:
    """One device's readings from a livedata response."""

    device_id: str
    """Serial number, or the datalogger's MAC without colons."""
    device_type: str
    """``inverter_1phase``, ``inverter_3phases``, ``meter``, ``battery`` or ``datalogger``."""
    model: str | None
    timestamp: str | None
    values: dict[str, Any] = field(default_factory=dict)
    """Readings keyed by vocabulary point name."""
    unmapped: list[str] = field(default_factory=list)
    """REST point names the mapping does not know, for diagnostics."""


def normalize_livedata(
    model: VsnModel,
    livedata: dict[str, Any],
    status: dict[str, Any] | None = None,
) -> dict[str, DeviceReadings]:
    """Return the readings of every device in a livedata response.

    ``status`` lets a VSN300's datalogger take its identity and its WiFi
    state from the status endpoint, and its inverter its model name.
    """
    keys = (status or {}).get("keys", {})
    readings: dict[str, DeviceReadings] = {}
    for raw_id, device in livedata.items():
        points = list(device.get("points", []))
        is_datalogger = ":" in raw_id
        device_id = raw_id
        if is_datalogger:
            serial = next((p.get("value") for p in points if p.get("name") == "sn"), None)
            device_id = serial or raw_id.replace(":", "")
            if model is VsnModel.VSN300:
                points += [
                    {"name": name, "value": keys[key]["value"]}
                    for key, name in VSN300_STATUS_POINTS.items()
                    if key in keys
                ]
        device_type = (
            DEVICE_TYPE_DATALOGGER if is_datalogger else device.get("device_type", "unknown")
        )
        device_model = device.get("device_model") if model is VsnModel.VSN700 else None
        if model is VsnModel.VSN300 and device_type.startswith("inverter"):
            device_model = keys.get("device.modelDesc", {}).get("value") or _model_from_points(
                points
            )
        if is_datalogger:
            device_model = str(model)

        result = DeviceReadings(device_id, device_type, device_model, device.get("timestamp"))
        for point in points:
            name, value = point.get("name"), point.get("value")
            if not name:
                continue
            if (mapping := _lookup(model, name)) is None:
                result.unmapped.append(name)
                continue
            shared = SHARED_NAME_ALIASES.get(mapping.name, mapping.name)
            result.values[shared] = _transform(name, value, mapping)
        readings[device_id] = result
    return readings


def _lookup(model: VsnModel, name: str) -> RestPoint | None:
    if model is VsnModel.VSN300:
        if name.startswith(("m101_", "m102_")):
            name = "m103_" + name[5:]  # the single and split phase models share the layout
        return BY_VSN300_NAME.get(name)
    return BY_VSN700_NAME.get(_VSN700_ALIASES.get(name, name))


def _transform(name: str, value: Any, mapping: RestPoint) -> Any:
    """Apply the unit and value fixes a raw point needs to match the vocabulary."""
    if value is None:
        return None
    if name in _STATE_POINTS and isinstance(value, float):
        value = int(value)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        if isinstance(value, str):
            if name in _DASH_PADDED_POINTS:
                value = value.strip("-")
            if name == "type":
                value = value.title()
        return value
    if name in _MICROAMPERE_POINTS:
        return value / 1000
    if name in _WEXT_QUALITY_POINTS:
        return min(100, round(value * 100 / _WEXT_QUALITY_MAX))
    if name in _TEMPERATURE_QUIRK_POINTS and value > _TEMPERATURE_PLAUSIBLE_MAX:
        return value / 10
    if name in _BYTES_POINTS:
        return value / _MEGABYTE
    if mapping.kind == "state" and isinstance(value, float):
        return int(value)
    return value


def _model_from_points(points: list[dict[str, Any]]) -> str | None:
    options = next((p.get("value") for p in points if p.get("name") == "C_Opt"), None)
    return inverter_model_from_options(options) if isinstance(options, str) else None
