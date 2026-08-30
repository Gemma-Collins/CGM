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


def test_day_view_defaults_to_today_with_no_data(tmp_path, monkeypatch):
    client = _client(tmp_path / "health.db", monkeypatch)
    resp = client.get("/day")
    assert resp.status_code == 200
    assert b"No activities logged this day" in resp.data
    assert b"No heart rate data this day" in resp.data
    assert b"No calendar events this day" in resp.data


def test_day_view_shows_activity_and_heart_rate_for_selected_date(tmp_path, monkeypatch):
    import pandas as pd

    from health_aggregator.models import ACTIVITY_COLUMNS, HEART_RATE_COLUMNS, ensure_schema

    db_path = tmp_path / "health.db"
    conn = dbmod.connect(str(db_path))
    dbmod.upsert_activities(
        conn,
        ensure_schema(
            pd.DataFrame(
                {
                    "start": pd.to_datetime(["2026-08-10 08:00"]),
                    "end": pd.to_datetime(["2026-08-10 08:30"]),
                    "activity_type": ["running"],
                    "avg_hr": [140.0],
                    "max_hr": [160.0],
                    "calories_kcal": [300.0],
                    "distance_m": [5000.0],
                    "steps": [6000.0],
                    "source": ["garmin_fit"],
                }
            ),
            ACTIVITY_COLUMNS,
        ),
    )
    dbmod.upsert_heart_rate(
        conn,
        ensure_schema(
            pd.DataFrame(
                {
                    "timestamp": pd.to_datetime(["2026-08-10 08:05", "2026-08-10 08:10"]),
                    "bpm": [140.0, 150.0],
                    "source": ["garmin_fit"] * 2,
                }
            ),
            HEART_RATE_COLUMNS,
        ),
    )
    conn.close()

    client = _client(db_path, monkeypatch)
    resp = client.get("/day?date=2026-08-10")

    assert resp.status_code == 200
    assert b"running" in resp.data
    assert b"min bpm" in resp.data
    assert b"140.0" in resp.data  # min bpm value


def test_day_view_month_grid_marks_days_with_data(tmp_path, monkeypatch):
    db_path = tmp_path / "health.db"
    conn = dbmod.connect(str(db_path))
    dbmod.upsert_glucose(conn, _glucose_df())  # 2026-08-10
    conn.close()

    client = _client(db_path, monkeypatch)
    resp = client.get("/day?date=2026-08-15")  # different day, same month

    assert resp.status_code == 200
    assert b"August 2026" in resp.data


def test_day_view_shows_calendar_events_with_toggle_per_calendar(tmp_path, monkeypatch):
    import pandas as pd

    from health_aggregator.models import CALENDAR_COLUMNS, ensure_schema

    db_path = tmp_path / "health.db"
    conn = dbmod.connect(str(db_path))
    dbmod.upsert_calendar_events(
        conn,
        ensure_schema(
            pd.DataFrame(
                {
                    "start": pd.to_datetime(["2026-08-10 07:00", "2026-08-10 09:00"]),
                    "end": pd.to_datetime(["2026-08-10 08:00", "2026-08-10 09:30"]),
                    "title": ["Gym", "Standup"],
                    "event_type": ["activity", "other"],
                    "calendar_name": ["Personal", "Work"],
                    "source": ["google_calendar"] * 2,
                }
            ),
            CALENDAR_COLUMNS,
        ),
    )
    conn.close()

    client = _client(db_path, monkeypatch)
    resp = client.get("/day?date=2026-08-10")

    assert resp.status_code == 200
    assert b"Gym" in resp.data
    assert b"Standup" in resp.data
    assert b'toggleCalendar(\'Personal\'' in resp.data
    assert b'toggleCalendar(\'Work\'' in resp.data
    assert b"toggleTrace('cal:Personal'" in resp.data
    assert b"toggleTrace('cal:Work'" in resp.data


def test_day_view_renders_chart_with_glucose_and_calendar_markers(tmp_path, monkeypatch):
    import pandas as pd

    from health_aggregator.models import CALENDAR_COLUMNS, ensure_schema

    db_path = tmp_path / "health.db"
    conn = dbmod.connect(str(db_path))
    dbmod.upsert_glucose(conn, _glucose_df())  # 2026-08-10
    dbmod.upsert_calendar_events(
        conn,
        ensure_schema(
            pd.DataFrame(
                {
                    "start": pd.to_datetime(["2026-08-10 07:00"]),
                    "end": pd.to_datetime(["2026-08-10 07:30"]),
                    "title": ["Morning run"],
                    "event_type": ["activity"],
                    "calendar_name": ["Personal"],
                    "source": ["google_calendar"],
                }
            ),
            CALENDAR_COLUMNS,
        ),
    )
    conn.close()

    client = _client(db_path, monkeypatch)
    resp = client.get("/day?date=2026-08-10")

    assert resp.status_code == 200
    assert b'id="day-chart"' in resp.data
    assert b"Personal events" in resp.data
    assert b"No CGM, heart rate, or activity data this day" not in resp.data
    # the unit toggle needs real glucose values embedded as a plain JS array -
    # Plotly's own embedded trace data isn't always a plain array (see
    # ORIGINAL_GLUCOSE_MGDL in day.html), so this must never be the "no data" default
    assert b"var ORIGINAL_GLUCOSE_MGDL = [];" not in resp.data
    assert b"90.0" in resp.data  # a value from _glucose_df()


