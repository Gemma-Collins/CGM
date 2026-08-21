"""CLI entry point: read exported files from each source and render a report.

Usage:
    python -m health_aggregator.cli \\
        --garmin-dir ./exports/garmin \\
        --cronometer-csv ./exports/cronometer_servings.csv \\
        --cgm-csv ./exports/libreview.csv \\
        --output report.html
"""

import click

from health_aggregator.importers import cgm, cronometer, garmin
from health_aggregator.merge import daily_summary, merge_all
from health_aggregator.models import ACTIVITY_COLUMNS, CARB_COLUMNS, GLUCOSE_COLUMNS, HEART_RATE_COLUMNS, empty_frame
from health_aggregator.report import build_report


@click.command()
@click.option("--garmin-dir", type=click.Path(exists=True, file_okay=False), default=None, help="Directory of .fit activity files exported from Garmin Connect.")
@click.option("--garmin-csv", type=click.Path(exists=True, dir_okay=False), default=None, help="Fallback: a simple timestamp+heart_rate CSV.")
@click.option("--cronometer-csv", type=click.Path(exists=True, dir_okay=False), default=None, help="Cronometer export CSV (Servings or Daily Summary).")
@click.option("--cgm-csv", type=click.Path(exists=True, dir_okay=False), default=None, help="CGM export CSV (LibreView, or Nightscout/xDrip+).")
@click.option("--cgm-format", type=click.Choice(["auto", "libreview", "nightscout", "generic"]), default="auto", help="Force the CGM CSV format instead of auto-detecting.")
@click.option("--freq", default="5min", show_default=True, help="Resampling interval for the merged timeline (pandas offset alias).")
@click.option("--low", "low_mg_dl", default=70.0, show_default=True, help="Lower bound of target glucose range (mg/dL).")
@click.option("--high", "high_mg_dl", default=180.0, show_default=True, help="Upper bound of target glucose range (mg/dL).")
@click.option("--output", "output_path", default="report.html", show_default=True, help="Path to write the HTML dashboard to.")
def main(garmin_dir, garmin_csv, cronometer_csv, cgm_csv, cgm_format, freq, low_mg_dl, high_mg_dl, output_path):
    """Merge Garmin, Cronometer, and CGM exports into one HTML report."""
    hr_df, activity_df = empty_frame(HEART_RATE_COLUMNS), empty_frame(ACTIVITY_COLUMNS)
    if garmin_dir:
        hr_df, activity_df = garmin.parse_fit_directory(garmin_dir)
    elif garmin_csv:
        hr_df = garmin.parse_csv(garmin_csv)

    carb_df = cronometer.parse_csv(cronometer_csv) if cronometer_csv else empty_frame(CARB_COLUMNS)

    glucose_df = empty_frame(GLUCOSE_COLUMNS)
    if cgm_csv:
        hint = None if cgm_format == "auto" else cgm_format
        glucose_df = cgm.parse_csv(cgm_csv, format_hint=hint)

    if glucose_df.empty and carb_df.empty and hr_df.empty:
        raise click.UsageError("provide at least one of --garmin-dir/--garmin-csv, --cronometer-csv, --cgm-csv")

    merged = merge_all(glucose_df, carb_df, hr_df, activity_df, freq=freq)
    daily = daily_summary(merged, low_mg_dl=low_mg_dl, high_mg_dl=high_mg_dl)
    build_report(merged, daily, output_path, low_mg_dl=low_mg_dl, high_mg_dl=high_mg_dl)
    click.echo(f"wrote {output_path} ({len(merged)} timeline rows, {len(daily)} days)")


if __name__ == "__main__":
    main()
