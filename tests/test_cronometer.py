import os

from health_aggregator.importers import cronometer

FIXTURES = os.path.join(os.path.dirname(__file__), "fixtures")


def test_parse_servings_csv():
    df = cronometer.parse_csv(os.path.join(FIXTURES, "cronometer_servings.csv"))
    assert len(df) == 6
    assert set(df["source"]) == {"cronometer"}
    breakfast = df[df["food_name"] == "Oatmeal"].iloc[0]
    assert breakfast["carbs_g"] == 27
    assert str(breakfast["timestamp"]) == "2026-08-10 08:05:00"


def test_parse_daily_summary_without_time_column(tmp_path):
    path = tmp_path / "daily.csv"
    path.write_text("Date,Energy (kcal),Carbs (g)\n2026-08-10,2100,220\n2026-08-11,1950,180\n")
    df = cronometer.parse_csv(str(path))
    assert len(df) == 2
    assert df.iloc[0]["timestamp"].hour == 12
    assert df.iloc[0]["carbs_g"] == 220
