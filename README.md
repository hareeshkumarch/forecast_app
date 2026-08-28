# Forecasting Platform

A full-stack demand forecasting and analytics platform built with **FastAPI**, **Next.js (App Router)**, and **Supabase** (with a local **PostgreSQL** fallback).

---

## Architecture Overview

```
forecast-hub/
├── backend/          # FastAPI REST API, Alembic migrations, forecasting engine, Supabase/Postgres access
├── frontend/         # Next.js App Router UI, ECharts, Zustand state, Tailwind CSS
├── storage/          # Local persistent storage for uploads, exports, and SQLite/DuckDB
├── docker-compose.yml# Single-command local dev environment
└── .env.example      # Environment template
```

### Components

- **Backend (`/backend`)**:
  - FastAPI with async database access via SQLAlchemy & AsyncPG / Psycopg.
  - Alembic for database migrations.
  - In-process `ProcessPoolExecutor` for asynchronous ML model training and prediction.
  - A model roster that is fitted, backtested and ranked per run: naive,
    seasonal naive, Holt-Winters, auto-ETS, Theta, Croston/SBA, SARIMAX,
    gradient boosting, an ensemble, and Prophet when installed.

- **Frontend (`/frontend`)**:
  - Next.js 14+ with React Server Components & Client Components.
  - Modern dashboard with Interactive ECharts (`forecast-vs-actual`, category aggregations).
  - State management via Zustand & React Query.
  - Tailwind CSS + UI Primitives, light/dark theming and a density switch.
  - Responsive from phone to ultra-wide: the rails become drawers on narrow
    viewports and the panels size themselves with container queries.

- **Storage (`/storage`)**:
  - Local directory for dataset uploads, generated Parquet files, and exports.

---

## Where the data lives

Supabase is the store of record. Everything the platform persists — connectors,
datasets, forecast runs, per-series forecasts, insights and usage — is written
there. Point the API at it with either form:

```bash
# The connection string from Project Settings → Database → Connection string → URI
SUPABASE_DB_URL=postgresql://postgres:YOUR-PASSWORD@db.YOUR-PROJECT-REF.supabase.co:5432/postgres

# …or the project URL and the database password, and the host is derived
SUPABASE_URL=https://YOUR-PROJECT-REF.supabase.co
SUPABASE_DB_PASSWORD=your-password
```

The pooled host (`…pooler.supabase.com:6543`) is supported and detected: server-side
statement caching is turned off for it, because pgbouncer in transaction mode cannot
carry a prepared statement between statements.

**Local PostgreSQL is the fallback.** With no Supabase settings — a plain
`docker compose up`, or the test suite — the platform uses `DATABASE_URL`
unchanged. If Supabase *is* configured but cannot be reached when a process
starts, that process falls back to the local database, logs a warning, and
reports `status: degraded` from `/api/health`; Settings → *Where runs are stored*
shows the same thing in the UI. Set `DATABASE_FALLBACK_ENABLED=false` to refuse
the fallback and fail the boot instead.

The choice is made once per process, and Alembic migrates whichever store was
chosen — so migrations and the request path never disagree about where the
schema lives. API and Celery workers read the same settings, so they resolve to
the same database.

---

## Quick Start (Docker Compose)

Run the full stack (Database + Backend + Frontend) with one command:

```bash
docker compose up --build
```