def test_day_view_glucose_tile_shows_stats_and_unit_selector(tmp_path, monkeypatch):
    db_path = tmp_path / "health.db"
    conn = dbmod.connect(str(db_path))
    dbmod.upsert_glucose(conn, _glucose_df())  # 2026-08-10, values 90-160
    conn.close()

    client = _client(db_path, monkeypatch)
    resp = client.get("/day?date=2026-08-10")

    assert resp.status_code == 200
    assert b"setGlucoseUnit(this.value)" in resp.data
    assert b"mmol/L" in resp.data
    assert b"time in range" in resp.data


def test_day_view_no_chart_when_only_calendar_events_exist(tmp_path, monkeypatch):
    """Calendar-only days shouldn't render an empty/broken chart."""
    import pandas as pd

    from health_aggregator.models import CALENDAR_COLUMNS, ensure_schema

    db_path = tmp_path / "health.db"
    conn = dbmod.connect(str(db_path))
    dbmod.upsert_calendar_events(
        conn,
        ensure_schema(
            pd.DataFrame(
                {
                    "start": pd.to_datetime(["2026-08-10 07:00"]),
                    "end": pd.to_datetime(["2026-08-10 07:30"]),
                    "title": ["Morning run"],
                    "event_type": ["activity"],
                    "calendar_name": ["Personal"],
                    "source": ["google_calendar"],
                }
            ),
            CALENDAR_COLUMNS,
        ),
    )
    conn.close()

    client = _client(db_path, monkeypatch)
    resp = client.get("/day?date=2026-08-10")

    assert resp.status_code == 200
    assert b"No CGM, heart rate, or activity data this day" in resp.data


def test_day_view_invalid_date_falls_back_to_today(tmp_path, monkeypatch):
    client = _client(tmp_path / "health.db", monkeypatch)
    resp = client.get("/day?date=not-a-date")
    assert resp.status_code == 200


def test_connections_page_shows_calendar_cli_instructions_when_not_connected(tmp_path, monkeypatch):
    monkeypatch.setattr("health_aggregator.webapp.app.calendar_live.DEFAULT_TOKEN_PATH", str(tmp_path / "no_token.json"))
    client = _client(tmp_path / "health.db", monkeypatch)
    resp = client.get("/connections")
    assert b"connect-calendar" in resp.data


def test_connections_page_shows_calendar_connected_when_token_exists(tmp_path, monkeypatch):
    token_path = tmp_path / "token.json"
    token_path.write_text("{}")
    monkeypatch.setattr("health_aggregator.webapp.app.calendar_live.DEFAULT_TOKEN_PATH", str(token_path))

    client = _client(tmp_path / "health.db", monkeypatch)
    resp = client.get("/connections")

    assert b"Status: connected" in resp.data


def test_upload_nutrition_pdf_success(tmp_path, monkeypatch):
    import io

    import pandas as pd

    from health_aggregator.models import CARB_COLUMNS, ensure_schema

    fake_df = ensure_schema(
        pd.DataFrame(
            {
                "timestamp": pd.to_datetime(["2026-08-15 12:00"]),
                "food_name": ["Salad"],
                "carbs_g": [12.0],
                "calories_kcal": [320.0],
                "source": ["nutrition_pdf"],
            }
        ),
        CARB_COLUMNS,
    )
    monkeypatch.setattr("health_aggregator.webapp.app.nutrition_pdf.parse_pdf", lambda path, date=None: fake_df)

    db_path = tmp_path / "health.db"
    client = _client(db_path, monkeypatch)
    resp = client.post(
        "/uploads/nutrition-pdf",
        data={"pdf_file": (io.BytesIO(b"%PDF-1.4 fake"), "meal.pdf")},
        content_type="multipart/form-data",
        follow_redirects=True,
    )

    assert resp.status_code == 200
    assert b"Extracted 1 new nutrition entry" in resp.data
    conn = dbmod.connect(str(db_path))
    assert len(dbmod.load_carbs(conn)) == 1


def test_upload_nutrition_pdf_without_file_shows_error(tmp_path, monkeypatch):
    client = _client(tmp_path / "health.db", monkeypatch)
    resp = client.post("/uploads/nutrition-pdf", data={}, content_type="multipart/form-data", follow_redirects=True)
    assert b"No PDF selected" in resp.data


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
