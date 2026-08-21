import os

from health_aggregator.report import build_report
from tests.test_merge import _activity_df, _carb_df, _glucose_df, _hr_df, _insulin_df
from health_aggregator.merge import daily_summary, merge_all


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
