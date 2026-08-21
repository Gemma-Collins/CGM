import pandas as pd

from health_aggregator.merge import daily_summary, merge_all
from health_aggregator.models import ACTIVITY_COLUMNS, CARB_COLUMNS, GLUCOSE_COLUMNS, HEART_RATE_COLUMNS, ensure_schema


def _glucose_df():
    return ensure_schema(
        pd.DataFrame(
            {
                "timestamp": pd.to_datetime(
                    ["2026-08-10 08:00", "2026-08-10 08:05", "2026-08-10 08:10", "2026-08-10 08:15"]
                ),
                "mg_dl": [90.0, 100.0, 150.0, 160.0],
                "reading_type": ["historic"] * 4,
                "source": ["libreview"] * 4,
            }
        ),
        GLUCOSE_COLUMNS,
    )


def _carb_df():
    return ensure_schema(
        pd.DataFrame(
            {
                "timestamp": pd.to_datetime(["2026-08-10 08:02"]),
                "food_name": ["toast"],
                "carbs_g": [30.0],
                "calories_kcal": [150.0],
                "source": ["cronometer"],
            }
        ),
        CARB_COLUMNS,
    )


def _hr_df():
    return ensure_schema(
        pd.DataFrame(
            {
                "timestamp": pd.to_datetime(["2026-08-10 08:03", "2026-08-10 08:12"]),
                "bpm": [130.0, 140.0],
                "source": ["garmin_fit"] * 2,
            }
        ),
        HEART_RATE_COLUMNS,
    )


def _activity_df():
    return ensure_schema(
        pd.DataFrame(
            {
                "start": pd.to_datetime(["2026-08-10 08:00"]),
                "end": pd.to_datetime(["2026-08-10 08:10"]),
                "activity_type": ["running"],
                "avg_hr": [135.0],
                "max_hr": [145.0],
                "calories_kcal": [80.0],
                "distance_m": [1000.0],
                "steps": [1200.0],
                "source": ["garmin_fit"],
            }
        ),
        ACTIVITY_COLUMNS,
    )


def test_merge_all_aligns_sources_on_5_minute_grid():
    merged = merge_all(_glucose_df(), _carb_df(), _hr_df(), _activity_df(), freq="5min")
    assert list(merged["timestamp"]) == list(
        pd.date_range("2026-08-10 08:00", "2026-08-10 08:15", freq="5min")
    )
    # carb entry at 08:02 falls in the 08:00 bucket
    assert merged.loc[merged["timestamp"] == "2026-08-10 08:00", "carbs_g"].iloc[0] == 30.0
    # no meal logged in the other buckets -> 0, not NaN
    assert merged.loc[merged["timestamp"] == "2026-08-10 08:05", "carbs_g"].iloc[0] == 0.0
    # activity spans 08:00-08:10 inclusive
    assert merged.loc[merged["timestamp"] == "2026-08-10 08:00", "in_activity"].iloc[0]
    assert merged.loc[merged["timestamp"] == "2026-08-10 08:10", "in_activity"].iloc[0]
    assert not merged.loc[merged["timestamp"] == "2026-08-10 08:15", "in_activity"].iloc[0]


def test_merge_all_handles_missing_sources():
    from health_aggregator.models import empty_frame

    merged = merge_all(_glucose_df(), empty_frame(CARB_COLUMNS), empty_frame(HEART_RATE_COLUMNS), empty_frame(ACTIVITY_COLUMNS))
    assert "glucose_mg_dl" in merged.columns
    assert "carbs_g" not in merged.columns
    assert not merged["in_activity"].any()


def test_daily_summary_computes_time_in_range():
    merged = merge_all(_glucose_df(), _carb_df(), _hr_df(), _activity_df(), freq="5min")
    daily = daily_summary(merged, low_mg_dl=70, high_mg_dl=140)
    assert len(daily) == 1
    row = daily.iloc[0]
    assert row["total_carbs_g"] == 30.0
    # 90 and 100 in range, 150 and 160 out -> 50%
    assert row["pct_time_in_range"] == 50.0
