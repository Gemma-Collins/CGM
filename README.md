# Health Data Aggregator

Merges three data sources into one HTML dashboard: a glucose curve overlaid
with carb intake and heart rate, with activity periods shaded and a daily
time-in-range table.

- **Activities & heart rate** — Garmin vivoactive, via `.fit` files exported
  from Garmin Connect
- **Carbs** — Cronometer, via its CSV export
- **Glucose (CGM)** — FreeStyle Libre 2 via LibreView, or xDrip+/MiaoMiao via
  a Nightscout CSV export

Everything runs from files you export yourself — no credentials are stored
and no API calls are made, so there's nothing to configure or authenticate.

## Setup

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## Getting the exports

**Garmin** — On [connect.garmin.com](https://connect.garmin.com), open an
activity, click the gear icon, then "Export Original" to download a `.fit`
file. Put all the `.fit` files you want in one folder and pass it as
`--garmin-dir`. (Garmin doesn't offer a file-based export of all-day
continuous heart rate outside of individual activities — only per-activity
heart rate during workouts is available this way.) If you only have a
simple `timestamp,heart_rate` CSV from somewhere else, use `--garmin-csv`
instead.

**Cronometer** — Settings → Export Data → download the "Servings" export
(gives per-meal timing) or the "Daily Summary" export (one row per day, no
meal timing — carb entries are placed at noon). Pass the CSV as
`--cronometer-csv`.

**CGM (Libre 2)** — Log into [LibreView](https://www.libreview.com) →
Export Data → download the CSV. Pass it as `--cgm-csv` (auto-detected).

**CGM (xDrip+ / MiaoMiao)** — If xDrip+ is uploading to a Nightscout site,
open its Reports page and download the CSV export (columns include
`dateString`/`sgv`). Pass it as `--cgm-csv` — this format is auto-detected
too. If you have some other CSV shape, `--cgm-format generic` will try to
find timestamp/glucose columns by name.

## Usage

```bash
python -m health_aggregator.cli \
  --garmin-dir ./exports/garmin \
  --cronometer-csv ./exports/cronometer_servings.csv \
  --cgm-csv ./exports/libreview.csv \
  --output report.html
```

Any of the three sources can be omitted. Open `report.html` in a browser —
the chart and data are fully embedded, so it works offline and can be
shared as a single file.

Useful flags:

- `--freq 5min` — resampling interval for aligning all sources (default 5
  minutes)
- `--low` / `--high` — target glucose range in mg/dL for the time-in-range
  calculation (defaults 70/180)
- `--cgm-format {auto,libreview,nightscout,generic}` — force the CGM CSV
  format instead of auto-detecting

## How it works

Each source is parsed into a small pandas schema (see `models.py`):
glucose readings, carb entries, heart-rate samples, and activity summaries.
`merge.py` resamples all of them onto a common time grid (glucose/HR
averaged per bucket, carbs summed per bucket) and flags which buckets fall
inside a Garmin activity. `report.py` renders that merged timeline as a
Plotly chart plus a per-day summary table.

## Development

```bash
pip install -r requirements-dev.txt
pytest
```

Sample export files for each source live in `tests/fixtures/` if you want
to see the expected CSV shapes.
