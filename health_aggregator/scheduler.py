"""Runs a poll function forever on a jittered interval - the piece that
turns a one-off poll into an always-on live tracker.

Jitter (a random interval instead of a fixed one) keeps request timing from
looking like a metronomic bot and avoids synchronized load; it isn't a
guarantee against detection, just reasonable, polite client behavior.
"""

import logging
import random
import time

logger = logging.getLogger(__name__)


def run_forever(poll_fn, min_interval_seconds: float, max_interval_seconds: float) -> None:
    """Call ``poll_fn()`` repeatedly, sleeping a random interval in
    [min_interval_seconds, max_interval_seconds] between calls. A single
    failed poll is logged and skipped rather than stopping the loop -
    losing one poll shouldn't take the whole tracker down."""
    if min_interval_seconds <= 0 or max_interval_seconds < min_interval_seconds:
        raise ValueError("require 0 < min_interval_seconds <= max_interval_seconds")

    while True:
        try:
            poll_fn()
        except Exception:
            logger.exception("poll failed; will retry next interval")

        sleep_for = random.uniform(min_interval_seconds, max_interval_seconds)
        time.sleep(sleep_for)
