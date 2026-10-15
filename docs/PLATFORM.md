# OceanMind: Ocean Environmental Intelligence and Marine Conservation Decision-Support Platform

This document describes what the platform does, where every number comes from, how to run it and what it cannot tell you.

## 1. The question chain

```
OBSERVATIONS (NOAA OISST) -> ANOMALIES -> FORECAST (ConvLSTM) -> MARINE HEATWAVES
        -> ENVIRONMENTAL RISK -> SPECIES OVERLAP (OBIS) -> ECOLOGICAL RISK -> ALERTS -> EXPLANATION
```

| Question | Where it is answered |
|---|---|
| What is happening, where? | Dashboard, Ocean Map, location inspector |
| Is it abnormal? | Anomalies page (`/anomaly`), anomaly layers |
| Will it continue? | Forecast page, Marine Heatwaves (forecast persistence) |
| How severe? | Severity bands, heatwave category, risk level |
| Which species / habitats may be affected? | Species pages, species overlap factor |
| Why? | "What does this mean?" and "Why this alert?" panels, risk factor bars |
| What should be watched? | Ecological Risk areas, Alerts |

## 2. Architecture and data flow

```
DATA SOURCES            INGESTION / ML BATCH                    DATABASE (PostgreSQL+PostGIS)   API (FastAPI)                 FRONTEND (React)
NOAA OISST   ---------> oceanmind_preprocess  -> processed/cubes
                        oceanmind_model train/evaluate           (files)
                        oceanmind_model export-dashboard ------> processed/model/dashboard/*   /api/monitor, /heatwaves,
                           (latest forecast, heatwaves,                                        /ecological-risk, /ocean
                            2-year per-cell history)
NOAA / Copernicus / OBIS  backend ingestion adapters  ---------> datasets, ocean_observations,  /api/ingestion, /datasets, ...   Dashboard, Map,
OBIS + WoRMS + GBIF       python -m app.jobs sync-biodiversity -> species, biodiversity_obs.    /api/species                    Forecast, Anomalies,
processed export          python -m app.jobs publish-outputs --> sst_forecasts, anomaly_det.,   /api/forecast, /anomaly,           Heatwaves, Species,
                                                                  ecological_risk_scores,       /risk, /alerts                  Ecological Risk,
                                                                  alerts(+details)                                              Alerts, Ocean Data,
                                                                                                                                Model Performance
```

Two kinds of backend data:
* **File-backed (no DB tables):** forecast maps, anomalies, marine heatwaves, risk grids and point history are read from
  `processed/model/dashboard/` (written by `python -m oceanmind_model export-dashboard`). The API never imports PyTorch.
* **Database-backed:** species catalogue, OBIS observations, alerts, per-record risk scores, derived observation/forecast rows,
  datasets, ingestion jobs and quality reports.

## 3. Running it end to end

```bash
# 0. prerequisites: PostgreSQL 16+ with PostGIS, Python 3.11-3.13, Node 20+, a trained model in processed/model/
cp .env.example .env            # set DATABASE_URL etc. (never commit .env)

# 1. ML export (once per data refresh; ~5 min on CPU)
.venv\Scripts\python -m oceanmind_model export-dashboard --config config.yaml

# 2. database
cd backend
python -m venv .venv && .venv\Scripts\pip install -r requirements.txt
.venv\Scripts\alembic upgrade head

# 3. load real data (all optional, all idempotent; need internet for OBIS/WoRMS/GBIF)
.venv\Scripts\python -m app.jobs sync-biodiversity      # species catalogue + sampled OBIS records
.venv\Scripts\python -m app.jobs publish-outputs        # observations, anomalies, forecasts, risk scores, alerts

# 4. run
.venv\Scripts\uvicorn app.main:app --port 8000
cd ../frontend && npm install && npm run dev
```

Register a user in the app (or via `POST /api/auth/register`); roles ADMIN/RESEARCHER may acknowledge/resolve alerts and add species.

### Environment variables

| Variable | Purpose |
|---|---|
| `DATABASE_URL` | SQLAlchemy URL of the main database |
| `FRONTEND_ORIGIN` | CORS origin (default `http://localhost:5173`) |
| `PROCESSED_DIR` | Where the ML pipeline wrote `processed/` (default `<repo>/processed`) |
| `OBIS_API_BASE_URL`, `NOAA_OISST_BASE_URL`, `COPERNICUS_*` | Source endpoints / credentials (see `.env.example`) |
| `VITE_API_BASE_URL` | Frontend API base (default `http://localhost:8000/api`) |

