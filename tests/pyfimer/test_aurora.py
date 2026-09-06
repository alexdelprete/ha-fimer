"""Tests for the shared Aurora protocol tables."""

from __future__ import annotations

import pytest

from custom_components.fimer.pyfimer import (
    ALARM_CODES,
    POINTS,
    POINTS_BY_NAME,
    decode_alarms,
    inverter_model_from_options,
    power_control_support,
)


def test_decode_alarms() -> None:
    assert decode_alarms(0, 0, 0) == []
    assert decode_alarms(None, None, None) == []
    assert decode_alarms(1) == []  # "No Alarm" is not an alarm
    assert decode_alarms(1 << 1 | 1 << 13, 1 << 1, 1 << 15) == [
        "Sun Low",
        "Grid Fail",
        "Grid OV",
        "Energy data reset",
    ]
    assert decode_alarms(0, 0, 1 << 30) == ["Alarm 92"]


def test_alarm_codes_are_contiguous() -> None:
    assert sorted(ALARM_CODES) == list(range(78))


@pytest.mark.parametrize(
    ("options", "model"),
    [
        ("X", "PVI-10.0-OUTD"),
        ("Xabc", "PVI-10.0-OUTD"),
        ("1", "PVI-3.0-OUTD"),  # chr(49)
        ("0x01", "UNO-DM-4.0-TL-PLUS"),
        ("0x0D/0xFFFF", "REACT2-UNO-5.0-TL"),
        ("0X0D", "REACT2-UNO-5.0-TL"),
        ("0xZZ", None),
        ("?", None),
        ("", None),
        (None, None),
    ],
)
def test_inverter_model_from_options(options: str | None, model: str | None) -> None:
    assert inverter_model_from_options(options) == model


def test_point_vocabulary_is_unique() -> None:
    assert len(POINTS_BY_NAME) == len(POINTS)
    assert POINTS_BY_NAME["W"].unit == "W"
    assert POINTS_BY_NAME["DCA_3"].model == 160


@pytest.mark.parametrize(
    ("model", "supported", "reason"),
    [
        ("PVI-10.0-OUTD", False, "unsupported_model"),
        ("TRIO-27.6-TL-OUTD", False, "unsupported_model"),
        ("TRIO-8.5-TL-OUTD-S", True, None),
        ("trio-50.0-tl-outd", True, None),
        ("REACT2-5.0-TL", True, None),
        ("UNO-DM-5.0-TL-PLUS", True, None),
        ("", False, "unknown_model"),
        (None, False, "unknown_model"),
    ],
)
def test_power_control_support(model: str | None, supported: bool, reason: str | None) -> None:
    """Only the families ABB lets a card set parameters on, or with native SunSpec, qualify."""
    support = power_control_support(model)
    assert support.supported is supported
    assert support.reason == reason
    assert support.model == (model or "").strip()
