"""Tests for how the sensor descriptions are named."""

from __future__ import annotations

from custom_components.fimer.pyfimer.rest import REST_POINTS
from custom_components.fimer.pyfimer.rest.mapping import SHARED_NAME_ALIASES
from custom_components.fimer.sensor import ALL_DESCRIPTIONS, SENSOR_DESCRIPTIONS


def test_shared_points_keep_the_rest_translation_keys() -> None:
    """A point the REST API also reports is named the way the REST integration named it."""
    rest_keys: dict[str, str] = {}
    for point in REST_POINTS:
        rest_keys.setdefault(SHARED_NAME_ALIASES.get(point.name, point.name), point.ha_name)
    for description in SENSOR_DESCRIPTIONS:
        if description.key in rest_keys:
            assert description.translation_key == rest_keys[description.key], description.key


def test_one_description_per_point() -> None:
    """No point is described twice, whichever source serves it."""
    keys = [description.key for description in ALL_DESCRIPTIONS]
    assert len(keys) == len(set(keys))
