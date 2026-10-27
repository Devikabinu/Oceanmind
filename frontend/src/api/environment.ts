import { apiClient } from "./client";

export type EnvironmentLayer = "sst" | "anomaly";
/** One grid value as sent by the backend: null means land, missing data or outside the selected region. Never 0. */
export type EnvironmentMapCell = number | null;

export interface EnvironmentProvider {
  provider_id: string;
  provider_type: string;
  is_observational: boolean;
  description: string;
  /** Where the data come from (observational sources): organisation, dataset, reference links, citation, update cadence and the newest final/preliminary days. */
  source?: {
    provider?: string;
    short_name?: string;
    dataset?: string;
    urls?: string[];
    reference_url?: string;
    citation?: string;
    final_through?: string | null;
    preliminary_through?: string | null;
    synced_at?: string | null;
    update_frequency?: string;
  } | null;
  notes?: string[];
}

export interface EnvironmentFreshness {
  days_behind: number;
  status: "current" | "delayed" | "stale";
  message: string;
  observation_date: string;
}

export interface EnvironmentExtent {
  lat_min: number;
  lat_max: number;
  lon_min: number;
  lon_max: number;
}

export interface EnvironmentDatasetInfo {
  id: string;
  name: string;
  kind: string;
  is_default: boolean;
  provider: EnvironmentProvider;
  extent: EnvironmentExtent;
  resolution_deg: number;
  units: string;
  lon_convention: string;
  grid_shape: [number, number];
  total_cells: number;
  valid_cells: number;
  latest_date: string;
  first_date: string;
  n_dates: number;
  layers: Record<EnvironmentLayer, { label: string; unit: string }>;
  variable?: string;
  temporal_resolution?: string;
  baseline?: [string, string] | null;
  climatology?: string | null;
  processing?: string;
  update_method?: string;
  limitations?: string[];
  freshness?: EnvironmentFreshness;
  processed_at?: string;
  source_timestamp?: string | null;
  preliminary_from?: string | null;
}

export interface EnvironmentDatasetAvailable extends EnvironmentDatasetInfo {
  available: true;
}

export interface EnvironmentDatasetUnavailable {
  available: false;
  id: string;
  name: string;
  kind: string;
  is_default: boolean;
  message: string;
}

export type EnvironmentDataset = EnvironmentDatasetAvailable | EnvironmentDatasetUnavailable;

export interface EnvironmentDatasets {
  default: string;
  datasets: EnvironmentDataset[];
}

export interface EnvironmentRegion {
  id: string;
  name: string;
  description: string;
  parent: string | null;
  children: string[];
  dataset_wide: boolean;
  boxes: EnvironmentExtent[];
  crosses_antimeridian: boolean;
  /** Suggested map view in the backend continuous east-longitude convention (values above 180 are west longitudes). */
  map_extent: (EnvironmentExtent & { lon_convention: string }) | null;
  overlap_note: string | null;
}

export interface EnvironmentRegions {
  regions: EnvironmentRegion[];
}

export interface EnvironmentDates {
  dataset: string;
  latest_date: string;
  first_date: string;
  n_dates: number;
  provider: EnvironmentProvider;
}

export interface CoverageCounts {
  total_cells: number;
  land_cells: number;
  ocean_cells: number;
  valid_cells: number;
  missing_cells: number;
  valid_pct_of_ocean: number | null;
  valid_pct_of_region: number | null;
  ocean_pct_of_region: number | null;
}

export interface EnvironmentBBox {
  min_lat: number;
  max_lat: number;
  min_lon: number;
  max_lon: number;
}

export interface EnvironmentCoverage {
  dataset: EnvironmentDatasetInfo;
  layer: EnvironmentLayer;
  region: { id: string; name: string };
  bbox: EnvironmentBBox | null;
  requested_date: string;
  date: string;
  latest_available_date: string;
  extent: EnvironmentExtent;
  coverage: CoverageCounts;
  overlaps_dataset: boolean;
}

export interface EnvironmentMapResponse {
  dataset: EnvironmentDatasetInfo;
  layer: EnvironmentLayer;
  label: string;
  unit: string;
  diverging: boolean;
  kind: "observed" | "generated";
  requested_date: string;
  date: string;
  latest_available_date: string;
  region: { id: string; name: string };
  bbox: EnvironmentBBox | null;
  coverage: CoverageCounts;
  status_legend: Record<string, string>;
  lat: number[];
  lon: number[];
  values: EnvironmentMapCell[][];
  min: number | null;
  max: number | null;
  downsample_factor: number;
  native_shape: [number, number];
  lon_convention: string;
  message?: string;
}

