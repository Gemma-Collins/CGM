import pandas as pd

from health_aggregator.live import garmin_live


def test_heart_rate_payload_to_frame_drops_null_readings():
    payload = {
        "calendarDate": "2026-08-10",
        "heartRateValues": [
            [1786000000000, 70],
            [1786000060000, None],
            [1786000120000, 85],
        ],
    }
    df = garmin_live._heart_rate_payload_to_frame(payload)
    assert len(df) == 2
    assert set(df["source"]) == {"garmin_live"}
    assert df["bpm"].tolist() == [70.0, 85.0]


def test_heart_rate_payload_to_frame_handles_empty_payload():
    df = garmin_live._heart_rate_payload_to_frame({"heartRateValues": []})
    assert df.empty
    df = garmin_live._heart_rate_payload_to_frame(None)
    assert df.empty


def test_activities_payload_to_frame_computes_end_from_duration():
    payload = [
        {
            "startTimeLocal": "2026-08-10 08:00:00",
            "duration": 1800,
            "activityType": {"typeKey": "running"},
            "averageHR": 140,
            "maxHR": 165,
            "calories": 300,
            "distance": 5000,
            "steps": 6000,
        }
    ]
    df = garmin_live._activities_payload_to_frame(payload)
    assert len(df) == 1
    row = df.iloc[0]
    assert row["end"] == pd.Timestamp("2026-08-10 08:30:00")
    assert row["activity_type"] == "running"
    assert row["source"] == "garmin_live"


def test_activities_payload_to_frame_skips_entries_without_start_time():
    df = garmin_live._activities_payload_to_frame([{"duration": 100}])
    assert df.empty
