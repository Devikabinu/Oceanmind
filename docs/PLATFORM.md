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
NOAA / OBIS  backend ingestion adapters  ---------> datasets, ocean_observations,  /api/ingestion, /datasets, ...   Dashboard, Map,
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
| `OBIS_API_BASE_URL`, `NOAA_OISST_BASE_URL`  | Source endpoints / credentials (see `.env.example`) |
| `VITE_API_BASE_URL` | Frontend API base (default `http://localhost:8000/api`) |

## 4. Data sources and coverage

| Source | What | Coverage of the source | Loaded in this project | Updated |
|---|---|---|---|---|
| NOAA OISST v2.1 (NOAA NCEI, via NOAA CoastWatch ERDDAP, gap days from the NCEI archive) | Daily SST analysis (observed) | Global ocean, 0.25 degree, 1981-present | Pacific Ocean 60S-65N, 100E-70W, every fourth cell (1 degree), 2002 to the latest day; NE Pacific study region at 0.25 degree | Daily; final product about 2 weeks behind, preliminary about 2 days (preliminary days are flagged) |
| NOAA CPC Oceanic Nino Index; NOAA NCEI PDO index | Monthly climate indices | Basin-wide | Used only as labelled context in anomaly explanations | Monthly |
| OBIS | Species occurrence records | Global, uneven effort | A time-spread selection of records per watch-list species across the Pacific (`sync-biodiversity --region pacific`) | On demand |
| WoRMS / GBIF | Taxonomy, English common names | n/a | Per catalogued species | On demand |
| GBIF species API / OBIS red-list checklist | IUCN Red List category (CR/EN/VU/NT/LC/DD/NE) | Species with an IUCN assessment | Per catalogued species | On demand |
| Project ConvLSTM | 7-day SST forecast (model output) | Pacific Ocean | Issued from the last processed day; weights trained on the NE Pacific | With every refresh |

Everything shown on the Ocean Map comes from these. Where a source has nothing for a place or day the interface says "Data unavailable" or "Insufficient evidence"; it never
shows zero for missing data.

### Refreshing the Pacific data (reproducible, no code changes)

`python scripts/refresh_pacific.py` runs the pipeline in order and is safe to repeat:

1. **sync** (`python -m oceanmind_environment sync --config config.pacific.yaml`): downloads NOAA OISST in two longitude windows (100E-180 and 180-70W) so the 180th meridian is
   never split, samples every fourth cell, validates every file (units, dimensions, value range, expected days) and merges them onto one contiguous east-longitude axis.
   Complete years and months are cached under `cache/pacific_oisst/` and never downloaded again; only the recent tail is refreshed. Days the ERDDAP aggregation lacks are taken
   from the NCEI daily files. The merged store is `data/pacific_oisst/sst.zarr`; it records which days are preliminary and when it was retrieved.
2. **climate**: ONI and PDO index files.
3. **build** (`oceanmind_preprocess`): land mask, missing-value handling, climatology and anomaly, features and splits, written to `processed_pacific/`. Skipped when the processed data
   already reach the latest source day.
4. **evaluate** (`oceanmind_model evaluate` + `export-dashboard`): forecast and its persistence comparison, marine heatwaves (the current ones and every historical event with its
   daily footprint), and the point-history files.
5. **alerts**: heatwave, extreme/rapid/persistent anomaly, ecological-risk, species-exposure and forecast alerts.
6. **species** (optional, `--species`): OBIS records and IUCN categories for the Pacific watch list.

Freshness: every dataset reports its observation date, the retrieval time of its source and how many days old the newest observation is (current / delayed / stale); the
interface shows these on Ocean Data and never presents an older date as today.

#### Automatic daily refresh and versioned publication
`scripts/daily_refresh.py` is what the scheduler runs. It asks NOAA for the newest day (never a fixed date; ERDDAP lists, and the NCEI daily files cover days the aggregation lacks), downloads only
what is missing, validates it, and rebuilds only when the processed dataset is older than the newest valid observation or its products disagree. Retries and timeouts apply to every request; a day
that is not published yet (HTTP 404) is reported missing, never filled. An unreachable source, a malformed or partial download, or an older record than the stored one leaves the previous valid store
in place. Running it again with nothing new changes nothing (the stored record is only replaced when it differs).

