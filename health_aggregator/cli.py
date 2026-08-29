"""CLI entry point.

Two steps, so a future scheduler can drive the first one repeatedly while
you view reports whenever you like:

    python -m health_aggregator.cli ingest --garmin-dir ./exports/garmin \\
        --cronometer-csv ./exports/cronometer_servings.csv \\
        --cgm-csv ./exports/libreview.csv

    python -m health_aggregator.cli report --output report.html
"""

import click
import pandas as pd

from health_aggregator import db as dbmod
from health_aggregator import scheduler
from health_aggregator.importers import cgm, cronometer, garmin
from health_aggregator.live import garmin_live, nightscout_live
from health_aggregator.merge import daily_summary, merge_all
from health_aggregator.report import build_report

_DB_OPTION = click.option(
    "--db", "db_path", default="health_data.db", show_default=True,
    help="SQLite file that import history accumulates in.",
)


@click.group()
def main():
    """Merge Garmin, Cronometer, and CGM exports into a local database and HTML report."""


@main.command()
@_DB_OPTION
@click.option("--garmin-dir", type=click.Path(exists=True, file_okay=False), default=None, help="Directory of .fit activity files exported from Garmin Connect.")
@click.option("--garmin-csv", type=click.Path(exists=True, dir_okay=False), default=None, help="Fallback: a simple timestamp+heart_rate CSV.")
@click.option("--cronometer-csv", type=click.Path(exists=True, dir_okay=False), default=None, help="Cronometer export CSV (Servings or Daily Summary).")
@click.option("--cgm-csv", type=click.Path(exists=True, dir_okay=False), default=None, help="CGM export CSV (LibreView, or Nightscout/xDrip+).")
@click.option("--cgm-format", type=click.Choice(["auto", "libreview", "nightscout", "generic"]), default="auto", help="Force the CGM CSV format instead of auto-detecting.")
def ingest(db_path, garmin_dir, garmin_csv, cronometer_csv, cgm_csv, cgm_format):
    """Parse export files and upsert them into the local database (re-running with
    overlapping files is safe - duplicates are skipped)."""
    conn = dbmod.connect(db_path)
    counts = {}

    if garmin_dir:
        hr_df, activity_df = garmin.parse_fit_directory(garmin_dir)
        counts["heart rate"] = dbmod.upsert_heart_rate(conn, hr_df)
        counts["activities"] = dbmod.upsert_activities(conn, activity_df)
    elif garmin_csv:
        hr_df = garmin.parse_csv(garmin_csv)
        counts["heart rate"] = dbmod.upsert_heart_rate(conn, hr_df)

    if cronometer_csv:
        carb_df = cronometer.parse_csv(cronometer_csv)
        counts["carbs"] = dbmod.upsert_carbs(conn, carb_df)

    if cgm_csv:
        hint = None if cgm_format == "auto" else cgm_format
        glucose_df = cgm.parse_csv(cgm_csv, format_hint=hint)
        counts["glucose"] = dbmod.upsert_glucose(conn, glucose_df)

    conn.close()

    if not counts:
        raise click.UsageError("provide at least one of --garmin-dir/--garmin-csv, --cronometer-csv, --cgm-csv")

    for name, n in counts.items():
        click.echo(f"{name}: {n} new row(s) added to {db_path}")


@main.command()
@_DB_OPTION
@click.option("--start", default=None, help="Only include data from this date/time onward (e.g. 2026-08-01).")
@click.option("--end", default=None, help="Only include data up to this date/time.")
@click.option("--freq", default="5min", show_default=True, help="Resampling interval for the merged timeline (pandas offset alias).")
@click.option("--low", "low_mg_dl", default=70.0, show_default=True, help="Lower bound of target glucose range (mg/dL).")
@click.option("--high", "high_mg_dl", default=180.0, show_default=True, help="Upper bound of target glucose range (mg/dL).")
@click.option("--output", "output_path", default="report.html", show_default=True, help="Path to write the HTML dashboard to.")
def report(db_path, start, end, freq, low_mg_dl, high_mg_dl, output_path):
    """Build the HTML dashboard from everything currently in the database."""
    conn = dbmod.connect(db_path)
    glucose_df = dbmod.load_glucose(conn, start, end)
    carb_df = dbmod.load_carbs(conn, start, end)
    hr_df = dbmod.load_heart_rate(conn, start, end)
    activity_df = dbmod.load_activities(conn, start, end)
    insulin_df = dbmod.load_insulin(conn, start, end)
    conn.close()

    if glucose_df.empty and carb_df.empty and hr_df.empty and insulin_df.empty:
        raise click.UsageError(f"no data found in {db_path} for that range - run 'ingest' first")

    merged = merge_all(glucose_df, carb_df, hr_df, activity_df, insulin_df, freq=freq)
    daily = daily_summary(merged, low_mg_dl=low_mg_dl, high_mg_dl=high_mg_dl)
    build_report(merged, daily, output_path, low_mg_dl=low_mg_dl, high_mg_dl=high_mg_dl)
    click.echo(f"wrote {output_path} ({len(merged)} timeline rows, {len(daily)} days)")


