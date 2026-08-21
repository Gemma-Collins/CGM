import os

from health_aggregator.importers import cgm

FIXTURES = os.path.join(os.path.dirname(__file__), "fixtures")


def test_detect_format_libreview():
    columns = ["Device Timestamp", "Record Type", "Historic Glucose mg/dL", "Scan Glucose mg/dL"]
    assert cgm.detect_format(columns) == "libreview"


def test_detect_format_nightscout():
    assert cgm.detect_format(["dateString", "sgv", "direction"]) == "nightscout"


def test_parse_libreview_csv_skips_banner_and_merges_historic_and_scan():
    df = cgm.parse_csv(os.path.join(FIXTURES, "libreview_sample.csv"))
    assert len(df) == 9
    assert set(df["reading_type"]) == {"historic", "scan"}
    scan_rows = df[df["reading_type"] == "scan"]
    assert len(scan_rows) == 1
    assert scan_rows.iloc[0]["mg_dl"] == 101
    assert df["mg_dl"].max() == 162


def test_parse_nightscout_csv():
    df = cgm.parse_csv(os.path.join(FIXTURES, "nightscout_sample.csv"))
    assert len(df) == 5
    assert set(df["source"]) == {"nightscout"}
    assert df["mg_dl"].iloc[0] == 90


def test_parse_generic_csv(tmp_path):
    path = tmp_path / "generic.csv"
    path.write_text("time,glucose_value\n2026-08-10 07:00:00,95\n2026-08-10 07:05:00,100\n")
    df = cgm.parse_csv(str(path))
    assert len(df) == 2
    assert set(df["source"]) == {"cgm_generic"}
