import os

import pandas as pd

from health_aggregator.report import build_figure, build_report
from tests.test_merge import _activity_df, _carb_df, _glucose_df, _hr_df, _insulin_df
from health_aggregator.merge import daily_summary, merge_all
from health_aggregator.models import CALENDAR_COLUMNS, ensure_schema


def test_build_report_writes_self_contained_html(tmp_path):
    merged = merge_all(_glucose_df(), _carb_df(), _hr_df(), _activity_df())
    daily = daily_summary(merged)
    output = tmp_path / "report.html"

    build_report(merged, daily, str(output))

    assert output.exists()
    content = output.read_text()
    assert "<html>" in content or "<html" in content
    assert "Daily summary" in content
    assert "plotly" in content.lower()


def test_build_report_includes_insulin_trace_and_table_column(tmp_path):
    merged = merge_all(_glucose_df(), _carb_df(), _hr_df(), _activity_df(), _insulin_df())
    daily = daily_summary(merged)
    output = tmp_path / "report.html"

    build_report(merged, daily, str(output))

    content = output.read_text()
    assert "Insulin (u)" in content
    assert "Total insulin" in content


def _events_df():
    return ensure_schema(
        pd.DataFrame(
            {
                "start": pd.to_datetime(["2026-08-10 07:00", "2026-08-10 09:00"]),
                "end": pd.to_datetime(["2026-08-10 07:45", "2026-08-10 09:30"]),
                "title": ["Morning run", "Standup"],
                "event_type": ["activity", "other"],
                "calendar_name": ["Personal", "Work"],
                "source": ["google_calendar"] * 2,
            }
        ),
        CALENDAR_COLUMNS,
    )


def test_build_figure_adds_one_marker_trace_per_calendar():
    merged = merge_all(_glucose_df(), _carb_df(), _hr_df(), _activity_df())
    fig = build_figure(merged, events_df=_events_df())

    trace_names = [t.name for t in fig.data]
    assert "Personal events" in trace_names
    assert "Work events" in trace_names


def test_build_figure_without_events_df_has_no_event_traces():
    merged = merge_all(_glucose_df(), _carb_df(), _hr_df(), _activity_df())
    fig = build_figure(merged)
    trace_names = [t.name for t in fig.data]
    assert not any(name and name.endswith(" events") for name in trace_names)


def test_build_figure_title_reflects_available_layers():
    merged = merge_all(_glucose_df(), _carb_df(), _hr_df(), _activity_df())
    fig = build_figure(merged, events_df=_events_df())
    assert "calendar events" in fig.layout.title.text.lower()
    assert "glucose" in fig.layout.title.text.lower()