def _run_garmin_live_poll(db_path: str, tokenstore: str, days_back: int) -> dict:
    """One live-Garmin poll: fetch, upsert, and record a poll_log heartbeat row."""
    conn = dbmod.connect(db_path)
    started = pd.Timestamp.now()
    try:
        counts = garmin_live.poll_once(conn, tokenstore=tokenstore, days_back=days_back)
        dbmod.record_poll(
            conn, "garmin_live", started, pd.Timestamp.now(), "success",
            rows_added=sum(counts.values()),
        )
        return counts
    except Exception as exc:
        dbmod.record_poll(
            conn, "garmin_live", started, pd.Timestamp.now(), "error",
            rows_added=0, error_message=str(exc),
        )
        raise
    finally:
        conn.close()


@main.command()
@_DB_OPTION
@click.option("--tokenstore", default=garmin_live.DEFAULT_TOKENSTORE, show_default=True, help="Where the cached Garmin session token is stored, so you're not re-prompted for a password every poll.")
@click.option("--days-back", default=1, show_default=True, help="How many days of heart rate/activities to fetch.")
def poll(db_path, tokenstore, days_back):
    """One-off live Garmin fetch: logs in and pulls recent heart rate + activities
    into the database. Reads credentials from GARMIN_EMAIL / GARMIN_PASSWORD."""
    try:
        counts = _run_garmin_live_poll(db_path, tokenstore, days_back)
    except Exception as exc:
        raise click.ClickException(f"garmin live poll failed: {exc}")
    click.echo(f"garmin_live: heart rate +{counts['heart_rate']}, activities +{counts['activities']}")


@main.command()
@_DB_OPTION
@click.option("--tokenstore", default=garmin_live.DEFAULT_TOKENSTORE, show_default=True, help="Where the cached Garmin session token is stored.")
@click.option("--days-back", default=1, show_default=True, help="How many days of heart rate/activities to fetch per poll.")
@click.option("--min-minutes", default=15.0, show_default=True, help="Minimum minutes between polls.")
@click.option("--max-minutes", default=30.0, show_default=True, help="Maximum minutes between polls (the interval is randomized between min and max each time).")
def schedule(db_path, tokenstore, days_back, min_minutes, max_minutes):
    """Run the live Garmin poll forever, on a jittered interval, until you stop it (Ctrl+C)."""

    def do_poll():
        try:
            counts = _run_garmin_live_poll(db_path, tokenstore, days_back)
            click.echo(f"{pd.Timestamp.now()}: poll ok, +{sum(counts.values())} rows")
        except Exception as exc:
            click.echo(f"{pd.Timestamp.now()}: poll FAILED: {exc}")

    click.echo(f"polling every {min_minutes}-{max_minutes} min (jittered); Ctrl+C to stop")
    scheduler.run_forever(do_poll, min_minutes * 60, max_minutes * 60)


def _run_nightscout_live_poll(db_path: str, nightscout_url: str | None, count: int) -> dict:
    """One live-Nightscout poll: fetch, upsert, and record a poll_log heartbeat row."""
    conn = dbmod.connect(db_path)
    started = pd.Timestamp.now()
    try:
        counts = nightscout_live.poll_once(conn, base_url=nightscout_url, count=count)
        dbmod.record_poll(
            conn, "nightscout_live", started, pd.Timestamp.now(), "success",
            rows_added=sum(counts.values()),
        )
        return counts
    except Exception as exc:
        dbmod.record_poll(
            conn, "nightscout_live", started, pd.Timestamp.now(), "error",
            rows_added=0, error_message=str(exc),
        )
        raise
    finally:
        conn.close()