A rebuild never writes into the dataset being served. `refresh_pacific.py --only build` builds the cubes, climatology, anomalies, the 7-day forecast issued from the newest observation (valid dates:
the day after it, for seven days) and the marine heatwaves in `processed_pacific.staging/`, checks that every product ends on the same day, and swaps the directory in one step
(`oceanmind_environment/publish.py`; the previous generation is kept until the swap succeeds, an interrupted swap is repaired at the next start). If any step fails, the live dataset is untouched and the
status says so. The forecast files carry a generation id so that the API never combines `snapshot.npz` and `snapshot.json` from different refreshes, and the forecast, explanation and SST-history
caches follow the files they were read from.

`data/refresh_status.json` records every attempt: outcome (updated / unchanged / source_unavailable / failed), the latest source observation, the latest processed observation, the last successful
refresh and the forecast dates. The interface shows them under the data note ("Latest source observation", "Latest observation processed", "Last successful refresh", "Data state": current,
delayed or refresh failed). A lock file holding the process id stops two runs at once; a lock left by a killed run is ignored.

Scheduling (Windows): `powershell -ExecutionPolicy Bypass -File scripts\install_daily_task.ps1` registers the task "OceanMind daily SST refresh" (07:00 daily, repeated every 6 hours for 18 hours,
run when next available if the computer was off, one instance at a time); `-Remove` unregisters it. Log: `logs/daily_refresh.log`. On a server use cron or a systemd timer to run
`python scripts/daily_refresh.py` the same way.

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

**Reading a score (location report, "Why this risk?").** Per factor the report shows the measured quantity (°C, days, species), the 0-1 factor, the nominal and
effective weight, and the contribution; the score is `sum(weight x factor) / sum(weights of the factors that are present)`, so the contributions add up to the score.
A factor has one of four statuses: *contributing*; *below threshold* (evidence present, factor < 0.33; in the score at a low value, never "insufficient");
*incomplete* (e.g. a forecast for fewer than 7 days; used as far as it goes); *unavailable* (the input does not exist for this cell or date; the report names the missing
input, the factor is left out and never counted as 0 or 1). A factor of 1.00 means the measured value reached its saturation point (3 °C, 14 days, 3 species); the raw value
is still shown and the factor is labelled "capped". A forecast or heatwave result is used only when it was computed for the selected observation day.

**Species counts** always name what is counted: "Species observations within about 5° of this location (last 2 years): N; distinct species: M" (stored OBIS observations
in the window). The catalogue-wide number of species with stored records is a different quantity and is labelled as such. No observations in the area/period gives
"Insufficient evidence", never 0.

**Explain this forecast** (`GET /api/environment/forecast-explain`, `/forecast-model`, `/data-dates`). Observed inputs (the 7-day window, climatology, anomaly, trend),
the model prediction for +1..+7 days with typical test error, and a sensitivity analysis run through the trained ConvLSTM (`python -m oceanmind_model explain`):
the anomaly is replaced by normal conditions on one input day / locally / everywhere / in 8° blocks and the change of the forecast is measured. This is sensitivity, not
causation; currents, winds, ENSO or upwelling are not inputs of the model and are never named as causes. The Pacific dataset is converted to the scale the NE-Pacific weights
were trained with (`oceanmind_model/normalisation.py`) before the model runs.

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

### 5.5 External biodiversity and ocean context (location report)
The location report adds two kinds of context that are **not** inputs of the ConvLSTM and **not** part of the risk score:

* **Biodiversity from the OBIS API** (`https://api.obis.org/v3`; `app/services/obis_service.py`, `obis_live.py`, `biodiversity_view.py`). For a clicked place the service tries boxes of ±0.5° (local), ±2° and ±5°
  (nearby), ±10° and ±20° (regional) and ±40° (regional Pacific) and uses the smallest one with at least 25 records, among the last two years first; older records are used, and labelled historical, only when no
  box has recent ones. It returns record and species counts, taxonomic groups, species with the IUCN Red List category that OBIS carries, distance and date of the nearest and latest record. The recorded places are
  overlaid on the current marine-heatwave footprint and on the area where the 7-day forecast anomaly is at least 1 °C in either direction: *potential exposure*, never damage. Results are cached on disk
  (`data/cache/biodiversity`, 7 days); a click on an uncached place starts a background fetch, waits a few seconds, and otherwise shows the project's stored OBIS records until the fetch finishes. Requests are
  rate-limited, time-limited and retried; when OBIS cannot be reached the previous cached answer (marked stale) or the stored records are used.
* **Chlorophyll-a and surface currents from NOAA ERDDAP** (`app/services/ocean_context.py`): NOAA S-NPP VIIRS chlorophyll-a (`noaa_snpp_chla_daily` for the last 30 days and `noaa_snpp_chla_monthly` for the same
  month of earlier years, served by NOAA PIFSC) and geostrophic currents from altimetry (`noaacwBLENDEDNRTcurrentsDaily`, NOAA CoastWatch). Each value carries its dataset, observation date and resolution;
  ocean-colour data lag the SST by about ten days and have gaps under cloud. Caches live in `data/cache/ocean_context` (12 hours).

The risk score still uses the project's stored OBIS selection (distinct species per 2×2° block, saturating at 3 species) and the forecast still uses only its documented inputs. `scripts/warm_external_cache.py` fills the caches
ahead of time for chosen places or a grid.

### 5.6 Physical explanation of an SST anomaly (Explainable AI, part B)
The Explainable AI panel has two parts. **A. Model explanation** is what the ConvLSTM predicts and what the trained network responds to (a sensitivity analysis; never a physical cause). **B. Physical
explanation** (`app/services/physical_drivers.py`, `physical_analysis.py`, `physical_report.py`; `GET /api/environment/physical-drivers`) compares the observed anomaly with measured environmental indicators and
says which mechanisms they are consistent with, which they argue against and which cannot be assessed. Every source below was checked for variables, dates and coverage before use, and is fetched and cached on its own
(12 h for current data, 90 days for baselines; background fetch; a failing source leaves the others in place and the SST map, dashboard and forecast untouched).

| Indicator | Source and dataset | Coverage used | Notes |
|---|---|---|---|
| Wind, wind stress | RSS CCMP v2.1 near-real-time winds, NOAA PIFSC ERDDAP `ccmp-daily-v2-1-NRT` | 6-hourly, 0.25°, 2015 to 2026-10-27; baseline = the same 7 days of 2016-2025 | stress derived with the Large and Pond bulk formula; Ekman transport (tau/(rho f)) is undefined within 3° of the equator |
| Sea level anomaly | NOAA CoastWatch blended altimetry `noaacwBLENDEDsshDaily` (SLA, m, relative to the DTU15 long-term mean sea surface; the seasonal cycle is **not** removed) | daily, 0.25°, 2015-01-15 to 2026-10-27; compared with the 7 same calendar days of 2016-2025 | proxy for upper-ocean heat content; only the departure from the same days of other years is interpreted; eddies and non-thermal effects also change it |
| Surface currents | NOAA CoastWatch `noaacwBLENDEDNRTcurrentsDaily` | daily, 0.25°, to 2026-10-26/27 | geostrophic only (no wind-driven part); advective tendency = −u·∇T with the OISST gradient; not interpreted within 3° of the equator |
| ENSO | NOAA CPC `sstoi.indices` (Niño 3.4) and the Oceanic Niño Index | monthly | context only; "consistent" is used only in the central and eastern tropical Pacific (15°S-15°N, 160°E-80°W) |
| Surface radiation and humidity | NASA POWER daily point API (`ALLSKY_SFC_SW_DWN`, `ALLSKY_SFC_LW_DWN`, `T2M`, `QV2M`, `PS`) | daily, last valid day about 8 days behind; baseline = the same 7 days of 2016-2025 | with the CCMP wind and the OISST of the same seven days it gives a **bulk estimate** of the surface heat-flux anomaly (shortwave, downward and upward longwave, latent and sensible heat; Ce = Ch = 1.2e-3, albedo 0.06), it is an estimate that has not been validated against measured fluxes in this project (no error bound is claimed), not a measured flux |
| Normal heat flux | NCEP/NCAR Reanalysis 1 (NOAA PSL THREDDS), 1991-2020 daily **climatology** | normal net flux for the forecast week | the 2026 reanalysis files end in March 2026 and are not used |

