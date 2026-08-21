import os

from click.testing import CliRunner

from health_aggregator.cli import main

FIXTURES = os.path.join(os.path.dirname(__file__), "fixtures")


def test_cli_ingest_then_report(tmp_path):
    db_path = tmp_path / "health.db"
    output = tmp_path / "report.html"
    runner = CliRunner()

    ingest_result = runner.invoke(
        main,
        [
            "ingest",
            "--db", str(db_path),
            "--garmin-csv", os.path.join(FIXTURES, "garmin_hr_sample.csv"),
            "--cronometer-csv", os.path.join(FIXTURES, "cronometer_servings.csv"),
            "--cgm-csv", os.path.join(FIXTURES, "libreview_sample.csv"),
        ],
    )
    assert ingest_result.exit_code == 0, ingest_result.output
    assert db_path.exists()

    report_result = runner.invoke(
        main, ["report", "--db", str(db_path), "--output", str(output)]
    )
    assert report_result.exit_code == 0, report_result.output
    assert output.exists()
    assert "wrote" in report_result.output


def test_cli_ingest_requires_at_least_one_source():
    runner = CliRunner()
    result = runner.invoke(main, ["ingest"])
    assert result.exit_code != 0


def test_cli_report_fails_without_prior_ingest(tmp_path):
    runner = CliRunner()
    result = runner.invoke(main, ["report", "--db", str(tmp_path / "empty.db")])
    assert result.exit_code != 0


def test_cli_status_with_no_polls_and_no_data(tmp_path):
    runner = CliRunner()
    result = runner.invoke(main, ["status", "--db", str(tmp_path / "empty.db")])
    assert result.exit_code == 0
    assert "no polls recorded yet" in result.output
    assert "glucose: 0" in result.output


def test_cli_poll_success_records_heartbeat(tmp_path, monkeypatch):
    db_path = tmp_path / "health.db"
    monkeypatch.setattr(
        "health_aggregator.cli.garmin_live.poll_once",
        lambda conn, tokenstore, days_back: {"heart_rate": 5, "activities": 1},
    )
    runner = CliRunner()
    result = runner.invoke(main, ["poll", "--db", str(db_path)])
    assert result.exit_code == 0, result.output
    assert "heart rate +5" in result.output

    status = runner.invoke(main, ["status", "--db", str(db_path)])
    assert "garmin_live: success" in status.output
    assert "6 row(s) added" in status.output


def test_cli_poll_failure_records_heartbeat_and_exits_nonzero(tmp_path, monkeypatch):
    db_path = tmp_path / "health.db"

    def _boom(conn, tokenstore, days_back):
        raise RuntimeError("401 unauthorized")

    monkeypatch.setattr("health_aggregator.cli.garmin_live.poll_once", _boom)
    runner = CliRunner()
    result = runner.invoke(main, ["poll", "--db", str(db_path)])
    assert result.exit_code != 0

    status = runner.invoke(main, ["status", "--db", str(db_path)])
    assert "garmin_live: error" in status.output
    assert "401 unauthorized" in status.output


def test_cli_poll_cgm_success_records_heartbeat(tmp_path, monkeypatch):
    db_path = tmp_path / "health.db"
    monkeypatch.setattr(
        "health_aggregator.cli.nightscout_live.poll_once",
        lambda conn, base_url, count: {"glucose": 4},
    )
    runner = CliRunner()
    result = runner.invoke(main, ["poll-cgm", "--db", str(db_path)])
    assert result.exit_code == 0, result.output
    assert "glucose +4" in result.output

    status = runner.invoke(main, ["status", "--db", str(db_path)])
    assert "nightscout_live: success" in status.output
    assert "4 row(s) added" in status.output


def test_cli_poll_cgm_failure_records_heartbeat_and_exits_nonzero(tmp_path, monkeypatch):
    db_path = tmp_path / "health.db"

    def _boom(conn, base_url, count):
        raise RuntimeError("NIGHTSCOUT_URL is required")

    monkeypatch.setattr("health_aggregator.cli.nightscout_live.poll_once", _boom)
    runner = CliRunner()
    result = runner.invoke(main, ["poll-cgm", "--db", str(db_path)])
    assert result.exit_code != 0

    status = runner.invoke(main, ["status", "--db", str(db_path)])
    assert "nightscout_live: error" in status.output


def test_cli_ingest_twice_does_not_duplicate(tmp_path):
    db_path = tmp_path / "health.db"
    runner = CliRunner()
    args = [
        "ingest",
        "--db", str(db_path),
        "--cgm-csv", os.path.join(FIXTURES, "libreview_sample.csv"),
    ]
    runner.invoke(main, args)
    second = runner.invoke(main, args)
    assert second.exit_code == 0
    assert "0 new row(s)" in second.output
