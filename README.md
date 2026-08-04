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
  - Statistical & ML forecasting models (Exponential Smoothing, ARIMA, LightGBM/Ridge).

- **Frontend (`/frontend`)**:
  - Next.js 14+ with React Server Components & Client Components.
  - Modern dashboard with Interactive ECharts (`forecast-vs-actual`, category aggregations).
  - State management via Zustand & React Query.
  - Tailwind CSS + UI Primitives.

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

## Testing

- **Backend tests**: `pytest` inside `backend/`
- **Frontend tests**: `npm test` inside `frontend/`
