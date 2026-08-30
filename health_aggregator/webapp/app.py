"""Local web UI.

Two pages instead of CLI flags: **Connections** to link Garmin/CGM once
(credentials are encrypted and saved, so you don't reconnect every time),
and **Dashboard**, the same chart/table `report` builds, read live from the
database. Connecting a source also starts a background thread that keeps
polling it on the same jittered interval the `schedule`/`schedule-cgm` CLI
commands use, so the dashboard stays current without you running anything
by hand.
"""

import calendar as calendar_module
import json
import os
import tempfile
import threading

import pandas as pd
from flask import Flask, flash, redirect, render_template, request, url_for

from health_aggregator import credentials as credmod
from health_aggregator import db as dbmod
from health_aggregator import scheduler
from health_aggregator.importers import nutrition_pdf
from health_aggregator.live import calendar_live, garmin_live, nightscout_live
from health_aggregator.merge import daily_summary, merge_all
from health_aggregator.models import CARB_COLUMNS, INSULIN_COLUMNS, empty_frame
from health_aggregator.report import EVENT_LANE_COLORS, build_figure, daily_table_html

_POLL_INTERVALS_MIN = {
    "garmin": (15, 30),
    "nightscout": (5, 10),
    "google_calendar": (30, 60),
}

_active_threads: dict = {}


