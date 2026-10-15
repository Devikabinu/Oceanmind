import { apiClient } from "./client";

export type Layer =
  | "observed"
  | "observed_anomaly"
  | "forecast"
  | "forecast_anomaly"
  | "heatwave"
  | "risk"
  | "hindcast"
  | "hindcast_truth"
  | "hindcast_error";
export type RegionName = "all" | "north" | "south" | "west" | "east";
export type Severity = "MEDIUM" | "HIGH" | "CRITICAL";
export type Level = "LOW" | "MEDIUM" | "HIGH" | "CRITICAL";

export interface Coverage {
  lat_min: number;
  lat_max: number;
  lon_min: number;
  lon_max: number;
}

export interface Snapshot {
  split: string;
  model: string;
  input_end_date: string;
  target_dates: string[];
  horizons: number[];
  kind: string;
  note: string;
  latest: { observed_date: string; target_dates: string[]; n_nrt_input_days: number | null; note: string };
}

export interface HeatwaveEvent {
  id: string;
  status: string;
  start_date: string;
  last_observed_date: string;
  duration_days: number;
  cells: number;
  area_km2: number;
  centroid: { lat: number; lon: number };
  bbox: { lat_min: number; lat_max: number; lon_min: number; lon_max: number };
  current_anomaly_c: number;
  max_anomaly_c: number;
  category: number;
  category_name: string;
  historical_percentile: number;
  forecast_still_above_p90_day7: number | null;
  cumulative_intensity_c_days?: number;
  max_cumulative_intensity_c_days?: number;
  timeline?: { date: string; area_km2: number; mean_anomaly_c: number }[];
}

export interface Overview {
  snapshot: Snapshot;
  data_status: {
    observed_date: string;
    forecast_dates: string[];
    data_age_days: number;
    available_dates: { start: string; end: string; n_days: number } | null;
    note: string | null;
    export_generated_at?: string | null;
  };
  provenance: { observed: string; forecast: string; evaluation: string; derived: string };
  current_sst: number | null;
  current_anomaly: number | null;
  forecast_sst: (number | null)[];
  forecast_anomaly: (number | null)[];
  forecast_change_c: number | null;
  forecast_trend: "warming" | "cooling" | "stable" | "unknown";
  hotspot_share_now: number;
  hotspot_share_day7: number;
  hotspot_threshold: number;
  heatwave: {
    active_area_km2: number;
    active_share: number;
    n_events: number;
    largest: HeatwaveEvent | null;
    historical_rank_pct: number;
    method: string;
  } | null;
  risk: { counts: Record<Level, number>; share_high_or_critical: number; factors_used: string[]; species_data_loaded: boolean };
  improvement: { persistence_mae: number; convlstm_mae: number; relative: number; better_all_horizons: boolean };
  interpretation: string[];
}

export interface MapLayer {
  layer: Layer;
  label: string;
  kind: "forecast" | "observed" | "evaluation" | "derived";
  unit: string;
  horizon: number;
  date: string;
  diverging: boolean;
  coverage: Coverage;
  lat: number[];
  lon: number[];
  values: (number | null)[][];
  min: number | null;
  max: number | null;
}

export interface RiskFactor {
  factor: "anomaly" | "persistence" | "forecast" | "overlap";
  value: number | null;
  level: "LOW" | "MEDIUM" | "HIGH" | null;
  weight: number;
  available: boolean;
}

export interface CellAssessment {
  score: number;
  level: Level;
  factors: RiskFactor[];
  reasons: string[];
  n_species: number | null;
  used_factors: string[];
}

export interface LocationInfo {
  query: { lat: number; lon: number };
  coverage: Coverage;
  in_coverage: boolean;
  is_ocean?: boolean;
  message?: string;
  cell?: { lat: number; lon: number };
  observed?: { date: string; sst_c: number; anomaly_c: number; climatology_c: number };
  forecast?: { dates: string[]; sst_c: (number | null)[]; anomaly_c: (number | null)[]; day7_change_c: number | null };
  heatwave?: {
    active: boolean;
    run_days: number;
    category: number;
    peak_anomaly_c: number | null;
    percentile: number | null;
    threshold_c: number | null;
    forecast_above_threshold_day7: boolean | null;
  } | null;
  risk?: CellAssessment;
  explanation?: string[];
}