export interface EnvironmentQuery {
  dataset: string;
  layer: EnvironmentLayer;
  /** "latest" (default) or YYYY-MM-DD. */
  date?: string;
  region: string;
}

/** Cells to ask the backend for. It block-averages to this size, so the browser never receives (or aggregates) the full grid. */
export const MAP_MAX_CELLS = 20_000;

const get = async <T>(path: string, params?: Record<string, string | number | undefined>): Promise<T> =>
  (await apiClient.get<T>(`/environment${path}`, { params })).data;

const isObject = (v: unknown): v is Record<string, unknown> => typeof v === "object" && v !== null && !Array.isArray(v);

/** Reject responses that do not have the documented shape instead of rendering them. */
export function assertMap(m: unknown): asserts m is EnvironmentMapResponse {
  const bad = (why: string) => new Error(`The environmental map response was malformed (${why}).`);
  if (!isObject(m)) throw bad("not an object");
  if (!Array.isArray(m.lat) || !Array.isArray(m.lon) || !Array.isArray(m.values)) throw bad("missing lat/lon/values");
  if (m.values.length !== m.lat.length) throw bad("row count differs from latitude count");
  if (!m.values.every((r) => Array.isArray(r) && r.length === (m.lon as unknown[]).length)) throw bad("row length differs from longitude count");
  if (typeof m.date !== "string" || !isObject(m.dataset) || !isObject(m.region) || !isObject(m.coverage)) throw bad("missing date/dataset/region/coverage");
}

export const getDatasets = () => get<EnvironmentDatasets>("/datasets");
export const getRegions = () => get<EnvironmentRegions>("/regions");
export const getDates = (dataset: string) => get<EnvironmentDates>("/dates", { dataset });
export const getCoverage = (q: EnvironmentQuery) =>
  get<EnvironmentCoverage>("/coverage", { dataset: q.dataset, layer: q.layer, date: q.date ?? "latest", region: q.region });
export async function getMap(q: EnvironmentQuery, maxCells = MAP_MAX_CELLS): Promise<EnvironmentMapResponse> {
  const body: unknown = await get<unknown>("/map", { dataset: q.dataset, layer: q.layer, date: q.date ?? "latest", region: q.region, max_cells: maxCells });
  assertMap(body);
  return body;
}

export type PointStatus = "valid" | "land" | "missing" | "outside_dataset";

/** /api/environment/point: values at one coordinate. sst / anomaly are null unless the cell has data (never 0). */
export interface EnvironmentPoint {
  dataset: EnvironmentDatasetInfo;
  query: { lat: number; lon: number };
  status: PointStatus;
  in_coverage: boolean;
  is_ocean: boolean | null;
  message: string | null;
  date: string;
  latest_available_date: string;
  unit: string;
  layer: EnvironmentLayer | null;
  lon_convention: string;
  coverage: EnvironmentExtent;
  provider: EnvironmentProvider;
  kind: "observed" | "generated";
  cell: { lat: number; lon: number; lon_180: number; row: number; col: number } | null;
  sst: number | null;
  anomaly: number | null;
}

export interface EnvironmentSummary {
  dataset: EnvironmentDatasetInfo;
  layer: EnvironmentLayer;
  label: string;
  unit: string;
  region: { id: string; name: string };
  date: string;
  latest_available_date: string;
  mean: number | null;
  min: number | null;
  max: number | null;
  coverage: CoverageCounts;
  provider: EnvironmentProvider;
  kind: "observed" | "generated";
}

export const getSummary = (dataset: string, layer: EnvironmentLayer, region: string, date?: string) =>
  get<EnvironmentSummary>("/summary", { dataset, layer, region, date });

export interface ForecastExplanation {
  headline: string;
  sections: { id: string; title: string; text: string; bullets: string[] }[];
}

