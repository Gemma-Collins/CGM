"""Unified schemas shared by every importer.

Each importer returns a pandas DataFrame with exactly these columns (extra
source-specific columns are fine, but these must be present with these
dtypes so ``merge.py`` can align sources without per-source special-casing).
All timestamps are timezone-naive local time.
"""

import pandas as pd

GLUCOSE_COLUMNS = {
    "timestamp": "datetime64[ns]",
    "mg_dl": "float64",
    "reading_type": "object",  # "historic" | "scan" | "sgv"
    "source": "object",  # "libreview" | "nightscout" | "xdrip"
}

CARB_COLUMNS = {
    "timestamp": "datetime64[ns]",
    "food_name": "object",
    "carbs_g": "float64",
    "calories_kcal": "float64",
    "source": "object",  # "cronometer"
}

HEART_RATE_COLUMNS = {
    "timestamp": "datetime64[ns]",
    "bpm": "float64",
    "source": "object",  # "garmin_fit" | "garmin_csv"
}

ACTIVITY_COLUMNS = {
    "start": "datetime64[ns]",
    "end": "datetime64[ns]",
    "activity_type": "object",
    "avg_hr": "float64",
    "max_hr": "float64",
    "calories_kcal": "float64",
    "distance_m": "float64",
    "steps": "float64",
    "source": "object",  # "garmin_fit"
}

INSULIN_COLUMNS = {
    "timestamp": "datetime64[ns]",
    "units": "float64",
    "dose_type": "object",  # Nightscout eventType, e.g. "Correction Bolus", "Meal Bolus"
    "source": "object",  # "nightscout_live"
}


def empty_frame(columns: dict) -> pd.DataFrame:
    """Build an empty, correctly-typed DataFrame for one of the schemas above."""
    df = pd.DataFrame({name: pd.Series(dtype=dtype) for name, dtype in columns.items()})
    return df


def ensure_schema(df: pd.DataFrame, columns: dict) -> pd.DataFrame:
    """Reorder/cast an importer's output to the canonical column set and dtypes."""
    missing = [c for c in columns if c not in df.columns]
    if missing:
        raise ValueError(f"missing required columns {missing}; got {list(df.columns)}")
    df = df[list(columns.keys())].copy()
    for name, dtype in columns.items():
        if dtype == "datetime64[ns]":
            df[name] = pd.to_datetime(df[name])
        else:
            df[name] = df[name].astype(dtype)
    return df.sort_values("timestamp" if "timestamp" in columns else "start").reset_index(drop=True)
