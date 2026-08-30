import pandas as pd

from health_aggregator import db as dbmod
from tests.test_merge import _activity_df, _carb_df, _glucose_df, _hr_df, _insulin_df


def test_upsert_and_load_glucose(tmp_path):
    conn = dbmod.connect(str(tmp_path / "health.db"))
    n = dbmod.upsert_glucose(conn, _glucose_df())
    assert n == 4

    loaded = dbmod.load_glucose(conn)
    assert len(loaded) == 4
    assert loaded["mg_dl"].max() == 160.0


def test_upsert_is_idempotent(tmp_path):
    conn = dbmod.connect(str(tmp_path / "health.db"))
    dbmod.upsert_glucose(conn, _glucose_df())
    second = dbmod.upsert_glucose(conn, _glucose_df())
    assert second == 0
    assert len(dbmod.load_glucose(conn)) == 4


def test_load_respects_date_range(tmp_path):
    conn = dbmod.connect(str(tmp_path / "health.db"))
    dbmod.upsert_glucose(conn, _glucose_df())
    subset = dbmod.load_glucose(conn, start="2026-08-10 08:06", end="2026-08-10 08:20")
    assert len(subset) == 2


def test_all_five_tables_roundtrip(tmp_path):
    conn = dbmod.connect(str(tmp_path / "health.db"))
    dbmod.upsert_glucose(conn, _glucose_df())
    dbmod.upsert_carbs(conn, _carb_df())
    dbmod.upsert_heart_rate(conn, _hr_df())
    dbmod.upsert_activities(conn, _activity_df())
    dbmod.upsert_insulin(conn, _insulin_df())

    assert len(dbmod.load_glucose(conn)) == 4
    assert len(dbmod.load_carbs(conn)) == 1
    assert len(dbmod.load_heart_rate(conn)) == 2
    activities = dbmod.load_activities(conn)
    assert len(activities) == 1
    assert activities.iloc[0]["activity_type"] == "running"
    insulin = dbmod.load_insulin(conn)
    assert len(insulin) == 1
    assert insulin.iloc[0]["units"] == 4.5


def test_upsert_insulin_is_idempotent(tmp_path):
    conn = dbmod.connect(str(tmp_path / "health.db"))
    dbmod.upsert_insulin(conn, _insulin_df())
    second = dbmod.upsert_insulin(conn, _insulin_df())
    assert second == 0
    assert len(dbmod.load_insulin(conn)) == 1


def test_reopening_db_persists_data(tmp_path):
    path = str(tmp_path / "health.db")
    conn = dbmod.connect(path)
    dbmod.upsert_glucose(conn, _glucose_df())
    conn.close()

    reopened = dbmod.connect(path)
    assert len(dbmod.load_glucose(reopened)) == 4


def test_latest_timestamp_returns_none_when_no_rows_for_source(tmp_path):
    conn = dbmod.connect(str(tmp_path / "health.db"))
    assert dbmod.latest_timestamp(conn, "glucose_readings", "timestamp", "nightscout_live") is None


def test_latest_timestamp_returns_max_for_that_source_only(tmp_path):
    conn = dbmod.connect(str(tmp_path / "health.db"))
    dbmod.upsert_glucose(conn, _glucose_df())  # source is "libreview"
    assert dbmod.latest_timestamp(conn, "glucose_readings", "timestamp", "nightscout_live") is None
    assert dbmod.latest_timestamp(conn, "glucose_readings", "timestamp", "libreview") == pd.Timestamp(
        "2026-08-10 08:15:00"
    )


def test_upsert_and_load_calendar_events(tmp_path):
    from health_aggregator.models import CALENDAR_COLUMNS, ensure_schema

    conn = dbmod.connect(str(tmp_path / "health.db"))
    df = ensure_schema(
        pd.DataFrame(
            {
                "start": pd.to_datetime(["2026-08-10 07:00"]),
                "end": pd.to_datetime(["2026-08-10 08:00"]),
                "title": ["Gym"],
                "event_type": ["activity"],
                "source": ["google_calendar"],
            }
        ),
        CALENDAR_COLUMNS,
    )

    n = dbmod.upsert_calendar_events(conn, df)
    assert n == 1
    loaded = dbmod.load_calendar_events(conn)
    assert len(loaded) == 1
    assert loaded.iloc[0]["title"] == "Gym"

    second = dbmod.upsert_calendar_events(conn, df)
    assert second == 0


def test_record_and_load_poll_log(tmp_path):
    conn = dbmod.connect(str(tmp_path / "health.db"))
    started = pd.Timestamp("2026-08-10 08:00:00")
    finished = pd.Timestamp("2026-08-10 08:00:05")
    dbmod.record_poll(conn, "garmin_live", started, finished, "success", rows_added=12)

    polls = dbmod.last_polls(conn)
    assert len(polls) == 1
    assert polls.iloc[0]["source"] == "garmin_live"
    assert polls.iloc[0]["status"] == "success"
    assert polls.iloc[0]["rows_added"] == 12


def test_last_polls_returns_most_recent_per_source(tmp_path):
    conn = dbmod.connect(str(tmp_path / "health.db"))
    dbmod.record_poll(conn, "garmin_live", pd.Timestamp("2026-08-10 08:00"), pd.Timestamp("2026-08-10 08:00:05"), "error", error_message="401")
    dbmod.record_poll(conn, "garmin_live", pd.Timestamp("2026-08-10 09:00"), pd.Timestamp("2026-08-10 09:00:05"), "success", rows_added=3)

    polls = dbmod.last_polls(conn)
    assert len(polls) == 1
    assert polls.iloc[0]["status"] == "success"
    assert polls.iloc[0]["rows_added"] == 3