- **Frontend UI**: [http://localhost:3000](http://localhost:3000)
- **Backend API**: [http://localhost:8000](http://localhost:8000)
- **Interactive API Docs (Swagger)**: [http://localhost:8000/docs](http://localhost:8000/docs)

---

## Local Development (Without Docker)

### Backend Setup

1. Navigate to `backend/`:
   ```bash
   cd backend
   ```
2. Create and activate a Python virtual environment:
   ```bash
   python -m venv .venv
   source .venv/bin/activate  # On Windows: .venv\Scripts\activate
   ```
3. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```
4. Run migrations & start server:
   ```bash
   uvicorn app.main:app --reload --port 8000
   ```

### Frontend Setup

1. Navigate to `frontend/`:
   ```bash
   cd frontend
   ```
2. Install dependencies:
   ```bash
   npm install
   ```
3. Start dev server:
   ```bash
   npm run dev
   ```
4. Access the web interface at `http://localhost:3000`.

---

## Reading a customer's file

Uploads and connectors go through the same profiler, which works out what each
column *is* before anything is forecast from it.

**The file opens first.** The delimiter is sniffed rather than assumed — a
semicolon CSV is what Excel writes anywhere the comma is the decimal separator,
and reading it as a comma file yields one column holding the whole line. Tabs
and pipes work the same way, and a delimiter inside a quoted value is not
counted as one. Encoding is detected across UTF-8, UTF-8 with a byte order
mark, cp1252 and latin-1, so `région` stays `région`. A report title and a
blank line above the header are skipped, and blank trailing rows are dropped.
A row holding more values than the header has columns is refused rather than
truncated, because truncation drops whatever sat past the last column and does
it in silence. A workbook is opened at the sheet that holds the data rather
than at whichever one comes first, and a label merged down a block of rows is
carried down the rows it spans instead of arriving once with nulls beneath it.

**Values are read, not assumed.** Money arrives from Excel as `$1,234.56`, from
a German ERP as `1.234,56`, from a French one as `1 234,56`, from an Indian
ledger as `₹1,00,000`, from an accounting package as `(890.00)`, from a
mainframe as `1000-`, and with a unit stuck on the end as `1000 kg`. All of
those are numbers, and all of them are read as numbers — by one reader, which
works out what the separators mean before removing them. Stripping the commas
as decoration first is how `1.234,56` becomes 1.23456, and a target a
thousandfold small is a file that looks like it imported cleanly.

Dates arrive as ISO, as `15.01.2024`, as an ISO timestamp with or without
milliseconds and with or without a zone, as `20240115`, as `2024Q1`, as
`2024-W03`, as `FY24-P01`, and as the Excel serial `45292` that a spreadsheet
leaves behind when it loses its formatting. A convention is chosen from a
sample, applied to the whole column, and kept only if it explains nearly every
row — so one stray token cannot drag a column into the wrong reading.

The values that come out are what gets stored. Everything downstream reads the
Parquet through DuckDB's `TRY_CAST`, and `"$1,234.56"` casts to `NULL`, so a
column detected but not converted would be a column silently full of nothing.
The original upload is kept untouched alongside it.

**Day/month order is the one guess worth arguing about.** `01/02/2024` is the
first of February in most of the world and the second of January in the United
States. Where a value passes the twelfth the data settles it outright. Where a
monthly file holds its day-of-month fixed, the position that never moves is the
day — which is how `01/01, 02/01, 03/01` stays January, February, March instead
of collapsing into the first three days of January. Where every value genuinely
fits both readings, no algorithm can do better than guess, so the profile says
so and `date_order` on the upload settles it by hand.

How each column was read is recorded and shown beside it, because a date read
in the wrong order is the one mistake nothing downstream can catch. A value
that was present and could not be read counts as missing and is reported as
such — a blank cell and an unreadable one are different problems, and only one
of them is about the data.

A fiscal period label means the company's own year, not January's:
`FISCAL_YEAR_START_MONTH` moves `FY24-P01` to October for a US federal
calendar or April for an Indian one. And the calendar step is inferred from
whether the gaps actually agree on one — five readings a day apart and one a
year later have a median gap of one day, and calling that daily asks for four
hundred periods holding six observations.

**Two table shapes are recognised as shapes.** A planning sheet writes its
periods across the top — `Jan 2024`, `Feb 2024`, … — and those headings are
data, so the table is turned on its side before anything is read from it. Long
format is the opposite trap: `date, metric, value` profiles perfectly well, and
means nothing when summed, because the number is revenue on one row and units
on the next. Where the values under a category are orders of magnitude apart
the profile says so, because nothing downstream can tell — by then it is a
column of doubles like any other.

**Roles come from meaning, not position.** `revenue`, `rev`, `umsatz`,
`ventas`, `chiffre_affaires`, `totalRevenue`, `fct_order__net_rev_usd` and
`Net Revenue` all name the same thing, and reordering the columns does not
change which one is the target. A word that names the measure beats one that
only says it is a sum, so `order_revenue` wins over `line_total`. A column with
more distinct values than a category plausibly has is treated as an identifier:
it stays available to group by, but is not offered by default, because
grouping by `customer_id` asks for a forecast per customer and pools almost all
of them into "Others".

---

## How a forecast is produced

Nothing about the fit is fixed in advance. Each series is profiled first
(`backend/app/forecasting/diagnostics.py`) to measure its seasonal period,
trend strength, intermittency, outliers and whether it needs a variance
transform. Every model then configures itself from that profile — the seasonal
period is detected rather than assumed, SARIMAX and ETS search their own
specifications by AICc, and gradient boosting scales its hyperparameters to the
training size.

Candidates are backtested over expanding (or rolling, on long histories)
windows, scored on a weighted blend of wMAPE/sMAPE/RMSE — or absolute error for
intermittent demand, where percentage metrics reward forecasting zero — and the
winner refits on the full history.

**Nothing leaks backwards from the future.** Every step that looks at the
values around a point is done inside the fold that is about to be scored, not
once over the whole history: the series profile, the variance transform, the
interpolation that fills a missing period, the clip that damps an outlier, and
the search for which column leads the target and by how many periods. Any one
of them done up front puts the validation window into its own training data,
and the only symptom is a reported accuracy better than the real one. A period
that was never observed is not scored at all — filling a gap invents a number,
and grading the model against it reports an accuracy nobody measured.

Models that tune their own hyperparameters search against the metrics the run
is scored by, and are evaluated the way they will really be used. Reading a
validation block out of a design matrix hands a recursive model the true last
observation at every step, so it is graded on one-step-ahead accuracy with the
answers in front of it — and the search then picks the settings that lean
hardest on the value it will not have.

### Optional models

Prophet is not installed by default because it compiles a Stan model on first
use. The engine detects what is present and reports the rest as unavailable
rather than failing:

```bash
pip install -r backend/requirements-optional.txt
```

### Tuning what it decides

The numbers behind those decisions — metric weights, the interval weight, the
divergence ceiling, ensemble limits, search budgets, insight thresholds and the
drift limits — are settings rather than constants, and every one is documented
with its default in `.env.example`. They are range-checked at boot: a value
outside its range fails the start naming the variable, instead of quietly
producing a forecast nobody can account for. The scoring rule the API reports
is built from the weights actually in force, so a re-weighted deployment
describes itself correctly.

### Breakdowns

A grouped run is one question asked at several levels, so everything under the
headline number is answered by the same settings. A period a series has no row
for is a gap rather than a zero — a SKU nobody reported and a SKU that sold
nothing are different facts, and which one it is comes from the run's gap-fill
setting rather than from a hard-coded zero. The reducer is the run's own, so a
breakdown of an averaged measure is averaged. A driver, though, adds up the way
*its* name says it does: summing a price or a conversion rate over the rows in
a month gives a figure that grows with the row count.

A total that is negative or zero still gets a breakdown. Margin, net-of-returns
and balance measures go below zero routinely, and dividing by the signed total
used to discard every series under it and say nothing.

### What it refuses

A run that reports "completed" has to have done what it was asked, so the
things that cannot be done are refused rather than quietly skipped. A column
is checked for what it *holds*, not just that it exists — a text column chosen
as the target casts to a column of nulls and fails somewhere far from the
choice that caused it. A driver that is not numeric, or not in the dataset, is
named back rather than filtered out of the list in silence. A model roster
that matches nothing fails the run instead of falling back to the full roster
and reporting the winner as though it had been asked for. A horizon longer
than half the history is refused, because no backtest fold can be built that
measures a forecast that far out. And a series the profiler marks severe — no
usable rows, too few periods — stops there, because a number produced from
that is indistinguishable from a real one.

A target that never moves is not in that list. A discontinued line is the same
value in every period and the flat forecast is the right answer for it; what
the report says instead is that its accuracy cannot be measured, because every
percentage error divides by a total that does not change.

### After the fact

A finished run can be graded against data that arrived later
(`POST /api/forecasts/{id}/score`). Alongside accuracy and interval coverage the
scorecard reports a tracking signal — cumulative error in mean absolute
deviations — and marks the run as drifting when it has missed the same way in
period after period, which is the kind of error that will not correct itself.

`POST /api/forecasts/{id}/simulate` re-prices a finished run under a different
assumption. It re-prices — it does not refit, because the history under the new
assumption does not exist — and it says so, in a `method` field beside the
numbers. The bands widen with the size of the intervention, because a scenario
nothing measured is less certain than the forecast it came from. Volume and target shifts scale it directly; a driver multiplier
moves the total by that driver's own measured share of the movement, so asking
for 2× on a driver holding 40% of the impact lifts the forecast by 40%, not
100%. Drivers the run never found are refused rather than silently applied.

### About a minute

The third step on the landing page says a forecast takes about a minute, which
makes it an SLO rather than a turn of phrase. Every stage of a run is timed
against its own budget — parse, validate, classify, features, fit, predict,
calibrate, persist — and the timings are persisted with the run in
`diagnostics.timings`. `tests/test_latency_budget.py` asserts the p95 of five
real runs over a reference dataset (104 weekly periods, one series, a nine-week
horizon) against the 60-second total.

The promise holds up to **500 series in one run**. Past that the run is queued
and reports progress instead of being served inline, and past 20,000 it is
refused with a message saying so — a count that high is almost always a grain
that accidentally includes an order or transaction reference. Both numbers live
in `app/core/budget.py` and are enforced by `admission()`, not left as a note.

The run dialog starts in **Fast** mode: five routed candidates over three
backtest folds. **Balanced** adds the heavier statistical and boosting models,
and **Thorough** uses the full roster over eight folds. Candidate backtests are
evaluated concurrently while their results are restored to the original model
order before scoring, so concurrency cannot change a tie or the reported rank.
`FORECAST_MODEL_CONCURRENCY` controls that per-run parallelism. Keep
`FORECAST_WORKERS × FORECAST_MODEL_CONCURRENCY` close to the machine's available
CPU cores; on a four-core host, `2 × 2` is the practical starting point.

### Where an accuracy figure comes from

`GET /api/forecasts/{id}/accuracy` returns WAPE and signed bias by horizon and
by series class, the value the chosen model added over the best baseline that
ran beside it, and the provenance behind every figure: the commit, the model
and feature versions, and a hash of the settings that change what a forecast
decides. It says plainly whether the numbers are measured against outcomes that
have since arrived or against held-out stretches of the customer's own history,
because those are different claims.

`GET /api/forecasts/accuracy/headline` aggregates that into the single
percentage an accuracy section would print, weighted by periods scored rather
than averaged across runs. It returns `publishable: false` until at least three
runs over twenty-six periods stand behind it. The landing page's accuracy
section is still static copy — pointing it at a live figure is a decision about
exposing one deployment's numbers publicly, and the endpoint is ready for
whoever makes it.

---

## Keyboard

| Key | Action |
| --- | --- |
| `⌘K` / `Ctrl+K` | Command palette |
| `N` | New forecast |
| `U` | Upload dataset |
| `I` | All insights |
| `T` | Toggle theme |
| `[` | Collapse / expand the sidebar |

---

## Testing

- **Backend tests**: `pytest` inside `backend/`
- **Frontend unit tests**: `npm test` inside `frontend/`
- **Frontend layout tests**: `npm run test:e2e` inside `frontend/` — builds and
  serves the app, then asserts the responsive contract at four viewports. It is
  a production build rather than `next dev` because Fast Refresh recompiles a
  route on first navigation and the rebuild lands mid-click, dropping it. Point
  the tests at a server you are already running with `E2E_BASE_URL`.
