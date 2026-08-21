"""Live Garmin Connect puller - an alternative to the file-based Garmin
importer in ``importers/garmin.py``. Instead of you exporting a .fit file,
this logs into Garmin's cloud with your account (via the unofficial
`garminconnect` library, https://github.com/cyberjunky/python-garminconnect)
and fetches whatever heart-rate/activity data has already synced there from
your watch, normalizing it into the same schemas the file importer uses.

This is unofficial - Garmin doesn't publish or support an individual
developer API, so this can break if Garmin changes their backend. The
parsing functions below are separated from the network calls so they can
be unit-tested against fixture JSON without hitting Garmin's servers; the
exact field names come from the (undocumented) Garmin Connect web API and
may need adjusting if Garmin changes its response shape.

Credentials are read only from environment variables (GARMIN_EMAIL /
GARMIN_PASSWORD), never from CLI flags, so they don't end up in shell
history or `ps` output. After the first successful login, a session token
is cached to disk (see ``tokenstore``) so subsequent polls don't need to
log in again.
"""

import os
from datetime import date, timedelta

import pandas as pd

from health_aggregator import db as dbmod
from health_aggregator.models import (
    ACTIVITY_COLUMNS,
    HEART_RATE_COLUMNS,
    empty_frame,
    ensure_schema,
)

DEFAULT_TOKENSTORE = os.path.expanduser("~/.garmin_tokens")


def _heart_rate_payload_to_frame(payload: dict) -> pd.DataFrame:
    """Normalize a single day's `get_heart_rates` response."""
    values = (payload or {}).get("heartRateValues") or []
    rows = [
        {"timestamp": pd.Timestamp(ts, unit="ms"), "bpm": bpm}
        for ts, bpm in values
        if ts is not None and bpm is not None
    ]
    if not rows:
        return empty_frame(HEART_RATE_COLUMNS)
    df = pd.DataFrame(rows)
    df["source"] = "garmin_live"
    return ensure_schema(df, HEART_RATE_COLUMNS)


def _activities_payload_to_frame(payload: list) -> pd.DataFrame:
    """Normalize a `get_activities_by_date` response (a list of activity dicts)."""
    rows = []
    for a in payload or []:
        start = a.get("startTimeLocal")
        if start is None:
            continue
        duration_s = a.get("duration") or 0
        activity_type = (a.get("activityType") or {}).get("typeKey", "unknown")
        rows.append(
            {
                "start": pd.Timestamp(start),
                "end": pd.Timestamp(start) + pd.Timedelta(seconds=duration_s),
                "activity_type": activity_type,
                "avg_hr": a.get("averageHR"),
                "max_hr": a.get("maxHR"),
                "calories_kcal": a.get("calories"),
                "distance_m": a.get("distance"),
                "steps": a.get("steps"),
            }
        )
    if not rows:
        return empty_frame(ACTIVITY_COLUMNS)
    df = pd.DataFrame(rows)
    df["source"] = "garmin_live"
    return ensure_schema(df, ACTIVITY_COLUMNS)


def login(email: str | None = None, password: str | None = None, tokenstore: str = DEFAULT_TOKENSTORE):
    """Log into Garmin Connect, reusing a cached session token if one exists."""
    import garminconnect

    email = email or os.environ.get("GARMIN_EMAIL")
    password = password or os.environ.get("GARMIN_PASSWORD")
    client = garminconnect.Garmin(email=email, password=password)
    client.login(tokenstore=tokenstore)
    return client


def fetch_heart_rate(client, day: date) -> pd.DataFrame:
    payload = client.get_heart_rates(cdate=day.isoformat())
    return _heart_rate_payload_to_frame(payload)


def fetch_activities(client, start: date, end: date) -> pd.DataFrame:
    payload = client.get_activities_by_date(start.isoformat(), end.isoformat())
    return _activities_payload_to_frame(payload)


def poll_once(
    conn,
    email: str | None = None,
    password: str | None = None,
    tokenstore: str = DEFAULT_TOKENSTORE,
    days_back: int = 1,
) -> dict:
    """Fetch the last `days_back` days of heart rate + activities and upsert
    them into the database. Returns {"heart_rate": n, "activities": n} new rows."""
    client = login(email, password, tokenstore)
    today = date.today()
    start = today - timedelta(days=days_back - 1)

    hr_frames = [fetch_heart_rate(client, start + timedelta(days=d)) for d in range(days_back)]
    hr_df = pd.concat(hr_frames, ignore_index=True) if hr_frames else empty_frame(HEART_RATE_COLUMNS)
    activity_df = fetch_activities(client, start, today)

    return {
        "heart_rate": dbmod.upsert_heart_rate(conn, hr_df),
        "activities": dbmod.upsert_activities(conn, activity_df),
    }
