from health_aggregator import credentials as credmod
from health_aggregator import db as dbmod
from health_aggregator.webapp.app import create_app
from tests.test_merge import _carb_df, _glucose_df


def _client(db_path, monkeypatch):
    # Avoid a real background poll loop spinning up during tests.
    monkeypatch.setattr(
        "health_aggregator.webapp.app.threading.Thread",
        lambda target, args, daemon: type("FakeThread", (), {"start": lambda self: None, "is_alive": lambda self: True})(),
    )
    app = create_app(db_path=str(db_path))
    app.config["TESTING"] = True
    return app.test_client()


def test_dashboard_shows_empty_state_with_no_data(tmp_path, monkeypatch):
    client = _client(tmp_path / "health.db", monkeypatch)
    resp = client.get("/")
    assert resp.status_code == 200
    assert b"No data yet" in resp.data


def test_dashboard_renders_chart_when_data_exists(tmp_path, monkeypatch):
    db_path = tmp_path / "health.db"
    conn = dbmod.connect(str(db_path))
    dbmod.upsert_glucose(conn, _glucose_df())
    dbmod.upsert_carbs(conn, _carb_df())
    conn.close()

    client = _client(db_path, monkeypatch)
    resp = client.get("/")

    assert resp.status_code == 200
    assert b"Daily summary" in resp.data
    assert b"plotly" in resp.data.lower()


def test_connections_page_shows_not_connected_by_default(tmp_path, monkeypatch):
    client = _client(tmp_path / "health.db", monkeypatch)
    resp = client.get("/connections")
    assert resp.status_code == 200
    assert b"Garmin email" in resp.data  # the connect form, not a status pill


def test_connect_garmin_success_saves_credentials(tmp_path, monkeypatch):
    db_path = tmp_path / "health.db"
    monkeypatch.setattr("health_aggregator.webapp.app.garmin_live.login", lambda email, password: object())
    monkeypatch.setattr("health_aggregator.credentials.DEFAULT_KEY_PATH", str(tmp_path / "secret.key"))

    client = _client(db_path, monkeypatch)
    resp = client.post(
        "/connections/garmin/connect", data={"email": "a@b.com", "password": "hunter2"}, follow_redirects=True
    )

    assert resp.status_code == 200
    assert b"Garmin connected" in resp.data
    conn = dbmod.connect(str(db_path))
    assert credmod.load_credentials(conn, "garmin", key_path=str(tmp_path / "secret.key")) == {
        "email": "a@b.com",
        "password": "hunter2",
    }


def test_connect_garmin_failure_does_not_save_credentials(tmp_path, monkeypatch):
    db_path = tmp_path / "health.db"

    def _boom(email, password):
        raise RuntimeError("bad login")

    monkeypatch.setattr("health_aggregator.webapp.app.garmin_live.login", _boom)
    monkeypatch.setattr("health_aggregator.credentials.DEFAULT_KEY_PATH", str(tmp_path / "secret.key"))

    client = _client(db_path, monkeypatch)
    resp = client.post(
        "/connections/garmin/connect", data={"email": "a@b.com", "password": "wrong"}, follow_redirects=True
    )

    assert b"Couldn&#39;t connect to Garmin" in resp.data or b"Couldn" in resp.data
    conn = dbmod.connect(str(db_path))
    assert credmod.load_credentials(conn, "garmin", key_path=str(tmp_path / "secret.key")) is None


def test_disconnect_garmin_removes_credentials(tmp_path, monkeypatch):
    db_path = tmp_path / "health.db"
    key_path = str(tmp_path / "secret.key")
    conn = dbmod.connect(str(db_path))
    credmod.save_credentials(conn, "garmin", {"email": "a@b.com", "password": "x"}, key_path=key_path)
    conn.close()

    client = _client(db_path, monkeypatch)
    resp = client.post("/connections/garmin/disconnect", follow_redirects=True)

    assert b"Garmin disconnected" in resp.data
    conn = dbmod.connect(str(db_path))
    assert credmod.load_credentials(conn, "garmin", key_path=key_path) is None


def test_connect_nightscout_success_saves_credentials(tmp_path, monkeypatch):
    db_path = tmp_path / "health.db"
    monkeypatch.setattr(
        "health_aggregator.webapp.app.nightscout_live.fetch_entries",
        lambda url, token=None, api_secret=None, count=1: [],
    )
    monkeypatch.setattr("health_aggregator.credentials.DEFAULT_KEY_PATH", str(tmp_path / "secret.key"))

    client = _client(db_path, monkeypatch)
    resp = client.post(
        "/connections/nightscout/connect",
        data={"url": "https://example.com", "token": "tok", "api_secret": ""},
        follow_redirects=True,
    )

    assert b"CGM (Nightscout) connected" in resp.data
    conn = dbmod.connect(str(db_path))
    creds = credmod.load_credentials(conn, "nightscout", key_path=str(tmp_path / "secret.key"))
    assert creds["url"] == "https://example.com"
    assert creds["token"] == "tok"
