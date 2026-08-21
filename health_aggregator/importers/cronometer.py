"""Cronometer importer: carb intake from a CSV export.

Cronometer -> Settings -> Export Data. Two export shapes are supported:

* "Servings" export - one row per food logged, with a ``Day``/``Date`` and
  ``Time`` column, giving carb timing at meal granularity.
* "Daily Summary" export - one row per day with a total carbs figure and no
  time-of-day; entries are placed at noon local time since no finer timing
  exists.

Column names have changed across Cronometer versions, so columns are found
by fuzzy (case-insensitive substring) matching rather than exact names.
"""

import re

import pandas as pd

from health_aggregator.models import CARB_COLUMNS, ensure_schema

_DEFAULT_TIME_OF_DAY = "12:00:00"


def _find_column(columns: list[str], pattern: str) -> str | None:
    regex = re.compile(pattern, re.IGNORECASE)
    for c in columns:
        if regex.search(c):
            return c
    return None


def parse_csv(path: str) -> pd.DataFrame:
    raw = pd.read_csv(path)
    columns = list(raw.columns)

    day_col = _find_column(columns, r"^(day|date)$") or _find_column(columns, r"day|date")
    time_col = _find_column(columns, r"^time$")
    # Prefer a plain "Carbs (g)" total over "Net Carbs" if both are present.
    carbs_col = _find_column(columns, r"^carbs\s*\(g\)$") or _find_column(columns, r"carb")
    food_col = _find_column(columns, r"food\s*name") or _find_column(columns, r"^food$")
    energy_col = _find_column(columns, r"energy|calorie")

    if day_col is None or carbs_col is None:
        raise ValueError(
            f"couldn't find date/carbs columns in {path}; got {columns}"
        )

    day = raw[day_col].astype(str)
    if time_col is not None:
        time = raw[time_col].astype(str).fillna(_DEFAULT_TIME_OF_DAY)
        time = time.where(raw[time_col].notna(), _DEFAULT_TIME_OF_DAY)
        timestamp = pd.to_datetime(day + " " + time, errors="coerce")
    else:
        timestamp = pd.to_datetime(day + " " + _DEFAULT_TIME_OF_DAY, errors="coerce")

    df = pd.DataFrame(
        {
            "timestamp": timestamp,
            "food_name": raw[food_col] if food_col is not None else "unknown",
            "carbs_g": pd.to_numeric(raw[carbs_col], errors="coerce"),
            "calories_kcal": pd.to_numeric(raw[energy_col], errors="coerce")
            if energy_col is not None
            else float("nan"),
        }
    )
    df = df.dropna(subset=["timestamp", "carbs_g"])
    df["source"] = "cronometer"
    return ensure_schema(df, CARB_COLUMNS)