## 4. Data sources and coverage

| Source | What | Coverage of the source | Loaded in this project |
|---|---|---|---|
| NOAA OISST v2.1 | Daily SST analysis (observed) | Global ocean, 0.25 degree, 1981-present | NE Pacific study region (20-50N, 160-120W), 2012 to the last processed day |
| Copernicus Marine (GMPE SST) | Secondary SST (observed/analysis) | Global | Adapter only; needs free credentials |
| OBIS | Species occurrence records | Global, uneven effort | A time-spread sample per catalogued species in the study region |
| WoRMS / GBIF | English common names | n/a | Names only |
| GBIF species API | IUCN Red List category for the species (CR/EN/VU/NT/LC/DD/NE) with the IUCN taxon id | Species GBIF links to an IUCN assessment | Per catalogued species (preferred source) |
| OBIS red-list checklist | IUCN category for *threatened* species only | Threatened species only | Fallback when GBIF has no assessment |
| Project ConvLSTM | 7-day SST forecast (model output) | Study region | Issued from the last processed day |

The Ocean Map starts from a world view, but **SST, forecast, heatwave and risk layers exist only inside the dashed study-region
outline**. Outside it the UI says "no data" rather than guessing. `GET /api/ocean/regions` and `/api/ocean/coverage` report this
programmatically; the Ocean Data page shows it per source.

Data freshness: the last processed observation is shown on every page ("Data status"). The forecast is issued from that day, not
from today.

## 5. Methods

### 5.1 SST anomaly
`anomaly = SST - climatology(day of year)`, with the climatology the smoothed 2012-2023 daily mean (training period).
Dashboard severity bands for 2x2 degree blocks: MEDIUM >= 1 degC, HIGH >= 2, CRITICAL >= 3 (absolute block-mean anomaly). These are
SST-departure bands, **not** ecological risk.

### 5.2 Marine heatwaves (project-level, simplified Hobday et al. 2016)
Per ocean cell and day:
1. Threshold = seasonally varying 90th percentile of SST in an 11-day window around each day of year, pooled over the baseline
   years (2012-2023), smoothed with a 31-day circular mean.
2. Exceedance = SST > threshold. Gaps of <= 2 days between exceedances are bridged. Runs shorter than 5 days are dropped.
   A run in progress on the last day counts only once it has already reached 5 days (right-censored).
3. Intensity = SST - climatology. Category = floor(peak intensity / (threshold - climatology)), capped at IV
   (I Moderate, II Strong, III Severe, IV Extreme).
