"""Render the merged timeline into a single self-contained HTML dashboard:
glucose overlaid with carb intake and heart rate/activity."""

import pandas as pd
import plotly.graph_objects as go

_TABLE_CSS = """
body { font-family: -apple-system, Segoe UI, Roboto, sans-serif; margin: 2rem; color: #1a1a1a; }
h1, h2 { font-weight: 600; }
table { border-collapse: collapse; margin-top: 0.5rem; }
th, td { padding: 0.4rem 0.8rem; border-bottom: 1px solid #ddd; text-align: right; }
th { text-align: right; background: #f5f5f5; }
td:first-child, th:first-child { text-align: left; }
"""


def _activity_spans(merged: pd.DataFrame) -> list[tuple]:
    """Collapse the per-bucket in_activity flag into contiguous (start, end, type) spans."""
    spans = []
    start = None
    label = None
    prev_ts = None
    for _, row in merged.iterrows():
        if row["in_activity"] and start is None:
            start, label = row["timestamp"], row["activity_type"]
        elif not row["in_activity"] and start is not None:
            spans.append((start, prev_ts, label))
            start = None
        prev_ts = row["timestamp"]
    if start is not None:
        spans.append((start, prev_ts, label))
    return spans


EVENT_LANE_COLORS = ["#9467bd", "#e377c2", "#8c564b", "#7f7f7f", "#bcbd22", "#17becf"]


