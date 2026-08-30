from unittest.mock import MagicMock, patch

import pandas as pd

from health_aggregator.live import calendar_live


def test_classify_event_matches_activity_keywords():
    assert calendar_live._classify_event("Morning gym session") == "activity"
    assert calendar_live._classify_event("5k run") == "activity"


def test_classify_event_matches_travel_keywords():
    assert calendar_live._classify_event("Flight to Sydney") == "travel"


def test_classify_event_defaults_to_other():
    assert calendar_live._classify_event("Team meeting") == "other"
    assert calendar_live._classify_event(None) == "other"


def test_events_payload_to_frame_handles_timed_events():
    items = [
        {
            "summary": "Gym",
            "start": {"dateTime": "2026-08-10T07:00:00Z"},
            "end": {"dateTime": "2026-08-10T08:00:00Z"},
        }
    ]
    df = calendar_live._events_payload_to_frame(items)
    assert len(df) == 1
    assert df.iloc[0]["event_type"] == "activity"
    assert df.iloc[0]["source"] == "google_calendar"
    assert df.iloc[0]["start"].tzinfo is None


def test_events_payload_to_frame_handles_all_day_events():
    items = [{"summary": "Conference", "start": {"date": "2026-08-10"}, "end": {"date": "2026-08-11"}}]
    df = calendar_live._events_payload_to_frame(items)
    assert len(df) == 1
    assert df.iloc[0]["start"] == pd.Timestamp("2026-08-10")


def test_events_payload_to_frame_skips_events_without_start_or_end():
    df = calendar_live._events_payload_to_frame([{"summary": "Broken"}])
    assert df.empty


def test_events_payload_to_frame_handles_empty_payload():
    assert calendar_live._events_payload_to_frame([]).empty
    assert calendar_live._events_payload_to_frame(None).empty


def test_poll_once_raises_when_not_connected(tmp_path):
    from health_aggregator import db as dbmod

    conn = dbmod.connect(str(tmp_path / "health.db"))
    with patch("health_aggregator.live.calendar_live._load_cached_credentials", return_value=None):
        try:
            calendar_live.poll_once(conn, token_path=str(tmp_path / "missing_token.json"))
            assert False, "expected RuntimeError"
        except RuntimeError as exc:
            assert "connect_interactive" in str(exc) or "connect-calendar" in str(exc)


def test_poll_once_upserts_events_when_connected(tmp_path):
    from health_aggregator import db as dbmod

    conn = dbmod.connect(str(tmp_path / "health.db"))
    fake_creds = MagicMock(valid=True)
    fake_items = [
        {
            "summary": "Yoga",
            "start": {"dateTime": "2026-08-10T07:00:00Z"},
            "end": {"dateTime": "2026-08-10T08:00:00Z"},
        }
    ]

    with patch("health_aggregator.live.calendar_live._load_cached_credentials", return_value=fake_creds), patch(
        "googleapiclient.discovery.build", return_value=MagicMock()
    ), patch("health_aggregator.live.calendar_live.fetch_events", return_value=fake_items):
        counts = calendar_live.poll_once(conn, token_path=str(tmp_path / "token.json"))

    assert counts == {"calendar_events": 1}
    assert len(dbmod.load_calendar_events(conn)) == 1
