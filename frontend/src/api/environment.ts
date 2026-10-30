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
  status: "current" | "delayed" | "stale" | "refresh failed";
  message: string;
  observation_date: string;
  expected_date?: string;
  behind_expected?: number;
  lag_days?: number;
  /** Outcome of the last automatic refresh, when one has run. */
  refresh?: { attempted_at: string; outcome: "running" | "updated" | "unchanged" | "source_unavailable" | "failed" | "interrupted"; message: string; latest_observation: string | null; expected_latest: string | null; forecast_dates: string[] | null; consistent: boolean | null; problems: string[] | null;
    source_latest?: string | null; processed_latest?: string | null; last_success_at?: string | null; last_update_at?: string | null; source_checked_at?: string | null } | null;
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
  forecast_methodology?: string;
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
  /** contributing | below_threshold | incomplete | unavailable: why the driver is, or is not, in the score. */
  status: "contributing" | "below_threshold" | "incomplete" | "unavailable";
  status_text?: string;
  effective_weight?: number | null;
  value_exact?: number;
  /** The measured quantity the factor is made from (°C, days, species) and the value at which the factor reaches 1.00. */
  raw?: number | null;
  raw_unit?: string;
  saturation_at?: number;
  saturated?: boolean | null;
  ratio?: number | null;
  missing_input?: string;
  classification?: string;
  detail_lines?: string[];
  normalization?: string | null;
  scope?: string | null;
  distance_deg?: number | null;
  evidence_detail?: { observations: number; species: number; latest: string | null; window_days: number };
  explanation: string;
}

