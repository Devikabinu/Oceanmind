# OceanMind

OceanMind is an AI-driven ocean monitoring platform for sea-surface temperature (SST) forecasting, anomaly detection, marine risk assessment, biodiversity analysis, and interactive visualization.

The project combines data ingestion, preprocessing, machine-learning forecasting, anomaly detection, risk assessment, backend APIs, and a frontend interface into a single extensible platform.

## Project Architecture

The system is organised into the following layers:

1. **User & Authentication Layer**
   - User registration and login
   - Role-based access
   - Profile management

2. **Data Management Layer**
   - SST data ingestion
   - Oceanographic data integration
   - Biodiversity data integration
   - Support for external scientific data sources

3. **Processing & Analytics Layer**
   - Data cleaning
   - Missing-data handling
   - Feature engineering
   - SST anomaly calculation
   - Spatial and temporal analysis

4. **AI/ML Layer**
   - SST forecasting
   - ConvLSTM-based spatiotemporal prediction
   - Multi-horizon forecasting
   - Anomaly detection
   - Severity scoring

5. **Application & Alert Layer**
   - Risk assessment
   - Risk-level classification
   - Alerts and recommendations

6. **Visualization Layer**
   - Interactive maps
   - Dashboards
   - Forecast visualization
   - Anomaly reports
   - Historical trends

7. **Backend & Database Layer**
   - REST APIs
   - Data services
   - User management
   - Forecast and anomaly services
   - Report and alert services

## Repository Structure

```text
Oceanmind/
├── backend/                 # Backend APIs and services
├── frontend/                # Frontend application
├── oceanmind_preprocess/    # Data preprocessing pipeline
├── oceanmind_forecast/      # Forecasting and baseline components
├── oceanmind_model/         # ConvLSTM model and training/evaluation
├── tests/                   # Automated tests
├── data/
│   └── raw/                 # Raw datasets (not tracked)
├── processed/               # Generated datasets/results (mostly not tracked)
├── config.yaml              # Project configuration
├── pyproject.toml           # Python project configuration
├── requirements.txt         # Python dependencies, if applicable
├── .env.example             # Environment variable template
└── README.md
## Ocean Environmental Intelligence platform

OceanMind is now a decision-support platform that connects observations, anomalies, forecasts, marine heatwaves, species records and
explainable risk and alerts. **Full documentation (architecture, data sources, methods, API, limitations, setup):
[docs/PLATFORM.md](docs/PLATFORM.md).**

Quick start (details and prerequisites in the document above):

```bash
.venv\Scripts\python -m oceanmind_model export-dashboard --config config.yaml   # forecast, heatwaves, history -> processed/model/dashboard/
cd backend && .venv\Scripts\alembic upgrade head
.venv\Scripts\python -m app.jobs sync-biodiversity      # real OBIS records + species catalogue (needs internet)
.venv\Scripts\python -m app.jobs publish-outputs        # DB rows + explainable alerts derived from the export
.venv\Scripts\uvicorn app.main:app --port 8000          # API, docs at /docs
cd ../frontend && npm install && npm run dev            # http://localhost:5173
```

Pages: Dashboard · Explore Ocean (Ocean Map, Forecast, Anomalies) · Marine Biodiversity (Species, Species Risk) · Environmental Risk
(Marine Heatwaves, Ecological Risk, Alerts) · Ocean Data · Model Performance. The recommended review walkthrough is in
[docs/PLATFORM.md](docs/PLATFORM.md#12-review-demonstration-path).

Tests: `cd backend && .venv\Scripts\python -m pytest app/tests` (add `-m "not network"` to skip the three live NOAA/OBIS tests), `.venv\Scripts\python -m pytest tests`
(ML), `cd frontend && npm run build`, `cd backend && .venv\Scripts\alembic check`.

Scientific honesty rules used throughout: data are labelled *Observation* / *Model output* / *Derived metric* / *Interpretation*;
SST, forecast, heatwave and risk layers exist only inside the NE Pacific study region (the map says so); the marine-heatwave
definition and the risk indicator are project-level and documented; species risk means *potential exposure*, never proven harm;
nothing is synthesised to fill an empty screen.
