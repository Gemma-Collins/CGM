import pytest

from health_aggregator import scheduler


def test_run_forever_calls_poll_fn_repeatedly_and_respects_jitter_bounds(monkeypatch):
    calls = []
    sleeps = []

    def poll_fn():
        calls.append(1)
        if len(calls) >= 3:
            raise KeyboardInterrupt  # our way of stopping the infinite loop in a test

    monkeypatch.setattr(scheduler.time, "sleep", lambda s: sleeps.append(s))

    with pytest.raises(KeyboardInterrupt):
        scheduler.run_forever(poll_fn, min_interval_seconds=10, max_interval_seconds=20)

    assert len(calls) == 3
    assert len(sleeps) == 2  # slept between each poll, not after the one that raised
    assert all(10 <= s <= 20 for s in sleeps)


def test_run_forever_continues_after_a_poll_error(monkeypatch):
    calls = []

    def poll_fn():
        calls.append(1)
        if len(calls) == 1:
            raise ValueError("boom")
        if len(calls) >= 2:
            raise KeyboardInterrupt

    monkeypatch.setattr(scheduler.time, "sleep", lambda s: None)

    with pytest.raises(KeyboardInterrupt):
        scheduler.run_forever(poll_fn, min_interval_seconds=1, max_interval_seconds=2)

    assert len(calls) == 2  # the ValueError on call 1 didn't stop the loop


def test_run_forever_rejects_invalid_interval_bounds():
    with pytest.raises(ValueError):
        scheduler.run_forever(lambda: None, min_interval_seconds=20, max_interval_seconds=10)
