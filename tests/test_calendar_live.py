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
    df = calendar_live._events_payload_to_frame(items, calendar_name="Personal")
    assert len(df) == 1
    assert df.iloc[0]["event_type"] == "activity"
    assert df.iloc[0]["source"] == "google_calendar"
    assert df.iloc[0]["calendar_name"] == "Personal"
    assert df.iloc[0]["start"].tzinfo is None


def test_events_payload_to_frame_defaults_calendar_name_to_primary():
    items = [{"summary": "Gym", "start": {"dateTime": "2026-08-10T07:00:00Z"}, "end": {"dateTime": "2026-08-10T08:00:00Z"}}]
    df = calendar_live._events_payload_to_frame(items)
    assert df.iloc[0]["calendar_name"] == "primary"


def test_list_calendars_returns_id_and_summary():
    service = MagicMock()
    service.calendarList().list().execute.return_value = {
        "items": [{"id": "primary", "summary": "gemma@example.com"}, {"id": "abc123@group.calendar.google.com", "summary": "Work"}]
    }
    calendars = calendar_live.list_calendars(service)
    assert calendars == [
        {"id": "primary", "summary": "gemma@example.com"},
        {"id": "abc123@group.calendar.google.com", "summary": "Work"},
    ]


def test_list_calendars_falls_back_to_id_when_no_summary():
    service = MagicMock()
    service.calendarList().list().execute.return_value = {"items": [{"id": "some-id"}]}
    assert calendar_live.list_calendars(service) == [{"id": "some-id", "summary": "some-id"}]


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
    fake_calendars = [{"id": "primary", "summary": "gemma@example.com"}]

    with patch("health_aggregator.live.calendar_live._load_cached_credentials", return_value=fake_creds), patch(
        "googleapiclient.discovery.build", return_value=MagicMock()
    ), patch("health_aggregator.live.calendar_live.list_calendars", return_value=fake_calendars), patch(
        "health_aggregator.live.calendar_live.fetch_events", return_value=fake_items
    ):
        counts = calendar_live.poll_once(conn, token_path=str(tmp_path / "token.json"))

    assert counts == {"calendar_events": 1}
    events = dbmod.load_calendar_events(conn)
    assert len(events) == 1
    assert events.iloc[0]["calendar_name"] == "gemma@example.com"


def test_poll_once_merges_events_from_multiple_calendars(tmp_path):
    from health_aggregator import db as dbmod

    conn = dbmod.connect(str(tmp_path / "health.db"))
    fake_creds = MagicMock(valid=True)
    fake_calendars = [{"id": "primary", "summary": "Personal"}, {"id": "work-id", "summary": "Work"}]

    def fake_fetch(service, time_min, time_max, calendar_id="primary"):
        if calendar_id == "primary":
            return [{"summary": "Gym", "start": {"dateTime": "2026-08-10T07:00:00Z"}, "end": {"dateTime": "2026-08-10T08:00:00Z"}}]
        return [{"summary": "Standup", "start": {"dateTime": "2026-08-10T09:00:00Z"}, "end": {"dateTime": "2026-08-10T09:30:00Z"}}]

    with patch("health_aggregator.live.calendar_live._load_cached_credentials", return_value=fake_creds), patch(
        "googleapiclient.discovery.build", return_value=MagicMock()
    ), patch("health_aggregator.live.calendar_live.list_calendars", return_value=fake_calendars), patch(
        "health_aggregator.live.calendar_live.fetch_events", side_effect=fake_fetch
    ):
        counts = calendar_live.poll_once(conn, token_path=str(tmp_path / "token.json"))

    assert counts == {"calendar_events": 2}
    events = dbmod.load_calendar_events(conn)
    assert set(events["calendar_name"]) == {"Personal", "Work"}