def create_app(db_path: str = "health_data.db") -> Flask:
    app = Flask(__name__)
    app.secret_key = os.urandom(24)
    app.config["DB_PATH"] = db_path
    app.config["MAX_CONTENT_LENGTH"] = 20 * 1024 * 1024  # 20MB, generous for a PDF upload

    def get_conn():
        return dbmod.connect(app.config["DB_PATH"])

    def _garmin_poll():
        conn = get_conn()
        try:
            creds = credmod.load_credentials(conn, "garmin")
            if creds is None:
                return
            garmin_live.poll_once(conn, email=creds["email"], password=creds["password"])
            credmod.mark_status(conn, "garmin", "connected")
        except Exception:
            credmod.mark_status(conn, "garmin", "error")
        finally:
            conn.close()

    def _nightscout_poll():
        conn = get_conn()
        try:
            creds = credmod.load_credentials(conn, "nightscout")
            if creds is None:
                return
            nightscout_live.poll_once(
                conn, base_url=creds["url"], token=creds.get("token"), api_secret=creds.get("api_secret")
            )
            credmod.mark_status(conn, "nightscout", "connected")
        except Exception:
            credmod.mark_status(conn, "nightscout", "error")
        finally:
            conn.close()

    def _calendar_poll():
        conn = get_conn()
        try:
            creds = credmod.load_credentials(conn, "google_calendar")
            if creds is None:
                return
            calendar_live.poll_once(conn, token_path=creds["token_path"])
            credmod.mark_status(conn, "google_calendar", "connected")
        except Exception:
            credmod.mark_status(conn, "google_calendar", "error")
        finally:
            conn.close()

    _poll_fns = {"garmin": _garmin_poll, "nightscout": _nightscout_poll, "google_calendar": _calendar_poll}

    def _sync_calendar_connection_marker() -> None:
        """The Calendar OAuth token isn't a secret we hold (Google's token
        file is), so this just mirrors "does that file exist" into the
        connections table for the status page and the background-poll
        resume logic - not a real credential."""
        conn = get_conn()
        try:
            token_path = calendar_live.DEFAULT_TOKEN_PATH
            if os.path.exists(token_path):
                if credmod.load_credentials(conn, "google_calendar") is None:
                    credmod.save_credentials(conn, "google_calendar", {"token_path": token_path})
            else:
                credmod.delete_credentials(conn, "google_calendar")
        finally:
            conn.close()

    def _ensure_background_poll(source: str) -> None:
        existing = _active_threads.get(source)
        if existing is not None and existing.is_alive():
            return
        lo, hi = _POLL_INTERVALS_MIN[source]
        thread = threading.Thread(
            target=scheduler.run_forever,
            args=(_poll_fns[source], lo * 60, hi * 60),
            daemon=True,
        )
        thread.start()
        _active_threads[source] = thread

    # Resume background polling for anything already connected from a past run.
    _sync_calendar_connection_marker()
    conn = get_conn()
    for row in credmod.list_connections(conn):
        _ensure_background_poll(row["source"])
    conn.close()

    @app.route("/")
    def dashboard():
        conn = get_conn()
        glucose_df = dbmod.load_glucose(conn)
        carb_df = dbmod.load_carbs(conn)
        hr_df = dbmod.load_heart_rate(conn)
        activity_df = dbmod.load_activities(conn)
        insulin_df = dbmod.load_insulin(conn)
        polls = dbmod.last_polls(conn)
        conn.close()

        has_data = not (glucose_df.empty and carb_df.empty and hr_df.empty and insulin_df.empty)
        chart_html, table_html = None, None
        if has_data:
            merged = merge_all(glucose_df, carb_df, hr_df, activity_df, insulin_df)
            daily = daily_summary(merged)
            fig = build_figure(merged)
            chart_html = fig.to_html(include_plotlyjs=True, full_html=False)
            table_html = daily_table_html(daily)

        return render_template(
            "dashboard.html",
            has_data=has_data,
            chart_html=chart_html,
            table_html=table_html,
            polls=polls.to_dict("records") if not polls.empty else [],
        )

    @app.route("/day")
    def day_view():
        try:
            selected_date = pd.Timestamp(request.args.get("date"))
            if pd.isna(selected_date):
                raise ValueError("no date given")
        except (ValueError, TypeError):
            selected_date = pd.Timestamp.now()
        selected_date = selected_date.normalize()

        day_start = selected_date
        day_end = selected_date + pd.Timedelta(days=1) - pd.Timedelta(seconds=1)
        year, month = selected_date.year, selected_date.month
        month_start = pd.Timestamp(year=year, month=month, day=1)
        month_end = month_start + pd.offsets.MonthEnd(0)

        conn = get_conn()
        glucose_df = dbmod.load_glucose(conn, start=day_start, end=day_end)
        activities = dbmod.load_activities(conn, start=day_start, end=day_end)
        hr_df = dbmod.load_heart_rate(conn, start=day_start, end=day_end)
        events = dbmod.load_calendar_events(conn, start=day_start, end=day_end)
        data_dates = (
            dbmod.dates_with_data(conn, "activities", "start", month_start, month_end)
            | dbmod.dates_with_data(conn, "heart_rate_samples", "timestamp", month_start, month_end)
            | dbmod.dates_with_data(conn, "calendar_events", "start", month_start, month_end)
            | dbmod.dates_with_data(conn, "glucose_readings", "timestamp", month_start, month_end)
        )
        conn.close()

        low_mg_dl, high_mg_dl = 70.0, 180.0

        chart_html = None
        glucose_mgdl_json = "[]"
        if not (glucose_df.empty and hr_df.empty and activities.empty):
            merged = merge_all(glucose_df, empty_frame(CARB_COLUMNS), hr_df, activities, empty_frame(INSULIN_COLUMNS), freq="5min")
            fig = build_figure(merged, low_mg_dl=low_mg_dl, high_mg_dl=high_mg_dl, events_df=events)
            chart_html = fig.to_html(include_plotlyjs=True, full_html=False, div_id="day-chart")
            if "glucose_mg_dl" in merged:
                # Embedded as a plain JS array so the unit toggle has the real
                # values to convert from - Plotly's own embedded trace data
                # isn't always a plain array (large series get a compact
                # {dtype, bdata} encoding that has no .slice()).
                glucose_mgdl_json = json.dumps(
                    [None if pd.isna(v) else v for v in merged["glucose_mg_dl"]]
                )

        hr_summary = None
        if not hr_df.empty:
            hr_summary = {
                "min": round(hr_df["bpm"].min(), 1),
                "avg": round(hr_df["bpm"].mean(), 1),
                "max": round(hr_df["bpm"].max(), 1),
                "count": len(hr_df),
            }

        glucose_summary = None
        if not glucose_df.empty:
            mg = glucose_df["mg_dl"]
            glucose_summary = {
                "min": round(mg.min(), 1),
                "avg": round(mg.mean(), 1),
                "max": round(mg.max(), 1),
                "in_range_pct": round(100 * mg.between(low_mg_dl, high_mg_dl).mean(), 1),
                "count": len(mg),
            }

        calendar_names = sorted(events["calendar_name"].dropna().unique().tolist()) if not events.empty else []
        calendar_colors = {
            name: EVENT_LANE_COLORS[(i + 1) % len(EVENT_LANE_COLORS)] for i, name in enumerate(calendar_names)
        }
        prev_month = (month_start - pd.Timedelta(days=1)).replace(day=1)
        next_month = month_end + pd.Timedelta(days=1)

        return render_template(
            "day.html",
            selected_date=selected_date,
            month_start=month_start,
            prev_month=prev_month,
            low_mg_dl=low_mg_dl,
            high_mg_dl=high_mg_dl,
            glucose_mgdl_json=glucose_mgdl_json,
            glucose_summary=glucose_summary,
            calendar_colors=calendar_colors,
            EVENT_LANE_COLORS=EVENT_LANE_COLORS,
            next_month=next_month,
            weeks=calendar_module.Calendar(firstweekday=6).monthdatescalendar(year, month),
            data_dates=data_dates,
            chart_html=chart_html,
            activities=activities.to_dict("records"),
            hr_summary=hr_summary,
            events=events.to_dict("records"),
            calendar_names=calendar_names,
        )

    @app.route("/connections")
    def connections():
        _sync_calendar_connection_marker()
        conn = get_conn()
        statuses = {row["source"]: row for row in credmod.list_connections(conn)}
        conn.close()
        return render_template(
            "connections.html",
            statuses=statuses,
            calendar_client_secrets_path=calendar_live.DEFAULT_CLIENT_SECRETS_PATH,
        )

    @app.route("/connections/garmin/connect", methods=["POST"])
    def connect_garmin():
        email = request.form.get("email", "").strip()
        password = request.form.get("password", "")
        conn = get_conn()
        try:
            garmin_live.login(email=email, password=password)
            credmod.save_credentials(conn, "garmin", {"email": email, "password": password})
            _ensure_background_poll("garmin")
            flash("Garmin connected.", "success")
        except Exception as exc:
            flash(f"Couldn't connect to Garmin: {exc}", "error")
        finally:
            conn.close()
        return redirect(url_for("connections"))

    @app.route("/connections/garmin/disconnect", methods=["POST"])
    def disconnect_garmin():
        conn = get_conn()
        credmod.delete_credentials(conn, "garmin")
        conn.close()
        flash("Garmin disconnected.", "success")
        return redirect(url_for("connections"))

    @app.route("/connections/nightscout/connect", methods=["POST"])
    def connect_nightscout():
        url = request.form.get("url", "").strip()
        token = request.form.get("token", "").strip() or None
        api_secret = request.form.get("api_secret", "").strip() or None
        conn = get_conn()
        try:
            nightscout_live.fetch_entries(url, token=token, api_secret=api_secret, count=1)
            credmod.save_credentials(conn, "nightscout", {"url": url, "token": token, "api_secret": api_secret})
            _ensure_background_poll("nightscout")
            flash("CGM (Nightscout) connected.", "success")
        except Exception as exc:
            flash(f"Couldn't connect to Nightscout: {exc}", "error")
        finally:
            conn.close()
        return redirect(url_for("connections"))

    @app.route("/connections/nightscout/disconnect", methods=["POST"])
    def disconnect_nightscout():
        conn = get_conn()
        credmod.delete_credentials(conn, "nightscout")
        conn.close()
        flash("CGM disconnected.", "success")
        return redirect(url_for("connections"))

    @app.route("/uploads/nutrition-pdf", methods=["POST"])
    def upload_nutrition_pdf():
        file = request.files.get("pdf_file")
        date = request.form.get("date", "").strip() or None
        if file is None or file.filename == "":
            flash("No PDF selected.", "error")
            return redirect(url_for("connections"))

        conn = get_conn()
        tmp_path = None
        try:
            with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp:
                file.save(tmp.name)
                tmp_path = tmp.name
            carb_df = nutrition_pdf.parse_pdf(tmp_path, date=date)
            n = dbmod.upsert_carbs(conn, carb_df)
            if carb_df.empty:
                flash(f"Couldn't find any labeled carbs/calories in {file.filename}.", "error")
            else:
                flash(f"Extracted {n} new nutrition entr{'y' if n == 1 else 'ies'} from {file.filename}.", "success")
        except Exception as exc:
            flash(f"Couldn't process {file.filename}: {exc}", "error")
        finally:
            conn.close()
            if tmp_path and os.path.exists(tmp_path):
                os.remove(tmp_path)
        return redirect(url_for("connections"))

    return app
