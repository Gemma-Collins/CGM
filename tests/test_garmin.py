import os

import pandas as pd

from health_aggregator.importers import garmin

FIXTURES = os.path.join(os.path.dirname(__file__), "fixtures")


def test_records_to_hr_frame_drops_missing_values():
    records = [
        {"timestamp": pd.Timestamp("2026-08-10 08:00:00"), "heart_rate": 80},
        {"timestamp": pd.Timestamp("2026-08-10 08:00:01"), "heart_rate": None},
        {"timestamp": None, "heart_rate": 82},
    ]
    df = garmin._records_to_hr_frame(records, source="garmin_fit")
    assert len(df) == 1
    assert df.iloc[0]["bpm"] == 80
    assert df.iloc[0]["source"] == "garmin_fit"


def test_sessions_to_activity_frame_computes_end_from_elapsed_time():
    sessions = [
        {
            "start_time": pd.Timestamp("2026-08-10 08:00:00"),
            "total_elapsed_time": 1800,
            "sport": "running",
            "avg_heart_rate": 140,
            "max_heart_rate": 165,
            "total_calories": 300,
            "total_distance": 5000,
            "total_steps": 6000,
            "total_strides": None,
        }
    ]
    df = garmin._sessions_to_activity_frame(sessions, source="garmin_fit")
    assert len(df) == 1
    row = df.iloc[0]
    assert row["end"] == pd.Timestamp("2026-08-10 08:30:00")
    assert row["activity_type"] == "running"
    assert row["steps"] == 6000


def test_parse_csv_fallback_autodetects_columns():
    df = garmin.parse_csv(os.path.join(FIXTURES, "garmin_hr_sample.csv"))
    assert len(df) == 6
    assert df["source"].unique().tolist() == ["garmin_csv"]
    assert df["bpm"].max() == 135


def test_parse_fit_directory_returns_empty_frames_for_no_files(tmp_path):
    hr_df, activity_df = garmin.parse_fit_directory(str(tmp_path))
    assert hr_df.empty
    assert activity_df.empty