4. Events = 8-connected clusters of active cells with >= 10 cells (about 7,000 km2). Area uses cell latitude (cos-lat) areas.
5. Per event we also report the **cumulative intensity** (sum of daily anomalies over the event, degC-days), the number of days the event has lasted, and a
   60-day **timeline** (area of today's event cells that was in a heatwave state on each date, and their mean anomaly).
6. Historical comparison: the share of earlier days with a smaller heatwave area; yearly maxima/means; "historical percentile" =
   today's SST rank among baseline-year values within +-5 days of the same day of year.

**Differences from the published definition:** 12-year instead of 30-year baseline, the project's climatology, no sea-ice handling.
It is therefore labelled a *project-level indicator*, not an official classification. Tested in `tests/test_heatwaves.py`.

### 5.3 Project environmental risk indicator
Four 0-1 factors, weighted sum (weights 0.35 / 0.25 / 0.20 / 0.20), documented at `GET /api/ecological-risk/methodology` and on the
Ecological Risk page (Methodology tab):

| Factor | Definition | Weight |
|---|---|---|
| SST anomaly | abs(today's anomaly) / 3 degC, capped at 1 | 0.35 |
| Heatwave persistence | current heatwave run length / 14 days, capped at 1 | 0.25 |
| Forecast anomaly | mean abs(forecast anomaly over days 1-7) / 3 degC, capped at 1 | 0.20 |
| Species overlap | distinct species with OBIS records in the surrounding 2x2 degree block (last 730 days) / 3, capped at 1 | 0.20 |

Levels: < 0.25 LOW, < 0.5 MEDIUM, < 0.75 HIGH, else CRITICAL. If no species data are loaded the overlap factor is dropped and the
remaining weights renormalised (the UI says so). The weights are a project choice, not fitted to outcomes; no confidence interval is
shown because none can be defended.

**Species exposure** applies the same factors to the places where a species was recorded in the last 2 years (weighted by record
count); the overlap factor becomes the share of those positions currently >= 1 degC from normal. Wording is always "potential
exposure" / "monitoring priority", never "harm".

### 5.4 Alerts
`python -m app.jobs publish-outputs` raises alerts of four types, each with `details` (driver, numbered reasons, data sources,
classification, recommendation, evidence, species) and a stable de-duplication key:

| Type | Raised when |
|---|---|
| `MARINE_HEATWAVE` | an active event has area >= 50,000 km2, or category >= III, or overlaps at least one species a source lists as VU/EN/CR |
| `SST_ANOMALY` | a 2x2 degree block is >= 2 degC from normal today |
| `SST_FORECAST_HEAT` | a block is forecast >= 2 degC warmer on day 7 (model output) |
| `ECOLOGICAL_RISK` | a species with >= 20 recent records has a HIGH/CRITICAL exposure score |

Each alert also stores `evidence_summary` (label/value pairs such as maximum anomaly, duration, affected area, cumulative intensity, number of species with
records, number of conservation-sensitive species), shown under "Why this alert?". Re-running the job refreshes the evidence of an existing alert in place
(same key) and never changes its workflow status. Status workflow (NEW -> ACKNOWLEDGED -> RESOLVED, forward only, ADMIN/RESEARCHER only) is unchanged.

## 6. Observation vs model output vs derived metric vs interpretation

Every card, chart and table carries a tag:

* **Observation**: measured/recorded data (NOAA OISST, OBIS records).
* **Model output**: ConvLSTM forecast. Never presented as an observation.
* **Derived metric**: anomaly, percentile, heatwave state, risk (computed from the above).
* **Test evaluation**: error statistics on the held-out test period.
* **Interpretation**: plain-language reading; not a scientific conclusion.

## 7. API (new endpoints)

All require authentication (JWT) like the existing API. Existing endpoints are unchanged except that `alerts` responses gained an
optional `details` object and `biodiversity-observations` gained optional species fields.

| Endpoint | Purpose |
|---|---|
| `GET /api/monitor/overview` | KPIs, data status, interpretation sentences, heatwave + risk summary |
| `GET /api/monitor/map?layer=&horizon=&date=` | Grid layer: observed, observed_anomaly, forecast, forecast_anomaly, heatwave, risk, hindcast* |
| `GET /api/monitor/location?lat=&lon=` | Everything known about a point, or a clear "outside coverage" |
| `GET /api/monitor/history?lat=&lon=&days=` | SST/normal/threshold/anomaly series (up to 730 days) |
| `GET /api/monitor/hotspots?horizon=0..7&date=` | Anomalous 2x2 degree areas (0 = observed) |
| `GET /api/monitor/{point,region,performance}` | Verification series, regional means, model metrics |
| `GET /api/heatwaves`, `/{id}`, `/timeseries` | Events, explanation + species overlap, area history |
| `GET /api/ecological-risk/{methodology,location,areas?region=,species}` | Method, cell assessment, top areas (filter by level and region), species ranking |
| `GET /api/species?q=&group=&status=&threatened=`, `/summary`, `/search`, `/{aphia}`, `/{aphia}/{observations,risk,distribution}`; `POST /api/species` | Catalogue (name/taxonomy search, group, IUCN status filter), dashboard summary, live OBIS search, detail, records, exposure metrics, observed distribution (OBIS record density) |
| `GET /api/alerts/summary` | Open alerts by status and severity (existing `/api/alerts` list/detail/PATCH unchanged; responses gained `details`) |
| `GET /api/ocean/regions`, `/coverage` | Ocean basins and per-source coverage |

Interactive docs: `http://localhost:8000/docs`.

## 8. Database additions (migration `7c1d9e3a5b21`, additive)

* New table `species` (AphiaID, names, taxon group, IUCN category + source, links, watch-list flag).
* `alerts.details` (JSON, nullable).
* `biodiversity_observations.species_name`, `species_aphia_id`, `taxon_class` (nullable, indexed).

Check with `alembic upgrade head` / `alembic downgrade -1`. No existing rows are modified. `CONTRACTS.md` lists the contracts.

## 9. Limitations (read before presenting results)

* Study-region only for SST, forecast, heatwave and risk; outside it there is no data.
* Observations end at the last processed day (shown on screen); the forecast is not a live feed. The processed data may include
  preliminary NRT values.
* The ConvLSTM is a small CPU-trained model; test MAE is about 0.22 degC averaged over 1-7 days. Local errors can be larger.
* Species records are a sample from OBIS with uneven effort. No records does not mean no animals.
* Conservation status is only what a source reports: the IUCN category from GBIF (preferred, includes Least Concern / Data Deficient) or, as a fallback, the OBIS
  threatened-species checklist. If neither reports one the UI says "Status not confirmed", never "Least Concern". Sources can disagree after a reassessment (e.g. green
  turtle: GBIF Least Concern, OBIS checklist Endangered); both are shown and the source of the displayed value is named. Species can also have regional
  sub-population assessments that differ from the global one.
* The heatwave definition is simplified; the risk weights are a project choice.
* Threat descriptions, habitat classes, range polygons and protected areas are **not** included: no authoritative dataset is loaded
  (the IUCN Red List API needs a key; protected-area layers were not added without a vetted dataset).
* Copernicus ingestion is available but not loaded (needs credentials).

## 10. Testing

```bash
cd backend && .venv\Scripts\python -m pytest app/tests -v     # needs the test database (see below)
cd .. && .venv\Scripts\python -m pytest tests -v               # ML / heatwave unit tests
cd frontend && npm run build && npm run lint
```

Test database: `ocean_platform_test` owned by the `ocean_admin` role with PostGIS available; `conftest.py` creates/drops the
schema. Dashboard tests use a tiny hand-built export (`app/tests/_outputs.py`: 16x16 grid with one synthetic heatwave); species
tests replace the external HTTP clients with canned responses. The three ingestion/alignment tests that hit the live NOAA and OBIS services are marked `@pytest.mark.network`; everything else runs offline:

```bash
cd backend && .venv\Scripts\python -m pytest app/tests -m "not network"   # offline, ~30 seconds
cd backend && .venv\Scripts\python -m pytest app/tests                      # everything incl. live NOAA/OBIS (a few minutes; NOAA may rate-limit)
```

## 11. Authentication and error handling

* All data endpoints require a JWT (`Authorization: Bearer ...`); unauthenticated calls get `401`, role-restricted actions get `403`. Roles: USER (read), RESEARCHER and
  ADMIN (also acknowledge/resolve alerts, add species).
* Frontend: sign-in/registration/logout, protected routes, and a clear "session expired" path (an invalid token is dropped once and the user is sent to
  `/login?expired=1`). If the **backend is unreachable** the app shows "Backend unavailable" with *Try again* and **keeps** the sign-in instead of silently logging out.
* Every data panel has four distinct states: *Loading*, *Data unavailable* (request failed: backend, session or external source), *No data* (request succeeded
  but nothing exists, with how to load it) and *No match* (filters too restrictive). Unhandled server errors return a generic message (never a traceback) with CORS
  headers so the browser can display it.

## 12. Review demonstration path

1. **Dashboard** (`/`): data-status banner (latest observation date, forecast issued from, coverage), ocean conditions, forecast, marine heatwaves, biodiversity,
   ecological risk and alerts, each with a link; "What does this mean?".
2. **Marine Heatwaves** (`/heatwaves`): definition and "How is this detected?", 8 active events; click the event near 34.5N, 120.8W (small, coastal, +2.5 degC).
3. Read its **evidence**: duration, maximum and cumulative intensity, 60-day timeline, forecast persistence, and the **species with records in the area**
   (13 species including conservation-sensitive ones, e.g. sea otter, great white shark).
4. **Species** (`/species`): search "shark" or "turtle", filter by conservation status; open **Great white shark** (68% of its recorded positions currently >= 1 degC from
   normal, risk MEDIUM) and compare with **Green turtle** (Least Concern per GBIF, with the OBIS discrepancy shown).
5. On the species page read: conservation status and source, observations and map, potential environmental exposure, ecological risk factors and "Why?".
6. **Ecological Risk** (`/ecological-risk`): areas, species ranking, methodology (weights and limitations).
7. **Alerts** (`/alerts`): open the heatwave alert, expand "Why this alert?", read the evidence and sources; acknowledge/resolve (researcher role).
8. **Ocean Data** (`/ocean-data`) and **Model Performance** (`/performance`) for data provenance and the ML evidence (14.5% lower MAE than persistence).
