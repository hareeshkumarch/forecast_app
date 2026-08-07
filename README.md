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
winner refits on the full history. The profile is recomputed inside every fold,
so nothing leaks backwards from the future.

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

### After the fact

A finished run can be graded against data that arrived later
(`POST /api/forecasts/{id}/score`). Alongside accuracy and interval coverage the
scorecard reports a tracking signal — cumulative error in mean absolute
deviations — and marks the run as drifting when it has missed the same way in
period after period, which is the kind of error that will not correct itself.

`POST /api/forecasts/{id}/simulate` re-prices a finished run under a different
assumption. Volume and target shifts scale it directly; a driver multiplier
moves the total by that driver's own measured share of the movement, so asking
for 2× on a driver holding 40% of the impact lifts the forecast by 40%, not
100%. Drivers the run never found are refused rather than silently applied.

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
