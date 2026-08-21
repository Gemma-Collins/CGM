from health_aggregator import db as dbmod
from tests.test_merge import _activity_df, _carb_df, _glucose_df, _hr_df


def test_upsert_and_load_glucose(tmp_path):
    conn = dbmod.connect(str(tmp_path / "health.db"))
    n = dbmod.upsert_glucose(conn, _glucose_df())
    assert n == 4

    loaded = dbmod.load_glucose(conn)
    assert len(loaded) == 4
    assert loaded["mg_dl"].max() == 160.0


def test_upsert_is_idempotent(tmp_path):
    conn = dbmod.connect(str(tmp_path / "health.db"))
    dbmod.upsert_glucose(conn, _glucose_df())
    second = dbmod.upsert_glucose(conn, _glucose_df())
    assert second == 0
    assert len(dbmod.load_glucose(conn)) == 4


def test_load_respects_date_range(tmp_path):
    conn = dbmod.connect(str(tmp_path / "health.db"))
    dbmod.upsert_glucose(conn, _glucose_df())
    subset = dbmod.load_glucose(conn, start="2026-08-10 08:06", end="2026-08-10 08:20")
    assert len(subset) == 2


def test_all_four_tables_roundtrip(tmp_path):
    conn = dbmod.connect(str(tmp_path / "health.db"))
    dbmod.upsert_glucose(conn, _glucose_df())
    dbmod.upsert_carbs(conn, _carb_df())
    dbmod.upsert_heart_rate(conn, _hr_df())
    dbmod.upsert_activities(conn, _activity_df())

    assert len(dbmod.load_glucose(conn)) == 4
    assert len(dbmod.load_carbs(conn)) == 1
    assert len(dbmod.load_heart_rate(conn)) == 2
    activities = dbmod.load_activities(conn)
    assert len(activities) == 1
    assert activities.iloc[0]["activity_type"] == "running"


def test_reopening_db_persists_data(tmp_path):
    path = str(tmp_path / "health.db")
    conn = dbmod.connect(path)
    dbmod.upsert_glucose(conn, _glucose_df())
    conn.close()

    reopened = dbmod.connect(path)
    assert len(dbmod.load_glucose(reopened)) == 4
