# Ocean Environmental Intelligence Platform — Module 1: User & Ocean Data Management

A final-year (7-credit) project. This repository implements **Module 1** of a larger
Ocean Environmental Intelligence Platform: a modular monolith that authenticates users,
registers external ocean-data sources, ingests real data from them, validates and
normalizes it into a common schema, and fuses environmental (SST) data with marine
biodiversity occurrences via a spatiotemporal join.

Modules 2–5 (SST forecasting, anomaly/ecological-risk detection, alerts, and an
analytics dashboard) are **not implemented here** — see
[How Module 1 feeds the rest of the platform](#how-module-1-feeds-the-rest-of-the-platform)
for how they would consume this module's output.

## Architecture

A single deployable backend (FastAPI) with clear internal service boundaries, not a
microservices system — deliberately, so it stays explainable and demoable:

```
frontend (React/Vite)  ──HTTP──▶  backend (FastAPI)
                                      │
                        ┌─────────────┼─────────────┐
                        │             │             │
                   api/v1/*      services/*    ingestion/*
                   (routes)   (business logic)  (source adapters:
                        │             │          NOAA / Copernicus / OBIS)
                        │             │
                        └──────┬──────┘
                               │
                        repositories/*
                               │
                          SQLAlchemy ORM
                               │
                      PostgreSQL + PostGIS
```

- **`app/ingestion/`** — one adapter per external source, all implementing the same
  `fetch → validate → transform → load` interface (`BaseIngestionAdapter`), so a new
  dataset can be added without touching the API or service layer.
- **`app/services/`** — orchestration and business rules (auth, ingestion job
  lifecycle, spatiotemporal alignment). Depends on repositories, never on the ORM
  session directly from routes.
- **`app/repositories/`** — the only layer that talks SQLAlchemy/SQL to Postgres.
- **`app/api/v1/`** — thin FastAPI routers: parse request → call a service → return a
  Pydantic schema.

## Tech stack

| Layer | Choice |
|---|---|
| Frontend | React 19 + TypeScript + Vite + Tailwind CSS v4 |
| Backend | Python 3.11, FastAPI |
| Database | PostgreSQL 16 + PostGIS 3.4 |
| Auth | JWT (python-jose) + bcrypt (passlib) |
| Data engineering | pandas, NumPy, xarray, netCDF4, GeoPandas, Shapely |
| Infra | Docker + Docker Compose |
| Migrations | Alembic |
| Tests | pytest (backend), tsc/oxlint (frontend) |

## Repository structure

```
backend/
  app/
    api/v1/         REST endpoints
    core/           config, security (JWT/bcrypt), logging
    db/             SQLAlchemy engine/session, seed data
    ingestion/      NOAAAdapter, CopernicusAdapter, OBISAdapter, quality checks
    models/         SQLAlchemy ORM models (PostGIS geometry columns)
    repositories/   data-access layer
    schemas/        Pydantic request/response models
    services/       auth, ingestion orchestration, alignment
    tests/          pytest suite (unit + real network/DB integration tests)
  alembic/          migrations
frontend/
  src/
    api/            typed axios client per resource
    contexts/       AuthContext (JWT storage, current-user state)
    pages/          Login, Register, Dashboard, DataSources, Datasets,
                     Ingestion, DataQuality, Profile
    components/     Layout, ProtectedRoute, StatCard
docker-compose.yml
.env.example
```

## Getting started

### Option A — Docker Compose

```bash
cp .env.example .env
# edit .env: set a real JWT_SECRET_KEY, and Copernicus credentials if you'll
# use that adapter (see "Data sources" below)
docker compose up --build
```

- Backend: http://localhost:8000 (docs at `/docs`)
- Frontend: http://localhost:5173
- Postgres+PostGIS: localhost:5432

Alembic migrations run automatically on backend container startup
(`alembic upgrade head`, wired into the `backend` service's `command` in
`docker-compose.yml`), and the three data sources are seeded automatically on
FastAPI startup (`app/db/seed.py`, idempotent).

> **Note on this environment:** the reference machine used to build this project did
> not have Docker installed, so the Compose stack itself could not be smoke-tested end
> to end here. Everything it runs — the Alembic migration, the FastAPI app, the same
> `requirements.txt` — **was** verified directly: a local PostgreSQL 17 + PostGIS 3.6
> instance, a from-scratch `pip install -r requirements.txt`, `alembic upgrade head`,
> and the full pytest suite (including tests that hit the real NOAA/OBIS APIs) all
> passed against it. `docker-compose.yml` and both Dockerfiles were reviewed by hand
> for correctness but not executed. If `docker compose up` surfaces anything, it's most
> likely an environment-path issue (e.g. an `.env` value), not the application code.

### Option B — Local development (no Docker)

Backend:

```bash
cd backend
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

# a local Postgres with PostGIS enabled, matching .env.example's DATABASE_URL
createdb ocean_platform
psql -d ocean_platform -c "CREATE EXTENSION postgis;"

cp ../.env.example ../.env   # then edit DATABASE_URL to point at your local DB
alembic upgrade head
uvicorn app.main:app --reload
```

Frontend:

```bash
cd frontend
npm install
npm run dev
```

## Environment variables

See [`.env.example`](.env.example) for the full list. The important ones:

- `DATABASE_URL` — SQLAlchemy connection string (`postgresql+psycopg2://...`)
- `JWT_SECRET_KEY` — set a real random value outside of local dev
- `COPERNICUS_MARINE_USERNAME` / `COPERNICUS_MARINE_PASSWORD` — only needed for the
  Copernicus ingestion adapter (see below)

## Data sources — how to obtain access

| Source | Access | Notes |
|---|---|---|
| **NOAA OISST v2.1** | No account needed | Served over OPeNDAP by NOAA PSL at `psl.noaa.gov/thredds`. One NetCDF file per variable per year (`sst.day.mean.<year>.nc`, `sst.day.anom.<year>.nc`, `sst.day.err.<year>.nc`, `icec.day.mean.<year>.nc`). Longitude is natively 0–360; the adapter normalizes it to -180..180. |
| **Copernicus Marine SST** (GMPE) | [Free account](https://data.marine.copernicus.eu/register) required | Product `SST_GLO_PHY_L4_NRT_010_005`, dataset `cmems_obs-sst_glo_phy-temp_nrt_P1D-m` — confirmed against the live public catalog via `copernicusmarine describe --contains GMPE` (catalog browsing needs no login; only data download does). Set `COPERNICUS_MARINE_USERNAME`/`PASSWORD` in `.env`, or ingestion fails fast with a clear error. **Not exercised end-to-end in this environment** — no test account was available — but implemented against the official `copernicusmarine` Python toolbox's documented API. |
| **OBIS** | No account needed | Public REST API v3 at `api.obis.org`, cursor-paginated (`after` = last record's `id`). Capped at 10,000 records per ingestion run by design — this platform ingests geographic/temporal *subsets*, not the full OBIS database. |

## Database schema

8 tables (see `backend/app/models/`): `users`, `data_sources`, `datasets`,
`ocean_observations`, `biodiversity_observations`, `ingestion_jobs`,
`data_quality_reports`, `environment_biodiversity_matches`. Environmental and
biodiversity observations each carry a `geometry(Point, 4326)` PostGIS column with a
GIST index (created automatically by GeoAlchemy2), plus a B-tree index on
`(dataset_id, timestamp)` for date-range queries.

## REST API

All routes are under `/api`. Interactive docs at `/docs` once the backend is running.

| Endpoint | Auth |
|---|---|
| `POST /auth/register`, `POST /auth/login`, `GET /auth/me`, `POST /auth/logout` | — / JWT |
| `GET /data-sources`, `GET /datasets` | any authenticated user |
| `POST /ingestion/{noaa,copernicus,obis}` | ADMIN or RESEARCHER |
| `GET /ingestion/jobs`, `GET /ingestion/jobs/{id}` | any authenticated user |
| `GET /ocean-observations`, `GET /biodiversity-observations` (paginated, date/bbox/dataset filters) | any authenticated user |
| `GET /data-quality/{dataset_id}` | any authenticated user |
| `POST /alignment/run` | ADMIN or RESEARCHER |
| `GET /alignment/results` (paginated) | any authenticated user |

Roles: **ADMIN** (full access), **RESEARCHER** (ingestion + analysis), **USER**
(read-only) — enforced server-side via a FastAPI dependency
(`app/api/deps.py::require_roles`), not just hidden in the UI.

## Data quality

Every ingestion run produces a `DataQualityReport` accounting for every input record —
nothing is silently dropped. Checks (`app/ingestion/quality.py`, reused by every
adapter): missing required fields, duplicate records, invalid coordinates (including,
for OBIS, the source's own `ON_LAND` QC flag), invalid/unparseable timestamps,
physically-implausible SST (outside -3°C..40°C), and statistical outliers (z-score,
reported but not auto-rejected — a marine heatwave looks the same as a bad sensor
reading, so the pipeline flags it and leaves the call to a human).

## Spatiotemporal alignment

`AlignmentService` (`app/services/alignment_service.py`) implements
`match_biodiversity_to_environment`: for every biodiversity observation, find the
nearest ocean observation within a configurable spatial radius (great-circle distance
via a PostGIS `geography` cast) and temporal window, as one `CROSS JOIN LATERAL` SQL
query rather than a per-row Python loop. Example (matching the module spec):

```json
POST /api/alignment/run
{ "spatial_radius_km": 25, "temporal_window_hours": 24 }
```

Verified end-to-end against real NOAA + real OBIS data (see
`backend/app/tests/test_alignment.py`): ingested both for the same region/period and
confirmed the matches it produced actually satisfy the radius/window and carry
physically plausible SST values.

## Tests

```bash
cd backend
export DATABASE_URL="postgresql+psycopg2://<user>:<pass>@localhost:<port>/ocean_platform_test"
pytest app/tests/ -q
```

20 tests: unit tests for the quality-check module, API tests for auth and the
data-source registry, and — deliberately not mocked — integration tests that ingest
real data from NOAA and OBIS into a real local PostGIS database and then run the real
alignment query against it. Tests marked `@pytest.mark.network` need internet access.

Frontend: `npm run build` (type-checks via `tsc -b`, then bundles) and `npm run lint`.

## How Module 1 feeds the rest of the platform

Module 1's job is to hand the later modules **clean, normalized, spatiotemporally
fused** data — not raw files — through the common data model in
`ocean_observations`, `biodiversity_observations`, and
`environment_biodiversity_matches`.

- **Module 2 (ConvLSTM SST forecasting)** needs a regular spatiotemporal grid of SST
  history. It would query `ocean_observations` filtered by `dataset_id`/bounding
  box/date range (already exposed via `GET /api/ocean-observations`), pivot it into a
  `(time, lat, lon)` tensor, and train on it — trusting that every value it sees
  already passed the missing/duplicate/invalid-coordinate/invalid-range checks
  recorded in `data_quality_reports`, so it isn't learning from land pixels, sensor
  glitches, or NOAA's 0–360 longitude convention leaking through.

- **Module 3 (convolutional-autoencoder anomaly detection + ecological risk scoring)**
  needs both environmental context and where organisms actually were — that's exactly
  `environment_biodiversity_matches`: for each species occurrence, the nearest valid
  SST reading, its anomaly, and how far/how long ago that reading was taken
  (`distance_km`, `time_difference_hours`). Risk scoring for a species/region becomes a
  join over this table rather than a fresh geospatial computation each time.

- **Module 4 (alerts / decision support)** watches `sst_anomaly` on
  `ocean_observations` and the eventual anomaly scores from Module 3, plus
  `ingestion_jobs`/`data_quality_reports` for pipeline-health alerts (e.g. a spike in
  `records_rejected` or a `FAILED` job) — both already tracked here.

- **Module 5 (analytics dashboard)** is a read-only consumer of all of the above
  through the same paginated, filterable REST endpoints this module already exposes
  (date range, bounding box, dataset) — no new query surface required.

The `Dataset` row produced by every ingestion job (`data_source_id`, `kind`, temporal
and spatial coverage, `record_count`) is the join key later modules use to say which
run of which source a given prediction, anomaly, or alert was computed from —
provenance that matters for a final-year evaluation as much as for a real system.
