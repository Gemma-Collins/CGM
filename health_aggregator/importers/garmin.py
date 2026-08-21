"""Garmin vivoactive importer: activities + heart rate.

Primary path is parsing ``.fit`` files exported from Garmin Connect
(activity page -> gear icon -> "Export Original"). A CSV fallback is
provided for any tool that dumps a simple ``timestamp, heart_rate`` table
(e.g. a chart export) when a raw FIT file isn't available.
"""

import glob
import os
import warnings

import pandas as pd

from health_aggregator.models import (
    ACTIVITY_COLUMNS,
    HEART_RATE_COLUMNS,
    empty_frame,
    ensure_schema,
)

# Candidate column names (lowercased) accepted by the CSV fallback importer.
_TIMESTAMP_ALIASES = ("timestamp", "time", "date", "datetime")
_HR_ALIASES = ("heart_rate", "heartrate", "bpm", "hr")


def _records_to_hr_frame(records: list[dict], source: str) -> pd.DataFrame:
    """Turn a list of FIT 'record' message dicts into the heart-rate schema."""
    rows = [
        {"timestamp": r["timestamp"], "bpm": r["heart_rate"]}
        for r in records
        if r.get("timestamp") is not None and r.get("heart_rate") is not None
    ]
    if not rows:
        return empty_frame(HEART_RATE_COLUMNS)
    df = pd.DataFrame(rows)
    df["source"] = source
    return ensure_schema(df, HEART_RATE_COLUMNS)


def _sessions_to_activity_frame(sessions: list[dict], source: str) -> pd.DataFrame:
    """Turn a list of FIT 'session' message dicts into the activity schema."""
    rows = []
    for s in sessions:
        start = s.get("start_time")
        if start is None:
            continue
        elapsed = s.get("total_elapsed_time") or 0
        end = start + pd.Timedelta(seconds=elapsed)
        rows.append(
            {
                "start": start,
                "end": end,
                "activity_type": s.get("sport") or "unknown",
                "avg_hr": s.get("avg_heart_rate"),
                "max_hr": s.get("max_heart_rate"),
                "calories_kcal": s.get("total_calories"),
                "distance_m": s.get("total_distance"),
                "steps": s.get("total_steps") or s.get("total_strides"),
            }
        )
    if not rows:
        return empty_frame(ACTIVITY_COLUMNS)
    df = pd.DataFrame(rows)
    df["source"] = source
    return ensure_schema(df, ACTIVITY_COLUMNS)


def parse_fit_file(path: str) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Parse one .fit activity file into (heart_rate_df, activity_df)."""
    import fitparse

    fit = fitparse.FitFile(path)
    records = [
        {"timestamp": m.get_value("timestamp"), "heart_rate": m.get_value("heart_rate")}
        for m in fit.get_messages("record")
    ]
    sessions = [
        {
            "start_time": m.get_value("start_time"),
            "total_elapsed_time": m.get_value("total_elapsed_time"),
            "sport": m.get_value("sport"),
            "avg_heart_rate": m.get_value("avg_heart_rate"),
            "max_heart_rate": m.get_value("max_heart_rate"),
            "total_calories": m.get_value("total_calories"),
            "total_distance": m.get_value("total_distance"),
            "total_steps": m.get_value("total_steps"),
            "total_strides": m.get_value("total_strides"),
        }
        for m in fit.get_messages("session")
    ]
    hr_df = _records_to_hr_frame(records, source="garmin_fit")
    activity_df = _sessions_to_activity_frame(sessions, source="garmin_fit")
    return hr_df, activity_df


def parse_fit_directory(dir_path: str) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Parse every .fit file in a directory (as exported from Garmin Connect)."""
    paths = sorted(glob.glob(os.path.join(dir_path, "*.fit")))
    hr_frames, activity_frames = [], []
    for path in paths:
        try:
            hr_df, activity_df = parse_fit_file(path)
        except Exception as exc:  # noqa: BLE001 - one bad file shouldn't abort the run
            warnings.warn(f"skipping unreadable FIT file {path}: {exc}")
            continue
        hr_frames.append(hr_df)
        activity_frames.append(activity_df)

    hr_df = (
        pd.concat(hr_frames, ignore_index=True).sort_values("timestamp").reset_index(drop=True)
        if hr_frames
        else empty_frame(HEART_RATE_COLUMNS)
    )
    activity_df = (
        pd.concat(activity_frames, ignore_index=True).sort_values("start").reset_index(drop=True)
        if activity_frames
        else empty_frame(ACTIVITY_COLUMNS)
    )
    return hr_df, activity_df


def _find_column(columns: list[str], aliases: tuple) -> str | None:
    lowered = {c.lower().strip(): c for c in columns}
    for alias in aliases:
        if alias in lowered:
            return lowered[alias]
    return None


def parse_csv(path: str) -> pd.DataFrame:
    """Fallback for a simple heart-rate CSV export (timestamp + bpm columns)."""
    raw = pd.read_csv(path)
    ts_col = _find_column(list(raw.columns), _TIMESTAMP_ALIASES)
    hr_col = _find_column(list(raw.columns), _HR_ALIASES)
    if ts_col is None or hr_col is None:
        raise ValueError(
            f"couldn't find timestamp/heart-rate columns in {path}; got {list(raw.columns)}"
        )
    df = pd.DataFrame({"timestamp": raw[ts_col], "bpm": raw[hr_col]})
    df = df.dropna(subset=["bpm"])
    df["source"] = "garmin_csv"
    return ensure_schema(df, HEART_RATE_COLUMNS)