Not integrated because they could not be verified as current: the CoastWatch blended NRT winds (end 2023), the NCEP reanalyses (end early 2026), the `upwell` ERDDAP server (unreachable at times). Coastal upwelling is judged
from the Ekman transport normal to a coastline estimated from the 0.25° land mask; open-ocean upwelling would need the stress curl and is reported as not assessable.

Verdicts are `consistent`, `not consistent`, `inconclusive` or `not assessable`, from fixed thresholds listed in the panel ("How each verdict is decided"). Advection is compared with the anomaly (a current that warms a warm anomaly is consistent; the sign of the observed trend is reported separately) and includes the normal advection already part of the normal SST. The equatorial upwelling rule applies only where the normal stress is easterly. Each source table row gives the day actually used (not only the source's last day). Evidence strength counts independent data families (wind and
upwelling share one wind field). No verdict is "cause established"; the ConvLSTM was not retrained and does not use any of these variables.

#### Interpretation layer (`physical_interpretation.py`, `ai_providers.py`)
The first view of part B is a written interpretation: why the area is warmer or cooler than normal, the (at most three) leading mechanisms with their measurements, what the data show, what may happen next
(from the actual SST forecast; the driver values are observations, never forecasts), possible marine implications (measured facts kept apart from general scientific context) and a qualitative confidence level with
its criteria. Everything else (dates, the full evidence table, charts, per-mechanism verdicts, sources, method) sits under "Evidence and limitations".

1. **Evidence package.** `build_package` collects only values already retrieved (SST, anomaly and trends, seasonal versus anomalous change over the last days, heatwave state, forecast days, winds, radiation/heat flux,
   sea level, currents, ENSO, source dates and lags), each with an id (E1, E2, ...). Nothing is estimated or filled in.
2. **Deterministic narrator.** `narrate` writes the interpretation from the package alone, with no external service. It is always computed and is what is shown when no AI provider is configured or the provider fails.
3. **Optional AI provider.** Off by default (`AI_PROVIDER=none`). Configure in the backend `.env` only: `AI_PROVIDER=anthropic` (with `AI_API_KEY`, `AI_MODEL`, optional `AI_BASE_URL`) or `AI_PROVIDER=openai_compatible`
   (with `AI_MODEL`, `AI_BASE_URL`, optional `AI_API_KEY`, e.g. a local server); `AI_TIMEOUT_S` bounds each call. The key never reaches the browser. The provider receives only the evidence package (no user data); the
   prompt says its content is data, not instructions. It is called in a background thread, so the report never waits for it; the result is cached on disk under `data/cache/physical_ai` by a hash of provider, prompt
   version and package, and a failure is not retried for ten minutes.
4. **Validation.** Any text (AI or narrator) is checked against the package before it is shown: the required shape, at most three mechanisms, evidence ids that exist, every number present in the package,
   no causal verbs or "will continue" claims about drivers, no damage reported, a mechanism described as supported by local measurements only when its verdict is "consistent" with its own evidence ids, general
   context citing no measurement, and the confidence level identical to the deterministic one. Output that fails is discarded and the narrator's text is shown with a note. Generated text never changes a measured value,
   the forecast or the risk score.

This repository has been verified with the deterministic narrator and with test doubles for the provider; no commercial provider was configured or called in development, so none is claimed as integrated.

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
