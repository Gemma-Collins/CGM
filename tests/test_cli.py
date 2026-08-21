import os

from click.testing import CliRunner

from health_aggregator.cli import main

FIXTURES = os.path.join(os.path.dirname(__file__), "fixtures")


def test_cli_end_to_end(tmp_path):
    output = tmp_path / "report.html"
    runner = CliRunner()
    result = runner.invoke(
        main,
        [
            "--garmin-csv", os.path.join(FIXTURES, "garmin_hr_sample.csv"),
            "--cronometer-csv", os.path.join(FIXTURES, "cronometer_servings.csv"),
            "--cgm-csv", os.path.join(FIXTURES, "libreview_sample.csv"),
            "--output", str(output),
        ],
    )

    assert result.exit_code == 0, result.output
    assert output.exists()
    assert "wrote" in result.output


def test_cli_requires_at_least_one_source():
    runner = CliRunner()
    result = runner.invoke(main, [])
    assert result.exit_code != 0
