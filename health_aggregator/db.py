"""Local persistent store (SQLite) for imported health data.

Every import run upserts here instead of the data living only in memory for
that one run, so history accumulates across runs - repeated imports of
overlapping export files are deduplicated, and (once a live tracker exists)
a scheduler can call the importer repeatedly without piling up duplicates.
"""

import sqlite3

import pandas as pd

from health_aggregator.models import (
    ACTIVITY_COLUMNS,
    CARB_COLUMNS,
    GLUCOSE_COLUMNS,
    HEART_RATE_COLUMNS,
    empty_frame,
    ensure_schema,
)

_SCHEMA = """
CREATE TABLE IF NOT EXISTS glucose_readings (
    timestamp TEXT NOT NULL,
    mg_dl REAL NOT NULL,
    reading_type TEXT,
    source TEXT NOT NULL,
    UNIQUE(timestamp, source)
);
CREATE TABLE IF NOT EXISTS carb_entries (
    timestamp TEXT NOT NULL,
    food_name TEXT,
    carbs_g REAL NOT NULL,
    calories_kcal REAL,
    source TEXT NOT NULL,
    UNIQUE(timestamp, food_name, source)
);
CREATE TABLE IF NOT EXISTS heart_rate_samples (
    timestamp TEXT NOT NULL,
    bpm REAL NOT NULL,
    source TEXT NOT NULL,
    UNIQUE(timestamp, source)
);
CREATE TABLE IF NOT EXISTS activities (
    "start" TEXT NOT NULL,
    "end" TEXT NOT NULL,
    activity_type TEXT,
    avg_hr REAL,
    max_hr REAL,
    calories_kcal REAL,
    distance_m REAL,
    steps REAL,
    source TEXT NOT NULL,
    UNIQUE("start", source)
);
CREATE TABLE IF NOT EXISTS poll_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source TEXT NOT NULL,
    started_at TEXT NOT NULL,
    finished_at TEXT NOT NULL,
    status TEXT NOT NULL,
    rows_added INTEGER,
    error_message TEXT
);
"""


def connect(db_path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path)
    conn.executescript(_SCHEMA)
    return conn


def _upsert(conn: sqlite3.Connection, table: str, df: pd.DataFrame, columns: list) -> int:
    if df.empty:
        return 0
    col_list = ", ".join(f'"{c}"' for c in columns)
    placeholders = ", ".join("?" for _ in columns)
    rows = [tuple(row[c] for c in columns) for _, row in df.iterrows()]
    cur = conn.executemany(
        f'INSERT OR IGNORE INTO {table} ({col_list}) VALUES ({placeholders})', rows
    )
    conn.commit()
    return cur.rowcount


def _where_range(column: str, start, end) -> tuple:
    clauses, params = [], []
    if start is not None:
        clauses.append(f'"{column}" >= ?')
        params.append(str(pd.Timestamp(start)))
    if end is not None:
        clauses.append(f'"{column}" <= ?')
        params.append(str(pd.Timestamp(end)))
    return (" WHERE " + " AND ".join(clauses)) if clauses else "", params


def upsert_glucose(conn: sqlite3.Connection, df: pd.DataFrame) -> int:
    df = ensure_schema(df, GLUCOSE_COLUMNS).assign(timestamp=lambda d: d["timestamp"].astype(str))
    return _upsert(conn, "glucose_readings", df, list(GLUCOSE_COLUMNS))


def upsert_carbs(conn: sqlite3.Connection, df: pd.DataFrame) -> int:
    df = ensure_schema(df, CARB_COLUMNS).assign(timestamp=lambda d: d["timestamp"].astype(str))
    return _upsert(conn, "carb_entries", df, list(CARB_COLUMNS))


def upsert_heart_rate(conn: sqlite3.Connection, df: pd.DataFrame) -> int:
    df = ensure_schema(df, HEART_RATE_COLUMNS).assign(timestamp=lambda d: d["timestamp"].astype(str))
    return _upsert(conn, "heart_rate_samples", df, list(HEART_RATE_COLUMNS))


def upsert_activities(conn: sqlite3.Connection, df: pd.DataFrame) -> int:
    df = ensure_schema(df, ACTIVITY_COLUMNS).assign(
        start=lambda d: d["start"].astype(str), end=lambda d: d["end"].astype(str)
    )
    return _upsert(conn, "activities", df, list(ACTIVITY_COLUMNS))


def load_glucose(conn: sqlite3.Connection, start=None, end=None) -> pd.DataFrame:
    where, params = _where_range("timestamp", start, end)
    df = pd.read_sql_query(f"SELECT * FROM glucose_readings{where}", conn, params=params)
    return ensure_schema(df, GLUCOSE_COLUMNS) if not df.empty else empty_frame(GLUCOSE_COLUMNS)


def load_carbs(conn: sqlite3.Connection, start=None, end=None) -> pd.DataFrame:
    where, params = _where_range("timestamp", start, end)
    df = pd.read_sql_query(f"SELECT * FROM carb_entries{where}", conn, params=params)
    return ensure_schema(df, CARB_COLUMNS) if not df.empty else empty_frame(CARB_COLUMNS)


def load_heart_rate(conn: sqlite3.Connection, start=None, end=None) -> pd.DataFrame:
    where, params = _where_range("timestamp", start, end)
    df = pd.read_sql_query(f"SELECT * FROM heart_rate_samples{where}", conn, params=params)
    return ensure_schema(df, HEART_RATE_COLUMNS) if not df.empty else empty_frame(HEART_RATE_COLUMNS)


def load_activities(conn: sqlite3.Connection, start=None, end=None) -> pd.DataFrame:
    where, params = _where_range("start", start, end)
    df = pd.read_sql_query(f"SELECT * FROM activities{where}", conn, params=params)
    return ensure_schema(df, ACTIVITY_COLUMNS) if not df.empty else empty_frame(ACTIVITY_COLUMNS)


def latest_timestamp(conn: sqlite3.Connection, table: str, column: str, source: str):
    """Most recent `column` value stored for one source, or None if there's
    none yet - lets a live poller ask for "only what's new since last time"."""
    row = conn.execute(f'SELECT MAX("{column}") FROM {table} WHERE source = ?', (source,)).fetchone()
    return pd.Timestamp(row[0]) if row and row[0] is not None else None


def record_poll(
    conn: sqlite3.Connection,
    source: str,
    started_at: pd.Timestamp,
    finished_at: pd.Timestamp,
    status: str,
    rows_added: int | None = None,
    error_message: str | None = None,
) -> None:
    """Log one poll attempt (the heartbeat trail a `status` command reads)."""
    conn.execute(
        "INSERT INTO poll_log (source, started_at, finished_at, status, rows_added, error_message) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (source, str(started_at), str(finished_at), status, rows_added, error_message),
    )
    conn.commit()


def last_polls(conn: sqlite3.Connection, limit_per_source: int = 1) -> pd.DataFrame:
    """Most recent poll_log row(s) per source, newest first."""
    df = pd.read_sql_query(
        "SELECT * FROM poll_log ORDER BY source, id DESC", conn
    )
    if df.empty:
        return df
    return df.groupby("source", group_keys=False).head(limit_per_source).sort_values(
        "started_at", ascending=False
    ).reset_index(drop=True)
