"""Align glucose, carbs, heart rate, and activity onto one common timeline.

Each source has a different natural sampling rate (CGM every 1-15 min,
heart rate every 1-5 sec during a workout, carb entries whenever a meal is
logged), so everything is resampled onto a uniform grid (default 5 minutes)
before being joined.
"""

import pandas as pd

from health_aggregator.models import INSULIN_COLUMNS, empty_frame


def merge_all(
    glucose_df: pd.DataFrame,
    carb_df: pd.DataFrame,
    hr_df: pd.DataFrame,
    activity_df: pd.DataFrame,
    insulin_df: pd.DataFrame = None,
    freq: str = "5min",
) -> pd.DataFrame:
    if insulin_df is None:
        insulin_df = empty_frame(INSULIN_COLUMNS)

    series = {}
    if not glucose_df.empty:
        series["glucose_mg_dl"] = glucose_df.set_index("timestamp")["mg_dl"].resample(freq).mean()
    if not hr_df.empty:
        series["bpm"] = hr_df.set_index("timestamp")["bpm"].resample(freq).mean()
    if not carb_df.empty:
        series["carbs_g"] = carb_df.set_index("timestamp")["carbs_g"].resample(freq).sum()
    if not insulin_df.empty:
        series["insulin_units"] = insulin_df.set_index("timestamp")["units"].resample(freq).sum()

    if not series:
        return pd.DataFrame(
            columns=["timestamp", "glucose_mg_dl", "bpm", "carbs_g", "insulin_units", "in_activity", "activity_type"]
        )

    merged = pd.concat(series, axis=1).sort_index()
    full_index = pd.date_range(merged.index.min(), merged.index.max(), freq=freq)
    merged = merged.reindex(full_index)
    merged.index.name = "timestamp"

    for summed_col in ("carbs_g", "insulin_units"):
        if summed_col in merged:
            # A blank bucket means nothing was logged, i.e. zero - unlike
            # glucose/heart-rate gaps, which genuinely mean "no reading".
            merged[summed_col] = merged[summed_col].fillna(0.0)

    merged["in_activity"] = False
    merged["activity_type"] = None
    for _, act in activity_df.iterrows():
        mask = (merged.index >= act["start"]) & (merged.index <= act["end"])
        merged.loc[mask, "in_activity"] = True
        merged.loc[mask, "activity_type"] = act["activity_type"]

    return merged.reset_index().rename(columns={"index": "timestamp"})


def daily_summary(merged: pd.DataFrame, low_mg_dl: float = 70, high_mg_dl: float = 180) -> pd.DataFrame:
    """Per-day rollup: average glucose, time-in-range, total carbs, active minutes."""
    if merged.empty:
        return pd.DataFrame(
            columns=[
                "date", "avg_glucose_mg_dl", "pct_time_in_range", "total_carbs_g",
                "total_insulin_units", "active_minutes",
            ]
        )

    df = merged.copy()
    df["date"] = df["timestamp"].dt.date
    freq_minutes = (df["timestamp"].iloc[1] - df["timestamp"].iloc[0]).total_seconds() / 60 if len(df) > 1 else 5

    def _summarize(g: pd.DataFrame) -> pd.Series:
        glucose = g["glucose_mg_dl"].dropna()
        in_range = glucose.between(low_mg_dl, high_mg_dl)
        return pd.Series(
            {
                "avg_glucose_mg_dl": glucose.mean() if not glucose.empty else float("nan"),
                "pct_time_in_range": 100 * in_range.mean() if not glucose.empty else float("nan"),
                "total_carbs_g": g["carbs_g"].sum() if "carbs_g" in g else 0.0,
                "total_insulin_units": g["insulin_units"].sum() if "insulin_units" in g else 0.0,
                "active_minutes": g["in_activity"].sum() * freq_minutes,
            }
        )

    return df.groupby("date").apply(_summarize, include_groups=False).reset_index()
