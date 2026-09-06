"""Logging helpers for the FIMER (ABB / Power-One) integration."""

from __future__ import annotations

import logging

_HA_STACK_MESSAGES = frozenset({"Full exception", "Full error:"})


class _NoStackFromHomeAssistant(logging.Filter):
    """Drop the stack traces Home Assistant attaches at DEBUG to failures already reported.

    When an entry is not ready or a poll fails, Home Assistant logs a one-line
    message and, on the integration's own logger at DEBUG, the complete
    exception chain. The integration reports every failure itself with its
    cause in the message, so those chains only bury the useful lines.
    """

    def filter(self, record: logging.LogRecord) -> bool:
        """Keep every record except Home Assistant's stack dumps."""
        return not (record.exc_info and record.msg in _HA_STACK_MESSAGES)


def install_log_filters() -> None:
    """Attach the stack filter to the loggers Home Assistant writes those dumps to."""
    for name in (__package__, f"{__package__}.coordinator"):
        logger = logging.getLogger(name)
        if not any(isinstance(existing, _NoStackFromHomeAssistant) for existing in logger.filters):
            logger.addFilter(_NoStackFromHomeAssistant())