@main.command("poll-cgm")
@_DB_OPTION
@click.option("--nightscout-url", default=None, help="Nightscout site base URL, e.g. https://mysite.up.railway.app. Falls back to the NIGHTSCOUT_URL env var.")
@click.option("--count", default=nightscout_live.DEFAULT_COUNT, show_default=True, help="Max entries to fetch per poll (only entries newer than what's already stored are added).")
def poll_cgm(db_path, nightscout_url, count):
    """One-off live CGM fetch from a Nightscout site (e.g. xDrip+/MiaoMiao
    uploading there). Reads auth from NIGHTSCOUT_TOKEN or NIGHTSCOUT_API_SECRET."""
    try:
        counts = _run_nightscout_live_poll(db_path, nightscout_url, count)
    except Exception as exc:
        raise click.ClickException(f"nightscout live poll failed: {exc}")
    click.echo(f"nightscout_live: glucose +{counts['glucose']}, insulin +{counts['insulin']}")


@main.command("schedule-cgm")
@_DB_OPTION
@click.option("--nightscout-url", default=None, help="Nightscout site base URL. Falls back to the NIGHTSCOUT_URL env var.")
@click.option("--count", default=nightscout_live.DEFAULT_COUNT, show_default=True, help="Max entries to fetch per poll.")
@click.option("--min-minutes", default=5.0, show_default=True, help="Minimum minutes between polls (CGM readings arrive every 1-5 min, so this can run tighter than the Garmin schedule).")
@click.option("--max-minutes", default=10.0, show_default=True, help="Maximum minutes between polls (jittered).")
def schedule_cgm(db_path, nightscout_url, count, min_minutes, max_minutes):
    """Run the live Nightscout poll forever, on a jittered interval, until you stop it (Ctrl+C)."""

    def do_poll():
        try:
            counts = _run_nightscout_live_poll(db_path, nightscout_url, count)
            click.echo(f"{pd.Timestamp.now()}: poll ok, glucose +{counts['glucose']}, insulin +{counts['insulin']}")
        except Exception as exc:
            click.echo(f"{pd.Timestamp.now()}: poll FAILED: {exc}")

    click.echo(f"polling every {min_minutes}-{max_minutes} min (jittered); Ctrl+C to stop")
    scheduler.run_forever(do_poll, min_minutes * 60, max_minutes * 60)


@main.command()
@_DB_OPTION
def status(db_path):
    """Show the poll heartbeat (is the live tracker actually running) and how
    much data is currently stored."""
    conn = dbmod.connect(db_path)
    polls = dbmod.last_polls(conn)

    if polls.empty:
        click.echo("no polls recorded yet - run 'poll' or 'schedule' at least once")
    else:
        now = pd.Timestamp.now()
        for _, row in polls.iterrows():
            minutes_ago = int((now - pd.Timestamp(row["finished_at"])).total_seconds() // 60)
            line = f"{row['source']}: {row['status']}, {minutes_ago} min ago, {row['rows_added']} row(s) added"
            if row["status"] == "error" and row["error_message"]:
                line += f" ({row['error_message']})"
            click.echo(line)

    click.echo("")
    click.echo("stored rows:")
    click.echo(f"  glucose: {len(dbmod.load_glucose(conn))}")
    click.echo(f"  carbs: {len(dbmod.load_carbs(conn))}")
    click.echo(f"  heart rate: {len(dbmod.load_heart_rate(conn))}")
    click.echo(f"  activities: {len(dbmod.load_activities(conn))}")
    click.echo(f"  insulin doses: {len(dbmod.load_insulin(conn))}")
    conn.close()


@main.command()
@_DB_OPTION
@click.option("--host", default="127.0.0.1", show_default=True, help="Bind address. Keep this as 127.0.0.1 (localhost-only) unless you understand the exposure of opening it to your network.")
@click.option("--port", default=5000, show_default=True)
def serve(db_path, host, port):
    """Launch the local web UI: a Connections page to link Garmin/CGM once
    (no more re-entering credentials or running poll by hand), and a
    Dashboard page with the same chart 'report' builds."""
    from health_aggregator.webapp.app import create_app

    app = create_app(db_path=db_path)
    click.echo(f"Serving on http://{host}:{port} - Ctrl+C to stop")
    app.run(host=host, port=port, debug=False)


if __name__ == "__main__":
    main()
