"""CGM importer: glucose readings from a Libre 2 (LibreView) export, or a
Nightscout/xDrip+ CSV export (the common path when using a MiaoMiao/Libre
sensor with xDrip+, since xDrip+ can export or upload to Nightscout, whose
reports are downloadable as CSV).

The two formats are auto-detected from the CSV header; pass
``format_hint`` to skip detection if it ever guesses wrong.
"""

import re

import pandas as pd

from health_aggregator.models import GLUCOSE_COLUMNS, ensure_schema

_LIBREVIEW_TIMESTAMP_COL = "Device Timestamp"
_LIBREVIEW_HISTORIC_COL = "Historic Glucose mg/dL"
_LIBREVIEW_SCAN_COL = "Scan Glucose mg/dL"
_LIBREVIEW_RECORD_TYPE_COL = "Record Type"


def detect_format(columns: list[str]) -> str:
    if _LIBREVIEW_TIMESTAMP_COL in columns and (
        _LIBREVIEW_HISTORIC_COL in columns or _LIBREVIEW_SCAN_COL in columns
    ):
        return "libreview"
    if "sgv" in [c.lower() for c in columns]:
        return "nightscout"
    return "generic"


def _parse_libreview(raw: pd.DataFrame) -> pd.DataFrame:
    rows = []
    record_type = raw.get(_LIBREVIEW_RECORD_TYPE_COL)
    historic = raw.get(_LIBREVIEW_HISTORIC_COL)
    scan = raw.get(_LIBREVIEW_SCAN_COL)
    timestamps = pd.to_datetime(raw[_LIBREVIEW_TIMESTAMP_COL], errors="coerce")

    for i in range(len(raw)):
        value = None
        reading_type = None
        if historic is not None and pd.notna(historic.iloc[i]):
            value, reading_type = historic.iloc[i], "historic"
        elif scan is not None and pd.notna(scan.iloc[i]):
            value, reading_type = scan.iloc[i], "scan"
        if value is None or pd.isna(timestamps.iloc[i]):
            continue
        rows.append({"timestamp": timestamps.iloc[i], "mg_dl": value, "reading_type": reading_type})

    df = pd.DataFrame(rows)
    df["source"] = "libreview"
    return df


def _parse_nightscout(raw: pd.DataFrame) -> pd.DataFrame:
    columns = {c.lower(): c for c in raw.columns}
    sgv_col = columns["sgv"]

    if "datestring" in columns:
        timestamp = pd.to_datetime(raw[columns["datestring"]], errors="coerce", utc=True).dt.tz_localize(None)
    elif "date" in columns:
        # Nightscout's numeric "date" field is epoch milliseconds.
        timestamp = pd.to_datetime(raw[columns["date"]], unit="ms", errors="coerce")
    elif "timestamp" in columns:
        timestamp = pd.to_datetime(raw[columns["timestamp"]], errors="coerce")
    else:
        raise ValueError("nightscout-style CSV has no dateString/date/timestamp column")

    df = pd.DataFrame(
        {
            "timestamp": timestamp,
            "mg_dl": pd.to_numeric(raw[sgv_col], errors="coerce"),
            "reading_type": "sgv",
        }
    )
    df["source"] = "nightscout"
    return df


def _parse_generic(raw: pd.DataFrame) -> pd.DataFrame:
    ts_col = next((c for c in raw.columns if re.search(r"time|date", c, re.IGNORECASE)), None)
    value_col = next((c for c in raw.columns if re.search(r"glucose|value", c, re.IGNORECASE)), None)
    if ts_col is None or value_col is None:
        raise ValueError(f"couldn't detect timestamp/glucose columns; got {list(raw.columns)}")
    df = pd.DataFrame(
        {
            "timestamp": pd.to_datetime(raw[ts_col], errors="coerce"),
            "mg_dl": pd.to_numeric(raw[value_col], errors="coerce"),
            "reading_type": "unknown",
        }
    )
    df["source"] = "cgm_generic"
    return df


def _read_csv_skipping_banner(path: str) -> pd.DataFrame:
    """LibreView's web export prepends a title/date banner line before the
    real header row; retry with skiprows=1 if the first parse looks wrong."""
    raw = pd.read_csv(path)
    if _LIBREVIEW_TIMESTAMP_COL not in raw.columns and "sgv" not in [c.lower() for c in raw.columns]:
        retried = pd.read_csv(path, skiprows=1)
        if _LIBREVIEW_TIMESTAMP_COL in retried.columns:
            return retried
    return raw


def parse_csv(path: str, format_hint: str | None = None) -> pd.DataFrame:
    raw = _read_csv_skipping_banner(path)
    fmt = format_hint or detect_format(list(raw.columns))

    if fmt == "libreview":
        df = _parse_libreview(raw)
    elif fmt == "nightscout":
        df = _parse_nightscout(raw)
    elif fmt == "generic":
        df = _parse_generic(raw)
    else:
        raise ValueError(f"unknown format_hint {fmt!r}; expected libreview/nightscout/generic")

    df = df.dropna(subset=["timestamp", "mg_dl"])
    return ensure_schema(df, GLUCOSE_COLUMNS)
