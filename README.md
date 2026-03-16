# ForecastHub — Time Series Analytics Platform
[![CI](https://github.com/hareeshkumarch/forecast_app/actions/workflows/ci.yml/badge.svg)](https://github.com/hareeshkumarch/forecast_app/actions/workflows/ci.yml)

A production-grade full-stack forecasting system. Upload any time series data, auto-detect columns, preprocess, and train 7 different models (ARIMA, SARIMA, ARIMAX, Prophet, Holt-Winters, LSTM, Transformer) with real-time progress and comprehensive comparison dashboards.

## Architecture

```
┌─────────────────────────────────────┐
│          React + Tailwind           │  Port 5000
│  (Upload, Configure, Train, View)   │
├─────────────────────────────────────┤
│         Express.js Proxy            │  Port 5000
│  (API proxy + WebSocket relay)      │
├─────────────────────────────────────┤
│      FastAPI ML Engine (async)      │  Port 8001
│  (Preprocessing, Training, SQLite)  │
└─────────────────────────────────────┘
```

## Quick Start (Development)

### Prerequisites
- Node.js 20+
- Python 3.10+
- pip

### 1. Install Node dependencies
```bash
npm install
```

### 2. Install Python dependencies
```bash
pip install -r ml_engine/requirements.txt
```

### 3. Start ML Engine
```bash
cd ml_engine && python server.py
```

### 4. Start Dev Server (new terminal)
```bash
npm run dev
```

Open http://localhost:5000

## Docker

```bash
docker-compose up --build
```

## Production

- **Verify build:** `npm run check` (TypeScript) and `npm run build` (client + server bundle). All imports and libraries are resolved; production start: `npm run start` (serves `dist/public` and `dist/index.cjs`).
- Copy `.env.example` to `.env` and set `PORT`, `ML_ENGINE_URL`. Optionally set `CORS_ORIGIN` and `ML_REQUEST_TIMEOUT_MS`.
- **Health:** `GET /api/health` — always 200; reports ML engine status. **Readiness:** `GET /api/ready` — 200 when ML engine is reachable, 503 otherwise (e.g. Kubernetes readiness probe).
- WebSocket URL for real-time progress: `ws://<host>/ws/<jobId>` (or `wss://` and path with base if using a reverse proxy).
- **Node:** `engines.node` >= 20 (see `package.json`).

## Features

- **Auto Column Detection** — Automatically identifies date, target, and exogenous columns
- **Smart Preprocessing** — Datetime parsing, frequency detection, missing value handling, outlier removal (IQR), stationarity testing (ADF), seasonality detection
- **7 Models** — ARIMA (auto-order), SARIMA, ARIMAX, Prophet, Holt-Winters, LSTM, Transformer
- **Real-time Progress** — WebSocket-based live training updates
- **Results Dashboard** — Comparison charts, forecast plots with confidence intervals, residual analysis, metrics table
- **History** — SQLite-backed job persistence, browse and revisit past forecasts
- **Demo Datasets** — 3 built-in datasets (Retail Sales daily, Product Demand weekly, Monthly Revenue)
- **Dark Mode** — Full dark/light theme support
- **Column Mapping** — When user data has different column names, map them via UI
- **Chart Filters** — Date range, horizon (points), model selection, and metric comparison (RMSE/MAE/MAPE/R²)

## Use Cases

| Use case | Flow |
|----------|------|
| **Quick demo** | Home → pick a demo dataset → Configure (or defaults) → Start → Training (real-time) → Results |
| **Custom upload** | Home → Upload CSV/Excel → Map columns (date, target, optional exogenous) → Set horizon & models → Start → Training → Results |
| **Compare models** | Results → Chart filters → select models to compare; Comparison tab → choose metric (RMSE, MAE, MAPE, R²) |
| **What-If scenario** | Results → What-If tab → adjust multiplier slider to simulate ±% change on best model forecast |
| **Export & report** | Results → Export CSV (best model forecast + bounds); Save PDF (print) |
| **History & revisit** | History → view past jobs → View Results or delete |

For a detailed **code strength assessment**, **flaws**, and **high-level UI improvement** ideas, see [docs/CODE_AND_UI_ASSESSMENT.md](docs/CODE_AND_UI_ASSESSMENT.md).

## Project Structure

```
forecast-hub/
├── client/src/
│   ├── App.tsx              # Router (hash-based)
│   ├── components/
│   │   └── app-layout.tsx   # Sidebar nav + dark mode
│   ├── pages/
│   │   ├── home.tsx         # Upload + demo + column mapping + model selection
│   │   ├── training.tsx     # Real-time progress via WebSocket
│   │   ├── results.tsx      # 4-tab results dashboard
│   │   └── history.tsx      # Past forecast jobs
│   └── index.css            # Dark slate + blue accent theme
├── server/
│   ├── routes.ts            # Express proxy to ML engine + WS relay
│   └── storage.ts           # Minimal (persistence in Python)
├── shared/
│   └── schema.ts            # Zod schemas + model constants
├── ml_engine/
│   ├── server.py            # FastAPI + WebSocket + SQLite
│   ├── database.py          # Async SQLite (aiosqlite)
│   ├── preprocessor.py      # Auto preprocessing pipeline
│   ├── models.py            # 7 forecasting models
│   ├── demo_data.py         # 3 demo datasets
│   └── requirements.txt     # Python dependencies
├── Dockerfile
├── docker-compose.yml
└── docker-start.sh
```

## API Endpoints

| Method | Path | Description |
|--------|------|-------------|
| GET | /api/health | Health check |
| POST | /api/upload | Upload CSV/Excel file |
| GET | /api/demos | List demo datasets |
| GET | /api/demo/:id | Load demo dataset |
| POST | /api/forecast | Start forecast job |
| GET | /api/jobs | List all jobs |
| GET | /api/jobs/:id | Get job details |
| GET | /api/results/:id | Get job results |
| DELETE | /api/jobs/:id | Delete job |
| WS | /ws/:id | Real-time training progress (WebSocket) |
| GET | /api/ready | Readiness probe (503 if ML engine unavailable) |
