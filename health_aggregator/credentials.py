"""Encrypted local storage for connection credentials (Garmin login,
Nightscout URL/token), so the web UI's "Connect" step only has to happen
once instead of re-entering credentials or re-setting env vars every time.

The encryption key lives in a file in the user's home directory (outside
the repo, never committed), and encrypted credential blobs live in the
same SQLite database as everything else, in a `connections` table.
"""

import json
import os
import sqlite3
import stat

from cryptography.fernet import Fernet

DEFAULT_KEY_PATH = os.path.expanduser("~/.health_aggregator/secret.key")

_SCHEMA = """
CREATE TABLE IF NOT EXISTS connections (
    source TEXT PRIMARY KEY,
    encrypted_credentials TEXT NOT NULL,
    connected_at TEXT NOT NULL,
    last_status TEXT
);
"""


def ensure_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(_SCHEMA)


def _load_or_create_key(key_path: str | None = None) -> bytes:
    key_path = key_path or DEFAULT_KEY_PATH
    if os.path.exists(key_path):
        with open(key_path, "rb") as f:
            return f.read()

    os.makedirs(os.path.dirname(key_path), exist_ok=True)
    key = Fernet.generate_key()
    with open(key_path, "wb") as f:
        f.write(key)
    try:
        os.chmod(key_path, stat.S_IRUSR | stat.S_IWUSR)  # 0600; no-op-ish on Windows
    except OSError:
        pass
    return key


def save_credentials(conn: sqlite3.Connection, source: str, credentials: dict, key_path: str | None = None) -> None:
    """Encrypt and store one source's credentials, replacing any existing entry."""
    ensure_schema(conn)
    fernet = Fernet(_load_or_create_key(key_path))
    encrypted = fernet.encrypt(json.dumps(credentials).encode()).decode()
    conn.execute(
        "INSERT INTO connections (source, encrypted_credentials, connected_at, last_status) "
        "VALUES (?, ?, datetime('now'), 'connected') "
        "ON CONFLICT(source) DO UPDATE SET encrypted_credentials = excluded.encrypted_credentials, "
        "connected_at = excluded.connected_at, last_status = 'connected'",
        (source, encrypted),
    )
    conn.commit()


def load_credentials(conn: sqlite3.Connection, source: str, key_path: str | None = None) -> dict | None:
    """Return a source's saved credentials, or None if it isn't connected."""
    ensure_schema(conn)
    row = conn.execute(
        "SELECT encrypted_credentials FROM connections WHERE source = ?", (source,)
    ).fetchone()
    if row is None:
        return None
    fernet = Fernet(_load_or_create_key(key_path))
    return json.loads(fernet.decrypt(row[0].encode()).decode())


def delete_credentials(conn: sqlite3.Connection, source: str) -> None:
    ensure_schema(conn)
    conn.execute("DELETE FROM connections WHERE source = ?", (source,))
    conn.commit()


def list_connections(conn: sqlite3.Connection) -> list:
    """Connection status for every source that's ever been connected, without
    decrypting anything - safe to show directly in the UI."""
    ensure_schema(conn)
    rows = conn.execute(
        "SELECT source, connected_at, last_status FROM connections ORDER BY source"
    ).fetchall()
    return [{"source": r[0], "connected_at": r[1], "last_status": r[2]} for r in rows]


def mark_status(conn: sqlite3.Connection, source: str, status: str) -> None:
    """Update last_status (e.g. 'connected' / 'error') without touching the
    stored credentials themselves."""
    ensure_schema(conn)
    conn.execute("UPDATE connections SET last_status = ? WHERE source = ?", (status, source))
    conn.commit()