export interface DatasetForecast {
  dataset: string;
  dataset_generated: boolean;
  region: { id: string; name: string };
  issued_from: string;
  target_dates: string[];
  horizons: number[];
  last_observed_sst: number | null;
  last_observed_climatology: number | null;
  last_observed_anomaly: number | null;
  forecast_sst: (number | null)[];
  climatology_sst: (number | null)[];
  persistence_sst: (number | null)[];
  forecast_anomaly: (number | null)[];
  typical_error_c: number[] | null;
  model: { name: string; checkpoint: { which: string; epoch: number | null; val_loss: number | null }; origin: { origin: string; trained_on: string; retrained: boolean; note?: string } | null; retrained_for_this_dataset: boolean };
  performance: {
    split: string;
    date_range: [string, string];
    n_windows: number;
    horizons: number[];
    models: Record<string, { mae: number[]; rmse: number[]; r2: number[]; mean_mae: number; mean_rmse: number }>;
    mae_skill_vs_persistence: number[];
    beats_persistence: boolean;
    evaluated_on: string;
  } | null;
  note: string;
  unit: string;
  explanation: ForecastExplanation;
}

export const getForecast = (dataset: string, region: string) => get<DatasetForecast>("/forecast", { dataset, region });
export const getForecastMap = (dataset: string, horizon: number, region: string, kind: EnvironmentLayer) =>
  get<{
    dataset: string;
    label: string;
    unit: string;
    horizon: number;
    date: string;
    issued_from: string;
    diverging: boolean;
    region: { id: string; name: string };
    coverage: EnvironmentExtent;
    lat: number[];
    lon: number[];
    values: EnvironmentMapCell[][];
    min: number | null;
    max: number | null;
  }>("/forecast/map", { dataset, horizon, region, kind });

export const getPoint = (dataset: string, lat: number, lon: number, date: string, layer?: EnvironmentLayer) =>
  get<EnvironmentPoint>("/point", { dataset, lat, lon, date, layer });

// ---- the one report for a clicked place, and the species layer ----------------------------------------------------------------
export interface ReportSection {
  id: string;
  title: string;
  text: string;
  bullets: string[];
}

export interface ReportExplanation {
  headline: string;
  sections: ReportSection[];
}

export interface ReportEvent {
  id: string;
  start_date: string;
  duration_days: number;
  area_km2: number;
  cells: number;
  category: number;
  category_name: string;
  current_anomaly_c: number;
  max_anomaly_c: number;
  cumulative_intensity_c_days?: number;
  max_cumulative_intensity_c_days?: number;
  historical_percentile?: number;
  risk_in_event?: { cells_assessed: number; mean_score: number | null; share_high_or_critical: number | null };
  affected_species?: { scientific_name: string; common_name: string | null; n_records: number; conservation_status: string }[];
  ecological_relationship?: string;
}

export interface ReportDriver {
  factor: "anomaly" | "persistence" | "forecast" | "overlap";
  label: string;
  weight: number;
  available: boolean;
  value: number | null;
  level: "LOW" | "MEDIUM" | "HIGH" | null;
  contribution: number | null;
  weight_share: number | null;
  status: string;
  explanation: string;
}

export interface ReportSpecies {
  aphia_id: number | null;
  scientific_name: string;
  common_name: string | null;
  taxon_group: string | null;
  conservation_status: string;
  conservation_source: string | null;
  conservation_sensitive: boolean;
  n_records: number;
  nearest_km: number;
  latest_record: string | null;
  records_in_heatwave: number | null;
  mean_anomaly_c: number | null;
  highest_risk_level: string | null;
  source: string;
}

export interface ReportAlert {
  id: string;
  alert_type: string;
  severity: "LOW" | "MEDIUM" | "HIGH" | "CRITICAL";
  message: string;
  timestamp: string;
  status: string;
  region: string | null;
  latitude: number;
  longitude: number;
  reasons: string[];
  evidence_summary: { label: string; value: string }[];
  same_event: boolean;
  distance_km: number;
}

