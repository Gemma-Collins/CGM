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

The CLI has two steps: `ingest` parses export files and stores them in a
local SQLite database (`health_data.db` by default), and `report` builds
the HTML dashboard from whatever's currently in that database. They're
separate so you can re-run `ingest` any time you have a new export —
already-seen rows are skipped, so overlapping files are safe to re-import —
without losing history from earlier runs, and so a future scheduler/live
tracker can call `ingest` on its own on a timer while you just run `report`
whenever you want to look.

```bash
python -m health_aggregator.cli ingest \
  --garmin-dir ./exports/garmin \
  --cronometer-csv ./exports/cronometer_servings.csv \
  --cgm-csv ./exports/libreview.csv

python -m health_aggregator.cli report --output report.html
```

Any of the three sources can be omitted from an `ingest` call — run it
again later with just the new file for whichever source has fresh data.
Open `report.html` in a browser — the chart and data are fully embedded,
so it works offline and can be shared as a single file.

Useful flags:

- `--db path/to/file.db` (both commands) — where the persistent history
  lives (default `health_data.db` in the current directory)
- `ingest --cgm-format {auto,libreview,nightscout,generic}` — force the CGM
  CSV format instead of auto-detecting
- `report --start` / `--end` — only include data in that date/time range
- `report --freq 5min` — resampling interval for aligning all sources
- `report --low` / `--high` — target glucose range in mg/dL for the
  time-in-range calculation (defaults 70/180)

## How it works

Each source is parsed into a small pandas schema (see `models.py`):
glucose readings, carb entries, heart-rate samples, and activity summaries.
`ingest` upserts those into SQLite tables (`db.py`) keyed so re-importing
the same reading is a no-op. `report` loads everything (or a date range)
back out, and `merge.py` resamples it onto a common time grid (glucose/HR
averaged per bucket, carbs summed per bucket), flagging which buckets fall
inside a Garmin activity. `report.py` renders that merged timeline as a
Plotly chart plus a per-day summary table.

## Development

```bash
pip install -r requirements-dev.txt
pytest
```

Sample export files for each source live in `tests/fixtures/` if you want
to see the expected CSV shapes.
