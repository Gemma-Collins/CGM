"""Live Google Calendar puller - pulls upcoming/recent events so the
recommendation-style features described in the insulin decision-support
doc (activity/travel-aware timing) have calendar context to work from.
Read-only: this never writes to your calendar.

Google's OAuth flow needs an interactive browser consent step once, which
doesn't fit a background poll loop - so connecting is split into two calls:
``connect_interactive`` (run once, opens a browser, caches a token) and
``poll_once`` (safe to call repeatedly/automatically, uses only the cached
token and refreshes it silently when it can).
"""

import os

import pandas as pd

from health_aggregator import db as dbmod
from health_aggregator.models import CALENDAR_COLUMNS, empty_frame, ensure_schema

SCOPES = ["https://www.googleapis.com/auth/calendar.readonly"]

DEFAULT_TOKEN_PATH = os.path.expanduser("~/.health_aggregator/google_calendar_token.json")
DEFAULT_CLIENT_SECRETS_PATH = os.path.expanduser("~/.health_aggregator/google_calendar_credentials.json")

# Keyword -> event_type. Checked in order; first match wins.
_KEYWORDS = {
    "activity": ["gym", "workout", "run", "ride", "swim", "exercise", "training", "yoga", "walk", "hike", "sport"],
    "travel": ["flight", "travel", "trip", "airport", "drive to", "train to"],
}


def _classify_event(title: str) -> str:
    lowered = (title or "").lower()
    for event_type, keywords in _KEYWORDS.items():
        if any(kw in lowered for kw in keywords):
            return event_type
    return "other"


def _to_naive_timestamp(value: str) -> pd.Timestamp:
    ts = pd.Timestamp(value)
    return ts.tz_localize(None) if ts.tzinfo is not None else ts


def _events_payload_to_frame(items: list, calendar_name: str = "primary") -> pd.DataFrame:
    """Normalize a Calendar API `events.list` response's `items` list.
    Handles both timed events (`dateTime`) and all-day events (`date`)."""
    rows = []
    for item in items or []:
        start_raw = (item.get("start") or {}).get("dateTime") or (item.get("start") or {}).get("date")
        end_raw = (item.get("end") or {}).get("dateTime") or (item.get("end") or {}).get("date")
        if start_raw is None or end_raw is None:
            continue
        title = item.get("summary") or "(untitled)"
        rows.append(
            {
                "start": _to_naive_timestamp(start_raw),
                "end": _to_naive_timestamp(end_raw),
                "title": title,
                "event_type": _classify_event(title),
                "calendar_name": calendar_name,
            }
        )
    if not rows:
        return empty_frame(CALENDAR_COLUMNS)
    df = pd.DataFrame(rows)
    df["source"] = "google_calendar"
    return ensure_schema(df, CALENDAR_COLUMNS)


def _load_cached_credentials(token_path: str):
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials

    if not os.path.exists(token_path):
        return None
    creds = Credentials.from_authorized_user_file(token_path, SCOPES)
    if creds and creds.expired and creds.refresh_token:
        creds.refresh(Request())
        with open(token_path, "w") as f:
            f.write(creds.to_json())
    return creds


def connect_interactive(client_secrets_path: str = DEFAULT_CLIENT_SECRETS_PATH, token_path: str = DEFAULT_TOKEN_PATH) -> None:
    """One-time setup: opens a browser for Google's consent screen, then
    caches the resulting token so `poll_once` never needs this again (until
    you revoke access). `client_secrets_path` is the OAuth client JSON you
    download from Google Cloud Console (APIs & Services -> Credentials ->
    Create Credentials -> OAuth client ID -> Desktop app)."""
    from google_auth_oauthlib.flow import InstalledAppFlow

    if not os.path.exists(client_secrets_path):
        raise FileNotFoundError(
            f"no Google OAuth client secrets file at {client_secrets_path} - download one from "
            "Google Cloud Console (Calendar API must be enabled) and save it there, or pass --client-secrets"
        )
    flow = InstalledAppFlow.from_client_secrets_file(client_secrets_path, SCOPES)
    creds = flow.run_local_server(port=0)
    os.makedirs(os.path.dirname(token_path), exist_ok=True)
    with open(token_path, "w") as f:
        f.write(creds.to_json())


def fetch_events(service, time_min: pd.Timestamp, time_max: pd.Timestamp, calendar_id: str = "primary") -> list:
    result = (
        service.events()
        .list(
            calendarId=calendar_id,
            timeMin=time_min.isoformat() + "Z",
            timeMax=time_max.isoformat() + "Z",
            singleEvents=True,
            orderBy="startTime",
        )
        .execute()
    )
    return result.get("items", [])


def list_calendars(service) -> list:
    """Every calendar on the account (primary plus any others - work,
    shared, holidays, ...), so events can be tagged with which one they
    came from and shown/hidden per-calendar in the day view."""
    result = service.calendarList().list().execute()
    return [
        {"id": item["id"], "summary": item.get("summary", item["id"])}
        for item in result.get("items", [])
    ]


def poll_once(conn, token_path: str = DEFAULT_TOKEN_PATH, days_back: int = 1, days_ahead: int = 7) -> dict:
    """Fetch events from every calendar on the account, in
    [now - days_back, now + days_ahead], and upsert them. Raises if
    Calendar isn't connected yet - call connect_interactive first."""
    from googleapiclient.discovery import build

    creds = _load_cached_credentials(token_path)
    if creds is None or not creds.valid:
        raise RuntimeError("Google Calendar isn't connected yet - run connect_interactive() / 'connect-calendar' first")

    service = build("calendar", "v3", credentials=creds)
    now = pd.Timestamp.now()
    time_min, time_max = now - pd.Timedelta(days=days_back), now + pd.Timedelta(days=days_ahead)

    frames = []
    for calendar in list_calendars(service):
        items = fetch_events(service, time_min, time_max, calendar_id=calendar["id"])
        frames.append(_events_payload_to_frame(items, calendar_name=calendar["summary"]))

    events_df = pd.concat(frames, ignore_index=True) if frames else empty_frame(CALENDAR_COLUMNS)
    return {"calendar_events": dbmod.upsert_calendar_events(conn, events_df)}
