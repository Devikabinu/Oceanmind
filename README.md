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