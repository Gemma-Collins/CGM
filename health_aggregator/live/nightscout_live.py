"""Live Nightscout puller - the live counterpart to the file-based Nightscout
CSV import in ``importers/cgm.py``, for xDrip+/MiaoMiao setups where xDrip+
already uploads to a Nightscout site.

Unlike Garmin, this talks to a real, documented REST API - Nightscout is
open source and meant to be queried - authenticated with your own site's
read-only token or API secret, not a reverse-engineered account login. It
won't break from Garmin-style backend changes, and there's no bot-detection
risk since it's your own server.
"""

import hashlib
import os

import pandas as pd
import requests

from health_aggregator import db as dbmod
from health_aggregator.models import GLUCOSE_COLUMNS, empty_frame, ensure_schema

DEFAULT_COUNT = 1000


def _entries_payload_to_frame(payload: list) -> pd.DataFrame:
    """Normalize a Nightscout `/api/v1/entries.json` response."""
    rows = []
    for e in payload or []:
        sgv, date_ms = e.get("sgv"), e.get("date")
        if sgv is None or date_ms is None:
            continue
        rows.append(
            {
                "timestamp": pd.Timestamp(date_ms, unit="ms"),
                "mg_dl": sgv,
                "reading_type": e.get("type") or "sgv",
            }
        )
    if not rows:
        return empty_frame(GLUCOSE_COLUMNS)
    df = pd.DataFrame(rows)
    df["source"] = "nightscout_live"
    return ensure_schema(df, GLUCOSE_COLUMNS)


def _auth_params_and_headers(token: str | None, api_secret: str | None) -> tuple:
    """A read-only access token goes in the query string; the classic master
    API secret is sent hashed (Nightscout expects SHA1, not the raw value)."""
    params, headers = {}, {}
    if token:
        params["token"] = token
    elif api_secret:
        headers["API-SECRET"] = hashlib.sha1(api_secret.encode()).hexdigest()
    else:
        raise ValueError("one of NIGHTSCOUT_TOKEN or NIGHTSCOUT_API_SECRET is required")
    return params, headers


def fetch_entries(
    base_url: str,
    token: str | None = None,
    api_secret: str | None = None,
    since: pd.Timestamp | None = None,
    count: int = DEFAULT_COUNT,
) -> list:
    auth_params, headers = _auth_params_and_headers(token, api_secret)
    params = {"count": count, **auth_params}
    if since is not None:
        params["find[date][$gte]"] = int(pd.Timestamp(since).timestamp() * 1000)

    url = base_url.rstrip("/") + "/api/v1/entries.json"
    response = requests.get(url, params=params, headers=headers, timeout=30)
    response.raise_for_status()
    return response.json()


def poll_once(
    conn,
    base_url: str | None = None,
    token: str | None = None,
    api_secret: str | None = None,
    count: int = DEFAULT_COUNT,
) -> dict:
    """Fetch glucose entries newer than whatever's already stored for this
    source, and upsert them. Returns {"glucose": n} new rows."""
    base_url = base_url or os.environ.get("NIGHTSCOUT_URL")
    token = token or os.environ.get("NIGHTSCOUT_TOKEN")
    api_secret = api_secret or os.environ.get("NIGHTSCOUT_API_SECRET")
    if not base_url:
        raise ValueError("NIGHTSCOUT_URL is required (env var or --nightscout-url)")

    since = dbmod.latest_timestamp(conn, "glucose_readings", "timestamp", "nightscout_live")
    payload = fetch_entries(base_url, token=token, api_secret=api_secret, since=since, count=count)
    glucose_df = _entries_payload_to_frame(payload)
    return {"glucose": dbmod.upsert_glucose(conn, glucose_df)}