export interface HistoryPoint {
  date: string;
  sst: number | null;
  climatology: number | null;
  p90_threshold: number | null;
  anomaly: number | null;
  anomaly_7d_mean: number | null;
}

export interface LocationHistory {
  cell: { lat: number; lon: number };
  unit: string;
  source: string;
  series: HistoryPoint[];
}

export interface PointForecast {
  lat: number;
  lon: number;
  dates: string[];
  horizons: number[];
  forecast: (number | null)[];
  observed: (number | null)[];
  climatology: (number | null)[];
  persistence: (number | null)[] | null;
  last_observed: number | null;
  last_observed_date: string;
  latest: { observed_date: string; dates: string[]; sst_c: number | null; forecast: (number | null)[]; climatology: (number | null)[] };
}

export interface RegionForecast extends Omit<PointForecast, "lat" | "lon"> {
  region: RegionName;
  n_cells: number;
  history: { date: string; sst: number; climatology: number }[];
}

export interface Hotspot {
  lat: number;
  lon: number;
  lat_min: number;
  lat_max: number;
  lon_min: number;
  lon_max: number;
  mean_anomaly: number;
  max_anomaly: number;
  value_c: number;
  baseline_c: number;
  persistence_days: number | null;
  cells: number;
  severity: Severity;
  direction: "warm" | "cold";
  date: string;
  kind: "observed" | "forecast";
  source: string;
}

export interface Hotspots {
  horizon: number;
  date: string;
  kind: "observed" | "forecast";
  total: number;
  items: Hotspot[];
  categories: { min_abs: number; level: string }[];
  available_dates: { start: string; end: string; n_days: number } | null;
  basis: string;
}

export interface ModelStats {
  mae: number[];
  rmse: number[];
  r2: number[];
  mean_mae: number;
  mean_rmse: number;
  mean_r2: number;
}

export interface Performance {
  split: string;
  date_range: [string, string];
  n_windows: number;
  n_valid_cells: number | null;
  horizons: number[];
  checkpoint: { which: string; epoch: number | null; val_loss: number | null } | null;
  models: { convlstm: ModelStats; persistence: ModelStats; climatology: ModelStats };
  mae_skill_vs_persistence: number[];
  rmse_skill_vs_persistence: number[];
  training: { epochs: number[]; train_loss: number[]; val_loss: number[] } | null;
  methodology: {
    model: string;
    task: string;
    splits: Record<string, { start: string; end: string; days: number; windows: number }>;
    baselines: string;
    evaluation: string;
  } | null;
}

type Params = Record<string, string | number | undefined>;
const get = async <T>(path: string, params?: Params): Promise<T> => (await apiClient.get<T>(path, { params })).data;

export const getOverview = () => get<Overview>("/monitor/overview");
export const getPerformance = () => get<Performance>("/monitor/performance");
export const getMapLayer = (layer: Layer, horizon: number, date?: string) =>
  get<MapLayer>("/monitor/map", { layer, horizon, date });
export const getLocation = (lat: number, lon: number) => get<LocationInfo>("/monitor/location", { lat, lon });
export const getHistory = (lat: number, lon: number, days = 180) =>
  get<LocationHistory>("/monitor/history", { lat, lon, days });
export const getPoint = (lat: number, lon: number) => get<PointForecast>("/monitor/point", { lat, lon });
export const getRegion = (name: RegionName) => get<RegionForecast>("/monitor/region", { name });
export const getHotspots = (horizon: number, min_abs = 1, limit = 200, date?: string) =>
  get<Hotspots>("/monitor/hotspots", { horizon, min_abs, limit, date });