def build_figure(
    merged: pd.DataFrame,
    low_mg_dl: float = 70,
    high_mg_dl: float = 180,
    events_df: pd.DataFrame = None,
) -> go.Figure:
    fig = go.Figure()

    if "glucose_mg_dl" in merged:
        fig.add_trace(
            go.Scatter(
                x=merged["timestamp"],
                y=merged["glucose_mg_dl"],
                name="Glucose (mg/dL)",
                meta="glucose",
                line=dict(color="#d62728"),
                yaxis="y1",
            )
        )
        fig.add_hrect(y0=low_mg_dl, y1=high_mg_dl, fillcolor="#2ca02c", opacity=0.08, line_width=0)

    if "bpm" in merged:
        fig.add_trace(
            go.Scatter(
                x=merged["timestamp"],
                y=merged["bpm"],
                name="Heart rate (bpm)",
                meta="heart_rate",
                line=dict(color="#1f77b4"),
                yaxis="y2",
                opacity=0.6,
            )
        )

    if "carbs_g" in merged:
        nonzero = merged[merged["carbs_g"] > 0]
        fig.add_trace(
            go.Bar(
                x=nonzero["timestamp"],
                y=nonzero["carbs_g"],
                name="Carbs (g)",
                meta="carbs",
                marker_color="#ff7f0e",
                yaxis="y3",
                width=3 * 60 * 1000,  # 3 minutes, in ms, so bars stay visible
            )
        )

    if "insulin_units" in merged:
        nonzero = merged[merged["insulin_units"] > 0]
        fig.add_trace(
            go.Bar(
                x=nonzero["timestamp"],
                y=nonzero["insulin_units"],
                name="Insulin (u)",
                meta="insulin",
                marker_color="#17becf",
                yaxis="y4",
                width=3 * 60 * 1000,
            )
        )

    # Activities and calendar events each get their own horizontal "lane" in a
    # thin strip along the top of the chart, spanning their actual start-end
    # time - a mini timeline, not just a point-in-time marker.
    activity_spans = _activity_spans(merged)
    calendar_names = (
        sorted(events_df["calendar_name"].dropna().unique()) if events_df is not None and not events_df.empty else []
    )
    lanes = (["Activities"] if activity_spans else []) + list(calendar_names)
    has_timeline = bool(lanes)

    if activity_spans:
        lane_y = lanes.index("Activities")
        xs, ys, texts = [], [], []
        for start, end, label in activity_spans:
            xs += [start, end, None]
            ys += [lane_y, lane_y, None]
            texts += [label, label, None]
        fig.add_trace(
            go.Scatter(
                x=xs,
                y=ys,
                mode="lines",
                line=dict(width=10, color=EVENT_LANE_COLORS[0]),
                name="Activities",
                meta="activities",
                yaxis="y5",
                text=texts,
                hoverinfo="text",
            )
        )

    for i, name in enumerate(calendar_names):
        lane_y = lanes.index(name)
        cal_events = events_df[events_df["calendar_name"] == name]
        xs, ys, texts = [], [], []
        for _, e in cal_events.iterrows():
            xs += [e["start"], e["end"], None]
            ys += [lane_y, lane_y, None]
            texts += [e["title"], e["title"], None]
        fig.add_trace(
            go.Scatter(
                x=xs,
                y=ys,
                mode="lines",
                line=dict(width=10, color=EVENT_LANE_COLORS[(i + 1) % len(EVENT_LANE_COLORS)]),
                name=f"{name} events",
                meta=f"cal:{name}",
                yaxis="y5",
                text=texts,
                hoverinfo="text",
            )
        )

    title_parts = []
    if "glucose_mg_dl" in merged:
        title_parts.append("glucose")
    if "bpm" in merged:
        title_parts.append("heart rate")
    if "carbs_g" in merged:
        title_parts.append("carbs")
    if "insulin_units" in merged:
        title_parts.append("insulin")
    if events_df is not None and not events_df.empty:
        title_parts.append("calendar events")
    title = ", ".join(title_parts).capitalize() if title_parts else "Health data"

    main_domain = [0, 0.7] if has_timeline else [0, 1]
    layout_kwargs = dict(
        title=title,
        xaxis=dict(title="Time", domain=[0, 0.82]),
        yaxis=dict(title="mg/dL", side="left", domain=main_domain),
        yaxis2=dict(title="bpm", overlaying="y", side="right"),
        yaxis3=dict(title="carbs (g)", overlaying="y", side="right", anchor="free", position=0.91, showgrid=False),
        yaxis4=dict(title="insulin (u)", overlaying="y", side="right", anchor="free", position=1.0, showgrid=False),
        legend=dict(orientation="h", y=1.08),
        height=680 if has_timeline else 600,
        barmode="overlay",
        showlegend=True,
    )
    if has_timeline:
        layout_kwargs["yaxis5"] = dict(
            domain=[0.78, 1.0],
            anchor="x",
            range=[-0.5, len(lanes) - 0.5],
            tickvals=list(range(len(lanes))),
            ticktext=lanes,
            showgrid=False,
            zeroline=False,
        )
    fig.update_layout(**layout_kwargs)
    return fig


def daily_table_html(daily: pd.DataFrame) -> str:
    if daily.empty:
        return "<p>No data.</p>"
    display = daily.rename(
        columns={
            "date": "Date",
            "avg_glucose_mg_dl": "Avg glucose (mg/dL)",
            "pct_time_in_range": "Time in range (%)",
            "total_carbs_g": "Total carbs (g)",
            "total_insulin_units": "Total insulin (u)",
            "active_minutes": "Active minutes",
        }
    ).round(1)
    return display.to_html(index=False, border=0)


def build_report(merged: pd.DataFrame, daily: pd.DataFrame, output_path: str, low_mg_dl: float = 70, high_mg_dl: float = 180) -> None:
    fig = build_figure(merged, low_mg_dl=low_mg_dl, high_mg_dl=high_mg_dl)
    chart_html = fig.to_html(include_plotlyjs=True, full_html=False)
    table_html = daily_table_html(daily)

    html = f"""<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<title>Health data report</title>
<style>{_TABLE_CSS}</style>
</head>
<body>
<h1>Health data report</h1>
{chart_html}
<h2>Daily summary</h2>
{table_html}
</body>
</html>
"""
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(html)
