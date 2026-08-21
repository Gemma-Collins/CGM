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
