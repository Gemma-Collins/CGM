# Health Data Aggregator

Merges data from Garmin, Cronometer, CGM, Google Calendar, and PDF
nutrition sheets into one local database, with an HTML dashboard: a
glucose curve overlaid with carb intake, insulin doses, and heart rate,
activity periods shaded, and a daily time-in-range table.

- **Activities & heart rate** — Garmin vivoactive, via `.fit` files exported
  from Garmin Connect, or live via `poll`/`schedule`
- **Carbs** — Cronometer CSV export, or a PDF nutrition sheet/meal plan
  (see "Nutrition PDF upload" below)
- **Glucose (CGM)** — FreeStyle Libre 2 via LibreView, or xDrip+/MiaoMiao via
  a Nightscout CSV export or live via `poll-cgm`/`schedule-cgm`
- **Insulin doses** — from Nightscout's treatment log (live only, via
  `poll-cgm`/`schedule-cgm` alongside glucose — see "Live tracking" below).
  Only picks up entries with a discrete dose amount (bolus-style), however
  they're logged there; temp-basal rate/duration entries (pump-specific)
  aren't parsed. There's no file-import path for this yet.
- **Calendar** — Google Calendar events, live via `poll-calendar`/
  `schedule-calendar`, classified by keyword (gym/workout -> "activity",
  flight/travel -> "travel", else "other"). Stored, but not yet drawn on
  the dashboard chart - see "Google Calendar" below.

Cronometer always works from a file export, since it has no public API.
Garmin, CGM (Nightscout), and Calendar all also have a live path (see
"Live tracking" below) that polls the source directly instead of you
exporting a file each time.

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

## Web UI (recommended for everyday use)

Instead of environment variables and CLI flags, a small local web app gives
you a **Connections** page (link Garmin/CGM once, credentials are encrypted
and saved so you never reconnect or re-run a poll command by hand again)
and a **Dashboard** page (the same chart `report` builds, always current).

```bash
python -m health_aggregator.cli serve
```

Then open `http://127.0.0.1:5000` in a browser. On **Connections**, enter
your Garmin login or Nightscout URL/token and click Connect — each one is
validated immediately, then polls automatically in the background on the
same jittered schedule described below (15-30 min for Garmin, 5-10 min for
Nightscout), for as long as `serve` keeps running. **Dashboard** always
reflects whatever's currently in the database, live sources included.

Credentials are encrypted at rest (a key file under `~/.health_aggregator/`,
separate from the repo) and stored in the same SQLite database as
everything else — nothing is sent anywhere except directly to Garmin's or
your Nightscout site's own servers, exactly as the CLI commands below do.

This only runs locally on your own machine for now (`127.0.0.1` — not
reachable from other devices or the internet). Turning this into something
you can share a link to with an educator, e.g. embedded on a website, is a
separate next step — the local version is the place to start.

Google Calendar also shows up on Connections, but read-only — its OAuth
consent needs a browser popup that doesn't fit a web form, so connect it
once from a terminal (`connect-calendar`, see below) and it then polls
automatically here just like Garmin/Nightscout. The Connections page also
has a **Nutrition PDF** upload form (a one-off action, not a persistent
connection - see "Nutrition PDF upload" below).

Cronometer still has no live path here either — keep using
`ingest --cronometer-csv` from the command line for it.

## Live tracking (CLI, if you'd rather not use the web UI)

Both live sources write into the same database the file importer uses, so
`report` (or the Dashboard page above) picks up whatever they've fetched
automatically — there's no separate "live view"; it's the same dashboard,
just fed automatically instead of by hand.

### Garmin

