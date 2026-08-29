from health_aggregator import credentials as credmod
from health_aggregator import db as dbmod


def test_save_and_load_credentials_roundtrip(tmp_path):
    conn = dbmod.connect(str(tmp_path / "health.db"))
    key_path = str(tmp_path / "secret.key")

    credmod.save_credentials(conn, "garmin", {"email": "a@b.com", "password": "hunter2"}, key_path=key_path)
    loaded = credmod.load_credentials(conn, "garmin", key_path=key_path)

    assert loaded == {"email": "a@b.com", "password": "hunter2"}


def test_credentials_are_encrypted_at_rest(tmp_path):
    conn = dbmod.connect(str(tmp_path / "health.db"))
    key_path = str(tmp_path / "secret.key")
    credmod.save_credentials(conn, "garmin", {"email": "a@b.com", "password": "hunter2"}, key_path=key_path)

    row = conn.execute("SELECT encrypted_credentials FROM connections WHERE source = 'garmin'").fetchone()
    assert "hunter2" not in row[0]
    assert "a@b.com" not in row[0]


def test_load_credentials_returns_none_when_not_connected(tmp_path):
    conn = dbmod.connect(str(tmp_path / "health.db"))
    assert credmod.load_credentials(conn, "garmin", key_path=str(tmp_path / "secret.key")) is None


def test_save_credentials_overwrites_existing(tmp_path):
    conn = dbmod.connect(str(tmp_path / "health.db"))
    key_path = str(tmp_path / "secret.key")
    credmod.save_credentials(conn, "garmin", {"email": "old@b.com", "password": "x"}, key_path=key_path)
    credmod.save_credentials(conn, "garmin", {"email": "new@b.com", "password": "y"}, key_path=key_path)

    loaded = credmod.load_credentials(conn, "garmin", key_path=key_path)
    assert loaded["email"] == "new@b.com"
    assert len(conn.execute("SELECT * FROM connections").fetchall()) == 1


def test_delete_credentials(tmp_path):
    conn = dbmod.connect(str(tmp_path / "health.db"))
    key_path = str(tmp_path / "secret.key")
    credmod.save_credentials(conn, "nightscout", {"url": "https://x"}, key_path=key_path)

    credmod.delete_credentials(conn, "nightscout")

    assert credmod.load_credentials(conn, "nightscout", key_path=key_path) is None
    assert credmod.list_connections(conn) == []


def test_list_connections_does_not_expose_secrets(tmp_path):
    conn = dbmod.connect(str(tmp_path / "health.db"))
    key_path = str(tmp_path / "secret.key")
    credmod.save_credentials(conn, "garmin", {"email": "a@b.com", "password": "hunter2"}, key_path=key_path)

    rows = credmod.list_connections(conn)

    assert len(rows) == 1
    assert rows[0]["source"] == "garmin"
    assert "hunter2" not in str(rows[0])
    assert "password" not in rows[0]


def test_mark_status_updates_without_touching_credentials(tmp_path):
    conn = dbmod.connect(str(tmp_path / "health.db"))
    key_path = str(tmp_path / "secret.key")
    credmod.save_credentials(conn, "garmin", {"email": "a@b.com", "password": "hunter2"}, key_path=key_path)

    credmod.mark_status(conn, "garmin", "error")

    rows = credmod.list_connections(conn)
    assert rows[0]["last_status"] == "error"
    assert credmod.load_credentials(conn, "garmin", key_path=key_path)["password"] == "hunter2"
