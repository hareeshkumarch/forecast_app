# Forecasting Platform

A full-stack demand forecasting and analytics platform built with **FastAPI**, **Next.js (App Router)**, and **PostgreSQL**.

---

## Architecture Overview

```
forecast-hub/
├── backend/          # FastAPI REST API, Alembic migrations, forecasting engine
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

---

## Keyboard

| Key | Action |
| --- | --- |
| `⌘K` / `Ctrl+K` | Command palette |
| `N` | New forecast |
| `U` | Upload dataset |
| `I` | All insights |
| `T` | Toggle theme |

---

## Testing

- **Backend tests**: `pytest` inside `backend/`
- **Frontend unit tests**: `npm test` inside `frontend/`
- **Frontend layout tests**: `npm run test:e2e` inside `frontend/` — starts its
  own dev server and asserts the responsive contract at four viewports