Instead of exporting `.fit` files by hand, `poll`/`schedule` log into
Garmin's cloud (the same account your Garmin Connect app already uses) and
pull whatever heart rate/activity data has synced there. This uses the
unofficial [`garminconnect`](https://github.com/cyberjunky/python-garminconnect)
library — Garmin doesn't publish an API for individual developers, so this
can break if Garmin changes their backend, and it needs your Garmin login
stored where the tool runs.

Set your credentials as environment variables (never as a CLI flag, so
they don't end up in shell history):

```bash
export GARMIN_EMAIL="you@example.com"
export GARMIN_PASSWORD="your-garmin-password"
```

**One-off pull:**

```bash
python -m health_aggregator.cli poll
```

**Run continuously** (polls forever on a jittered interval — a random gap
between `--min-minutes` and `--max-minutes` each time, by default 15-30,
rather than a perfectly fixed cadence):

```bash
python -m health_aggregator.cli schedule
```

The first login caches a session token to `~/.garmin_tokens` (override with
`--tokenstore`), so later polls don't need your password again until that
token expires.

### CGM (Nightscout, for xDrip+/MiaoMiao)

If xDrip+ uploads to a Nightscout site, `poll-cgm`/`schedule-cgm` pull both
glucose entries and insulin doses from it directly via Nightscout's own
REST API (entries + treatments endpoints). Unlike Garmin, this is a
documented, official API on a server you control, so there's no
reverse-engineering and no risk of Garmin-style breakage.

Set the site URL and either a read-only access token (preferred) or the
classic API secret, as environment variables:

```bash
export NIGHTSCOUT_URL="https://your-site.example.com"
export NIGHTSCOUT_TOKEN="your-read-only-token"
# or, if your site still uses the older scheme:
# export NIGHTSCOUT_API_SECRET="your-api-secret"
```

```bash
python -m health_aggregator.cli poll-cgm       # one-off pull
python -m health_aggregator.cli schedule-cgm    # runs forever, 5-10 min jittered by default
```

CGM readings arrive every 1-5 minutes, much faster than Garmin's sync
cadence, so `schedule-cgm` defaults to a tighter interval than Garmin's
`schedule` — and since it's your own server rather than an unofficial
client, there's no need to be as conservative about polling frequency.

### Google Calendar

Google's OAuth consent needs an interactive browser popup, which doesn't
fit a background poll loop - so connecting is a one-time step, separate
from polling:

1. In [Google Cloud Console](https://console.cloud.google.com/apis/credentials),
   enable the Calendar API, then create an OAuth client ID of type
   **Desktop app**, and download its JSON.
2. Save it to `~/.health_aggregator/google_calendar_credentials.json` (or
   pass `--client-secrets path/to/file.json` below).
3. Connect once - this opens a browser for you to sign in and grant
   read-only calendar access, then caches a token so this never needs to
   happen again (until you revoke access):

```bash
python -m health_aggregator.cli connect-calendar
```

Then, same pattern as the other live sources:

```bash
python -m health_aggregator.cli poll-calendar       # one-off pull
python -m health_aggregator.cli schedule-calendar    # runs forever, 30-60 min jittered by default
```

Events are classified by keyword into `activity` (gym, workout, run,
ride, swim, yoga, hike, ...), `travel` (flight, trip, airport, ...), or
`other`, and stored in a `calendar_events` table - not yet drawn on the
dashboard chart itself (planned next).

### Nutrition PDF upload

If nutrition info only exists as a PDF (a dietitian's handout, a meal
plan, a scanned nutrition facts sheet) rather than a Cronometer export,
`ingest --nutrition-pdf` extracts labeled carbs/calories from it - lines
like "Carbs: 45g" or "Total Carbohydrate 45 g", "Calories: 210" or
"Energy 210" - using the nearest heading-like line above each as the food
name. It's a best-effort text pattern match, not a general PDF-table
parser, so check the extracted rows against the source document,
especially for multi-column layouts.

```bash
python -m health_aggregator.cli ingest --db health_data.db \
  --nutrition-pdf path/to/meal-plan.pdf --pdf-date 2026-08-15
```

`--pdf-date` matters since PDFs rarely carry a reliable "when eaten"
timestamp - it defaults to noon today if omitted. Extracted entries land
in the same carbs table as Cronometer's, tagged `source=nutrition_pdf` so
they can still be told apart.

The web UI's Connections page has an upload form for this too, since it's
a one-off action rather than a persistent connection.

### Checking it's running

```bash
python -m health_aggregator.cli status
```

This shows each source's most recent poll outcome (success/error, how long
ago, rows added, and the error message if it failed) plus a row count for
each data type currently stored — the heartbeat to glance at instead of
reading logs.

## How it works

Each source is parsed into a small pandas schema (see `models.py`):
glucose readings, carb entries, heart-rate samples, activity summaries,
insulin doses, and calendar events. `ingest` upserts those into SQLite
tables (`db.py`) keyed so re-importing the same reading is a no-op.
`report` loads everything (or a date range) back out, and `merge.py`
resamples it onto a common time grid (glucose/HR averaged per bucket,
carbs/insulin summed per bucket), flagging which buckets fall inside a
Garmin activity. `report.py` renders that merged timeline as a Plotly
chart plus a per-day summary table. Calendar events are stored and
queryable via `db.load_calendar_events` but aren't in that merge/chart yet
— per the "functionality first, visualize later" scoping of this feature.

`credentials.py` encrypts and stores Garmin/Nightscout credentials for the
web UI (`webapp/`), which is a thin Flask layer over the same `db.py`,
`live/`, and `report.py` code the CLI uses — connecting a source there just
calls the same `garmin_live`/`nightscout_live` functions `poll`/`poll-cgm`
call, and starts a background thread running the same `scheduler.py` loop
`schedule`/`schedule-cgm` use.

## Development

```bash
pip install -r requirements-dev.txt
pytest
```

Sample export files for each source live in `tests/fixtures/` if you want
to see the expected CSV shapes.
