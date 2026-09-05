"""Bridge from the generated REST point table to the vocabulary."""

from __future__ import annotations

from collections.abc import Iterator


def rest_point_rows() -> Iterator[tuple[str, str | None, str, str, str]]:
    """Yield (name, unit, kind, models, description) for every REST point row."""
    from .rest._mapping_data import REST_POINT_ROWS  # noqa: PLC0415
    from .rest.mapping import SHARED_NAME_ALIASES  # noqa: PLC0415 - avoids an import cycle

    for row in REST_POINT_ROWS:
        if row[0] in SHARED_NAME_ALIASES:
            continue
        yield row[0], row[3], row[4], row[6], row[7]