export interface LocationReportData {
  dataset: string;
  date: string;
  latest_available_date: string;
  query: { lat: number; lon: number };
  status: PointStatus;
  message: string | null;
  cell: { lat: number; lon: number; lon_180: number; row: number; col: number } | null;
  provider: EnvironmentProvider;
  kind: "observed" | "generated";
  region?: { id: string; name: string; contains: string[] };
  conditions?: { sst: number | null; normal_sst: number | null; anomaly: number | null; unit: string };
  anomaly?: { value: number | null; class: string | null; region_percentile: number | null; historical_percentile?: number | null; historical_samples?: number; neighbourhood_mean?: number | null; explanation: ReportExplanation };
  heatwave?: {
    available: boolean;
    inside: boolean | null;
    message: string;
    run_days?: number;
    event_id?: string;
    event_region?: string;
    event?: ReportEvent | null;
    why_it_matters?: string;
    baseline?: [string, string];
    latest_computed?: string;
  };
  risk?: {
    status: string;
    message?: string;
    score?: number | null;
    level?: "LOW" | "MEDIUM" | "HIGH" | "CRITICAL" | null;
    evidence_completeness?: number | null;
    drivers?: ReportDriver[];
    biodiversity_evidence?: string;
    explanation?: ReportExplanation;
  };
  species?: { items: ReportSpecies[]; summary: string; evidence: string; radius_deg: number };
  forecast?: {
    available: boolean;
    message?: string;
    issued_from?: string;
    dates?: string[];
    forecast_sst?: number[];
    climatology?: number[];
    forecast_anomaly?: number[];
    current_sst?: number | null;
    change_c?: number;
    direction?: "warming" | "cooling" | "stable";
    typical_error_c?: number[] | null;
    model?: string;
    trained_on?: string | null;
    beats_persistence?: boolean | null;
    summary?: string;
    interpretation?: string[];
    persistence_sst?: number[] | null;
  };
  alerts?: ReportAlert[];
}

export const getReport = (dataset: string, lat: number, lon: number, date?: string) => get<LocationReportData>("/report", { dataset, lat, lon, date });

export interface SpeciesPoint {
  aphia_id: number | null;
  scientific_name: string;
  common_name: string | null;
  taxon_group: string | null;
  conservation_status: string;
  conservation_source: string | null;
  lat: number;
  lon: number;
  lon_180: number;
  n_records: number;
  latest: string | null;
  alert_severity?: string | null;
  anomaly_c: number;
  in_heatwave: boolean;
  risk_level: string | null;
  source: string;
}

export interface SpeciesLayer {
  dataset: string;
  date: string;
  region: { id: string; name: string };
  items: SpeciesPoint[];
  heatwave_computed: boolean;
  summary: { points: number; species: number; records: number; points_in_heatwave: number; points_high_risk: number; conservation_sensitive_species: number; threatened_in_heatwave: number; with_alert: number };
  note: string;
}

export const getSpeciesLayer = (dataset: string, region: string, date?: string) => get<SpeciesLayer>("/species-layer", { dataset, region, date });

export interface SpeciesExposure {
  available: boolean;
  message?: string;
  aphia_id: number;
  scientific_name: string;
  common_name: string | null;
  conservation_status: string;
  conservation_source: string | null;
  explanation?: ReportExplanation;
}

export const getSpeciesExposure = (aphiaId: number, dataset: string, date?: string) => get<SpeciesExposure>("/species-exposure", { aphia_id: aphiaId, dataset, date });

// ---- anomaly analysis -------------------------------------------------------------------------------------------
export interface AnomalyCell {
  lat: number;
  lon: number;
  lon_180: number;
  anomaly_c: number;
  region: { id: string; name: string };
  historical_percentile: number | null;
  historical_samples: number;
}
export interface PersistentAnomaly {
  lat: number;
  lon: number;
  lon_180: number;
  days: number;
  anomaly_c: number;
  direction: "warm" | "cold";
  region: { id: string; name: string };
  capped: boolean;
}
export interface AnomalyAnalysis {
  dataset: EnvironmentDatasetAvailable;
  region: { id: string; name: string };
  date: string;
  latest_available_date: string;
  baseline: [string, string] | null;
  threshold_c: number;
  summary: { mean_anomaly_c: number | null; valid_cells: number; share_warm: number | null; share_cold: number | null; persistent_cells: number; persistent_share: number | null };
  strongest_warm: AnomalyCell[];
  strongest_cold: AnomalyCell[];
  persistent: PersistentAnomaly[];
  persistence_min_days: number;
  timeline: { dates: string[]; mean_anomaly_c: number[]; share_warm: number[]; share_cold: number[] };
  regions: { id: string; name: string; mean_anomaly_c: number; share_warm: number; share_cold: number; valid_cells: number }[];
  method: string;
  limits: string[];
}
export const getAnomalyAnalysis = (dataset: string, region: string, date?: string) => get<AnomalyAnalysis>("/anomaly-analysis", { dataset, region, date });