export interface EvidenceKinds {
  [kind: string]: string;
}
export interface KindedStatement {
  kind: string;
  label: string;
  text: string;
}
export interface DataDates {
  sst_observation: { date: string; latest_available: string; note: string };
  anomaly: { date: string; baseline: [string, string] | null };
  marine_heatwave: { date: string | null };
  forecast: { initialised_from: string | null; valid_dates: string[] | null };
  species_records: { latest_record: string | null; window_days: number };
  aligned: boolean;
  message: string;
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

export interface ObisItem {
  scientific_name: string; common_name: string | null; group: string | null; conservation_status: string; threatened: boolean; records: number; nearest_km: number | null;
  latest_record: string | null; recency: string; scope_label: string; records_in_heatwave: number | null; records_in_forecast_area: number | null; sampled_records: number; datasets: string[];
}
export interface ExposureShare { available: boolean; records: number; species: number; threatened_species: number; share_pct: number | null; cells?: number; cells_share_pct?: number | null; species_share_pct?: number | null; threshold_c?: number }
export interface ObisBlock {
  available: boolean; status?: string; message?: string | null; scope?: string; scope_label?: string; half_width_deg?: number; historical?: boolean; window?: { start: string | null; end: string };
  label?: string; trail?: { half_width_deg: number; scope: string; records: number; window: string }[];
  counts?: { observations: number; observations_all_time: number; distinct_species: number; threatened_species: number; taxa: number; sampled_records: number; density_per_1000_km2: number };
  groups?: { group: string; species: number; records: number }[]; items?: ObisItem[]; threatened?: ObisItem[];
  exposure?: { records_in_domain: number; species_in_domain?: number; cells_in_domain?: number; densest_cell_share_pct?: number | null; heatwave: ExposureShare; forecast: ExposureShare } | null; exposure_text?: string | null;
  provenance?: Record<string, string>; caveats?: string[];
}
export interface ChlorophyllInfo {
  available: boolean; message?: string; text?: string; source: string; dataset: string; unit: string; spatial_resolution: string; temporal_resolution: string; dataset_end: string; retrieved?: string;
  latest?: { value: number; date: string }; recent_mean?: number; valid_days?: number; change_pct?: number | null; history?: { percentile: number; median: number; years: number; month: number; dataset: string };
}
export interface CurrentsInfo {
  available: boolean; message?: string; text?: string; caveat?: string; source: string; dataset: string; unit: string; spatial_resolution: string; temporal_resolution: string; dataset_end: string; retrieved?: string;
  latest?: { date: string; speed: number; direction_deg: number; u: number; v: number }; speed_change?: number | null; direction_change_deg?: number | null;
}
export interface OceanContextBlock { status?: string; chlorophyll: ChlorophyllInfo | null; currents: CurrentsInfo | null; errors?: string[] }
export interface SourceRow { topic: string; source: string; dataset: string | null; observation_date: string | null; spatial_resolution: string | null; temporal_resolution: string | null; retrieved: string | null }
export interface ReportTrends { days: number; sst_3d_c_per_day: number; sst_7d_c_per_day: number; anomaly_3d_change_c: number; anomaly_7d_change_c: number; from: string; to: string }
export interface SpatialPattern { half_deg: number; cells: number; mean_anomaly_c: number; share_warm_pct: number; share_cold_pct: number; label: string; relative_to_surroundings: string | null; text: string }

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
    analysis?: { active: boolean | null; status?: string | null; lines: string[]; trend: string | null; continuation: string | null };
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
    score_breakdown?: { terms: { factor: string; contribution: number }[]; sum: number | null; denominator_weight: number; formula: string; text: string | null };
  };
  species?: { items: ReportSpecies[]; summary: string; evidence: string; radius_deg: number;
    counted?: { observations: number; distinct_species: number; listed: number; radius_deg: number; window_days: number; latest_record: string | null; label: string; scope?: string; historical?: boolean; earliest_record?: string | null } };
  data_dates?: DataDates;
  analysis?: { recent_anomaly: { date: string; anomaly_c: number; sst_c?: number }[]; trends?: ReportTrends | null; spatial_pattern?: SpatialPattern | null; risk_dominance?: string | null;
    why_forecast: { direction: string; headline: string; bullets: KindedStatement[] } | null };
  obis?: ObisBlock | null;
  context?: OceanContextBlock | null;
  sources?: SourceRow[];
  refresh_hint_s?: number | null;
  implications?: { available: boolean; items: KindedStatement[]; caveat?: string; message?: string; kinds: EvidenceKinds };
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
    reading?: { label: string; anomaly_label: string; sst_change_c: number; peak_day: number; peak_anomaly_c: number; max_abs_anomaly_c: number; mean_anomaly_c: number; anomaly_now_c: number; anomaly_end_c: number; days: number; text: string };
    direction_by_day?: string[];
    change_vs_latest_c?: number[];
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
  summary: { points: number; species: number; records: number; points_in_heatwave: number; points_high_risk: number; conservation_sensitive_species: number; threatened_in_heatwave: number; with_alert: number; points_total: number; window_days: number; records_definition: string };
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

// ---- historical SST ---------------------------------------------------------------------------------------------
export type SstAggregation = "daily" | "monthly" | "annual";
export interface SstPoint {
  date: string;
  sst: number | null;
  anomaly: number | null;
  observations?: number;
}
export interface SstAnnual {
  year: number;
  mean_sst: number | null;
  mean_anomaly: number | null;
  min_sst: number | null;
  max_sst: number | null;
  observations: number;
  expected_days: number;
  coverage: number;
  complete: boolean;
}
export interface SstTrend {
  method: string;
  slope_per_year: number | null;
  direction: "warming" | "cooling" | "stable" | "insufficient_data";
  significant: boolean | null;
  message: string;
  n_years: number;
  years_used: number[];
  min_years_required: number;
  stderr?: number;
  ci95?: [number, number];
  p_value?: number;
  r_squared?: number;
  reference_year?: number;
  anomaly_at_reference_year?: number;
  change_over_span?: number;
  span_years?: number;
}
export interface SstHistory {
  dataset: EnvironmentDatasetAvailable;
  scope: { type: "region" | "location"; name: string };
  region: { id: string; name: string };
  location: { latitude: number; longitude: number; cell: { lat: number; lon: number; lon_180: number } } | null;
  aggregation: SstAggregation;
  period: { start: string; end: string; available_start: string; available_end: string; years: number };
  baseline: [string, string] | null;
  series: SstPoint[];
  annual_summary: SstAnnual[];
  trend: SstTrend;
  change: { from_year: number; to_year: number; mean_sst_change: number | null; mean_anomaly_change: number | null; basis: string } | null;
  percent_change: number | null;
  percent_change_note: string;
  statistics: { mean_sst: number | null; min_sst: number | null; max_sst: number | null; min_date: string | null; max_date: string | null; observations: number; expected_days: number; missing_days: number; cells: number; complete_years: number; years_without_data: number[] };
  forecast: { kind: "forecast"; label: string; issued_from: string; model: string; beats_persistence: boolean | null; series: SstPoint[] } | null;
  kind: "observed" | "generated";
  statement: string;
  limitations: string[];
}
export const getSstHistory = (p: { dataset: string; region: string; lat?: number; lon?: number; aggregation?: SstAggregation; start_date?: string; end_date?: string }) => get<SstHistory>("/sst-history", p);


// ---- forecast explanation ---------------------------------------------------------------------------------------
export interface ForecastModelInfo {
  dataset: string;
  name: string;
  checkpoint: { which: string; epoch: number | null; val_loss: number | null; input_scale?: string };
  architecture?: { in_channels: number; hidden_channels: number; kernel_size: number; layers: number; head_channels: number; n_horizons: number; residual: boolean } | null;
  architecture_text: string[];
  input: { window_days: number; channels: string[]; grid?: { rows: number; cols: number; resolution_deg: number | null }; description: string; not_inputs: string };
  output: { variable: string; horizons: number[]; form: string };
  normalisation: { method: string; dataset_statistics: Record<string, { mean: number; std: number }>; statistics_period: [string, string] | null; applied: string };
  training: { trained_on: string; retrained_for_this_dataset: boolean; note?: string };
  periods: { dataset_training: { start: string; end: string; days: number } | null; validation: { start: string; end: string; days: number } | null; test: { start: string; end: string; days: number } | null };
  evaluation: { split: string; date_range: [string, string]; n_windows: number; horizons: number[]; mean_mae: Record<string, number>; mae: Record<string, number[]>; mae_skill_vs_persistence: number[]; beats_persistence: boolean } | null;
  kinds: EvidenceKinds;
}
export interface ForecastExplanation {
  available: boolean;
  message?: string;
  dataset: string;
  issued_from: string;
  latest_observation: string;
  model: ForecastModelInfo;
  current?: { date: string; sst_c: number; climatological_sst_c: number; anomaly_c: number; relation: string; recent_trend_c_per_day: number; trend_3d_c_per_day?: number; anomaly_change_3d_c?: number; anomaly_change_7d_c?: number; recent_change_c: number; statement: string; trend_statement: string;
    window: { date: string; sst_c: number; climatology_c: number; anomaly_c: number }[] };
  forecast?: { day: number; date: string; sst_c: number; anomaly_c: number; change_vs_latest_c: number; direction: string; typical_error_c: number | null; statement: string }[];
  model_explanation?: KindedStatement[];
  matches_published_forecast?: boolean;
  sensitivity?: { method: string; title: string; plain: string; reading: string; neighbourhood_deg: number; block_deg: number; temporal: { days: string[]; delta_c: number[][] };
    local_all_days_c: number[]; everywhere_all_days_c: number[]; spatial: { lat_edges: number[]; lon_edges: number[]; delta_c: (number | null)[][][]; own_block: [number, number] | null } };
  persistence_c?: number;
  interpretation?: { direction: string; anomaly_trajectory: string; start_anomaly_c: number; end_anomaly_c: number; total_change_c: number; sst_change_c: number; text: string; plain?: string; forecast_outlook?: string; anomaly_outlook?: string };
  signals?: { rank: number; id: string; label: string; contribution_c: number; response_when_removed_c: number; relative: number; direction: string; sentence: string }[];
  inputs?: { latest_observation: string; window: { start: string; end: string; days: number }; latest_sst_c: number; latest_anomaly_c: number; sst_trend_7d_c_per_day: number; sst_change_7d_c: number; anomaly_change_7d_c: number;
    sst_trend_3d_c_per_day: number; anomaly_change_3d_c: number; grid: { rows: number; cols: number; resolution_deg: number | null } | null; cell: { lat: number; lon: number }; channels: string[]; window_days: number; horizons: number[]; spatial_context: string };
  model_evidence?: string[];
  physical_cause?: string;
  counterfactual?: { horizon: number; title: string; date: string; reading: string; rows: { label: string; sst_c: number; anomaly_c: number; difference_c: number; note: string }[] };
  statement?: string;
  kinds?: EvidenceKinds;
}
export interface PhysicalDatum { label: string; value: number | string; unit: string; period: string; kind: string }
export interface PhysicalMechanism {
  id: string; name: string; kind: string; verdict: "consistent" | "not consistent" | "inconclusive" | "not assessable"; favours: string | null;
  evidence_for: string[]; evidence_against: string[]; data: PhysicalDatum[]; caveat: string; evidence_quality: string;
}
export interface PhysicalSource {
  id: string; label: string; status: string; source: string | null; dataset: string | null; variable: string | null; unit: string | null; kind: string | null; spatial_resolution: string | null;
  temporal_resolution: string | null; dataset_end: string | null; used_through?: string | null; lag_days_behind_sst: number | null; retrieved: string | null; message: string | null; caveat: string | null;
}
export interface PhysicalInterpretationMechanism { id: string; name: string; support: "local_measurements" | "local_estimate" | "climate_context" | "climatology" | "general_context"; explanation: string; evidence: string[]; evidence_ids: string[]; complications: string[] }
export interface PhysicalInterpretation {
  headline: string; summary: string; mechanisms: PhysicalInterpretationMechanism[]; near_term: { text: string }; implications: { measured: string[]; general: string[] };
  confidence: { level: string; justification: string; criteria: { text: string; met: boolean }[] };
  key_measurements: { label: string; value: number | string; unit: string; period: string; kind: string }[];
  provider: { name: string; ai_generated: boolean; status: "not_configured" | "ok" | "generating" | "fallback"; note: string; generated_at?: string };
}
export interface PhysicalReport {
  interpretation?: PhysicalInterpretation;
  available: boolean; status?: string; message?: string; refresh_hint_s?: number | null; cell?: { lat: number; lon: number };
  observed?: { date: string; sst_c: number; anomaly_c: number; classification: string | null; text: string; trends: Record<string, number | string> | null };
  mechanisms?: PhysicalMechanism[];
  forecast_relationship?: { dates: { sst_observation: string; forecast_issued_from: string | null; forecast_valid: string[] | null; drivers: Record<string, { label: string; observation_date: string | null; lag_days_behind_sst: number | null }> }; statements: string[]; agreement: string | null };
  confidence?: { level: string; text: string; attribution: string };
  series?: { dates: string[]; sst_anomaly_c: (number | null)[]; wind_speed_ms: (number | null)[]; zonal_stress_nm2: (number | null)[]; sea_level_anomaly_m: (number | null)[] } | null;
  sources?: PhysicalSource[]; method?: string[]; definitions?: Record<string, string>; limitations?: string[];
}
export const getPhysicalDrivers = (dataset: string, lat: number, lon: number) => get<PhysicalReport>("/physical-drivers", { dataset, lat, lon });
export const getForecastModel = (dataset: string) => get<ForecastModelInfo>("/forecast-model", { dataset });
export const getForecastExplanation = (dataset: string, lat: number, lon: number) => get<ForecastExplanation>("/forecast-explain", { dataset, lat, lon });
export interface DatasetDates extends DataDates {
  dataset: string;
  freshness: { status: string; message: string; observation_date: string; expected_date?: string; refresh?: EnvironmentFreshness["refresh"] };
}
export const getDataDates = (dataset: string, date?: string) => get<DatasetDates>("/data-dates", { dataset, date });
