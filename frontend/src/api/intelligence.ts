import { apiClient } from "./client";
import type { Level, HeatwaveEvent, MapLayer, RiskFactor, CellAssessment } from "./monitor";

type Params = Record<string, string | number | boolean | undefined>;
const get = async <T>(path: string, params?: Params): Promise<T> => (await apiClient.get<T>(path, { params })).data;

// ---- species -------------------------------------------------------------------------------------------------
export interface Species {
  aphia_id: number;
  scientific_name: string;
  common_name: string | null;
  taxon_group: string;
  class_name: string | null;
  order_name: string | null;
  family: string | null;
  iucn_category: string | null;
  iucn_label: string | null;
  iucn_source: string | null;
  watchlist: boolean;
  n_observations: number;
  last_observation: string | null;
}

export interface SpeciesDetail extends Species {
  first_observation: string | null;
  sources: Record<string, string | null> & { conservation_alt?: { source: string; category: string } | null };
  last_synced_at: string | null;
}

export interface SpeciesPage {
  items: Species[];
  total: number;
  page: number;
  page_size: number;
  groups: Record<string, number>;
  statuses: Record<string, number>;
}

export interface SpeciesObservation {
  id: string;
  timestamp: string;
  latitude: number;
  longitude: number;
  scientific_name: string;
  occurrence_status: string | null;
  min_depth: number | null;
  max_depth: number | null;
  source_record_id: string | null;
}

export interface SpeciesRisk {
  available: boolean;
  dataset?: string | null;
  status?: string | null;
  evidence_completeness?: number | null;
  unavailable_factors?: Record<string, string> | null;
  aphia_id: number;
  scientific_name: string;
  n_records: number;
  window_days: number;
  methodology: string;
  message: string | null;
  score: number | null;
  level: Level | null;
  factors: RiskFactor[];
  reasons: string[];
  n_cells: number | null;
  exposed_share: number | null;
  heatwave_share: number | null;
  mean_anomaly_c: number | null;
  thermal_range_c: { p10: number; median: number; p90: number; n: number } | null;
  max_anomaly_c: number | null;
  observed_locations: number | null;
  overlapping_locations: number | null;
  exposure_pct_locations: number | null;
  heatwave_locations: number | null;
  heatwave_days_mean: number | null;
  heatwave_days_max: number | null;
  forecast_exposure: "LOW" | "MEDIUM" | "HIGH" | null;
  forecast_mean_anomaly_c: number | null;
  recent_records_90d: number | null;
  latest_record: string | null;
  labels: Record<string, string>;
}

export interface SearchHit {
  aphia_id: number;
  scientific_name: string;
  rank: string | null;
  taxon_group: string;
  class_name: string | null;
  family: string | null;
  in_catalogue: boolean;
}

export const listSpecies = (p: Params) => get<SpeciesPage>("/species", p);
export const getSpecies = (id: number) => get<SpeciesDetail>(`/species/${id}`);
export const getSpeciesObservations = (id: number, p: Params = {}) =>
  get<{ items: SpeciesObservation[]; total: number; source: string }>(`/species/${id}/observations`, { page_size: 500, ...p });
export const getSpeciesRisk = (id: number, dataset?: string) => get<SpeciesRisk>(`/species/${id}/risk`, { dataset });
export const getSpeciesDistribution = (id: number) =>
  get<{ geojson: GeoJSON.FeatureCollection; note: string; source: string }>(`/species/${id}/distribution`);
export interface BiodiversitySummary {
  n_species: number;
  species_with_records: number;
  n_records: number;
  records_last_90_days: number;
  first_observation: string | null;
  latest_observation: string | null;
  conservation_sensitive_with_records: number;
  note: string;
}
export const getBiodiversitySummary = () => get<BiodiversitySummary>("/species/summary");
export const searchObis = (q: string) => get<SearchHit[]>("/species/search", { q });
export const trackSpecies = async (aphia_id: number) => (await apiClient.post<SpeciesDetail>("/species", { aphia_id })).data;

// ---- heatwaves -------------------------------------------------------------------------------------------------
export interface HeatwaveSummary {
  method: string;
  baseline: [string, string];
  data_source: string;
  latest_date: string;
  active_area_km2: number;
  active_share: number;
  historical_rank_pct: number;
  n_events: number;
  ocean_area_km2: number;
  min_event_cells: number;
  what_is: string;
  how_detected: string[];
  dataset?: string;
  /** Provider metadata of the SST the heatwaves were derived from (absent for the NE Pacific export). */
  source?: { provider_id: string; is_observational: boolean; description: string } | null;
  is_observational?: boolean;
  threshold?: { method: string; percentile: number; window_days: number; smoothing_days: number };
  min_duration_days?: number;
  max_gap_days?: number;
}

export interface HeatwaveFootprint {
  cells: number;
  returned: number;
  lat: number[];
  lon: number[];
  lon_180: number[];
  resolution_deg: number;
}

export interface HeatwaveProvenance {
  dataset: string;
  provider: { provider_id: string; is_observational: boolean; description: string } | null;
  is_observational: boolean;
  data_source: string;
}

export interface YearStats {
  days: number;
  max_area_km2: number;
  mean_area_km2: number;
  days_with_heatwave_area_over_5pct: number;
}

export interface SpeciesInArea {
  aphia_id: number | null;
  scientific_name: string;
  common_name: string | null;
  taxon_group: string | null;
  iucn_category: string | null;
  n_records: number;
}

export const listHeatwaves = (p: Params = {}) =>
  get<{ summary: HeatwaveSummary; total: number; items: HeatwaveEvent[]; dataset?: string; provenance?: HeatwaveProvenance; region?: { id: string; name: string } }>("/heatwaves", p);
export const getHeatwave = (id: string, dataset?: string) =>
  get<{
    event: HeatwaveEvent;
    explanation: string[];
    summary: HeatwaveSummary;
    yearly: Record<string, YearStats>;
    species_in_area: SpeciesInArea[];
    species_note: string;
    biodiversity_evidence?: "observed" | "insufficient_coverage";
    footprint?: HeatwaveFootprint;
    provenance?: HeatwaveProvenance;
    narrative?: Explanation;
  }>(`/heatwaves/${id}`, { dataset });
export const getHeatwaveSeries = (days: number, dataset?: string) =>
  get<{ dates: string[]; heatwave_area_km2: number[]; mean_sst: number[]; mean_anomaly: number[]; ocean_area_km2: number; yearly: Record<string, YearStats>; method: string }>(
    "/heatwaves/timeseries",
    { days, dataset },
  );
/** Anomaly of the cells in a heatwave on the dataset's latest date (null elsewhere), in the shape the grid map draws. */
export const getHeatwaveMap = (dataset: string, region: string, date?: string) =>
  get<MapLayer & { dataset: string; region: { id: string; name: string }; active_cells: number; provenance: HeatwaveProvenance }>("/heatwaves/map", { dataset, region, date });

// ---- historical events (the whole record, not only the latest day) --------------------------------------------------
export interface HistoricalEvent {
  id: string;
  dataset: string;
  status: "ACTIVE" | "ENDED";
  start_date: string;
  end_date: string;
  duration_days: number;
  peak_date: string;
  peak_area_km2: number;
  peak_cells: number;
  max_area_km2: number;
  cell_days: number;
  mean_anomaly_c: number;
  max_anomaly_c: number;
  category: number;
  category_name: string;
  cumulative_intensity_c_days: number;
  centroid: { lat: number; lon: number; lon_180: number };
  bbox: { lat_min: number; lat_max: number; lon_min: number; lon_max: number };
  cells_on_date?: number;
}
export interface HistoricalEventList {
  dataset: string;
  total: number;
  items: HistoricalEvent[];
  by_start_year: Record<string, number>;
  first_date: string;
  last_date: string;
  n_detected: number;
  n_listed_in_record: number;
  note: string;
  provenance?: HeatwaveProvenance;
  region?: { id: string; name: string } | null;
}
export interface HistoricalEventDetail {
  event: HistoricalEvent;
  evolution: { dates: string[]; area_km2: number[]; mean_anomaly_c: number[] };
  footprint: HeatwaveFootprint & { date: string; anomaly_c: number[] };
  current_event_ids: string[] | null;
  explanation: string[];
  species_in_area: SpeciesInArea[];
  species_note?: string;
  biodiversity_evidence?: "observed" | "insufficient_coverage";
  provenance?: HeatwaveProvenance;
}
export const listHeatwaveHistory = (p: Params = {}) => get<HistoricalEventList>("/heatwaves/history", p);
export const getHeatwaveHistoryEvent = (id: string, dataset?: string, date?: string) => get<HistoricalEventDetail>(`/heatwaves/history/${id}`, { dataset, date });
export const listHeatwavesOn = (date: string, dataset?: string) => get<{ date: string; items: HistoricalEvent[] }>(`/heatwaves/on/${date}`, { dataset });

// ---- ecological risk ---------------------------------------------------------------------------------------------
export interface Methodology {
  name: string;
  status: string;
  weights: Record<string, number>;
  factors: Record<string, string>;
  levels: string;
  weights_note: string;
  confidence: string;
  limitations: string[];
}

export interface RiskArea {
  lat: number;
  lon: number;
  score: number;
  level: Level;
  top_driver: string;
  factors: Record<string, number>;
  /** Longitude in -180..180 (Pacific datasets send `lon` on a continuous east axis). */
  lon_180?: number;
  bbox: { lat_min: number; lat_max: number; lon_min: number; lon_max: number };
}

export const getMethodology = () => get<Methodology>("/ecological-risk/methodology");
export const getRiskAreas = (min_level: Level, limit = 30, region = "all", dataset?: string, date?: string) =>
  get<{ date: string; total: number; items: RiskArea[]; factors_used: string[]; factors_unavailable?: Record<string, string>; dataset?: string }>("/ecological-risk/areas", {
    min_level,
    limit,
    region,
    dataset,
    date,
  });
export const getLocationRisk = (lat: number, lon: number) =>
  get<CellAssessment & { cell: { lat: number; lon: number }; date: string; methodology: string }>("/ecological-risk/location", { lat, lon });
export const getSpeciesRanking = () =>
  get<{ items: (SpeciesRisk & { common_name: string | null; taxon_group: string | null; iucn_category: string | null })[] }>("/ecological-risk/species");

// ---- ocean coverage ----------------------------------------------------------------------------------------------
export interface OceanRegion {
  id: string;
  name: string;
  approx_bounds: [[number, number], [number, number]];
  project_data: "partial" | "none";
  note: string;
  stored_species_records: number | null;
}

export interface SourceInfo {
  id: string;
  name: string;
  provider: string;
  data_type: string;
  variables: string[];
  coverage_source: string;
  temporal_source: string;
  loaded_in_project: string | null;
  resolution: string;
  spatial_loaded: string;
  latest_date: string | null;
  status_kind: "loaded" | "integrated" | "not_loaded";
  status_label: string;
  records_label: string;
  database: {
    registered?: boolean;
    status?: string;
    datasets?: number;
    records?: number;
    temporal_start?: string | null;
    temporal_end?: string | null;
    last_successful_ingestion?: string | null;
  };
  documentation: string | null;
  stored_rows: number | null;
  url?: string | null;
  update_frequency?: string;
  baseline?: [string, string] | null;
  last_updated?: string | null;
  freshness?: { days_behind: number; status: "current" | "delayed" | "stale"; message: string; observation_date: string } | null;
  processing?: string;
  limitations?: string[];
}

export const getRegions = () =>
  get<{ study_region: (import("./monitor").Coverage & { name: string; latest_observed_date: string }) | null; regions: OceanRegion[] }>("/ocean/regions");
export const getCoverage = () => get<{ items: SourceInfo[] }>("/ocean/coverage");

// ---- ecological risk on a selectable dataset (/api/ecological-risk/map and /location?dataset=) --------------------------
export type RiskStatus = "assessed" | "insufficient_data" | "unavailable" | "land" | "outside_region";
export type BiodiversityEvidence = "observed" | "none_recorded" | "insufficient_coverage" | "unavailable";
/** Cell state codes of /ecological-risk/map `status`. */
export const RISK_STATE = { ASSESSED: 0, INSUFFICIENT: 1, UNAVAILABLE: 2, LAND: 3, OUTSIDE: 4 } as const;

export interface RiskSource {
  provider_id: string;
  is_observational: boolean;
  description: string;
}

export interface RiskMapResponse {
  dataset: string;
  date: string;
  region: { id: string; name: string };
  layer: "risk";
  label: string;
  unit: string;
  kind: "derived";
  methodology: string;
  weights: Record<string, number>;
  source: RiskSource;
  factors_used: string[];
  factors_unavailable: Record<string, string>;
  lat: number[];
  lon: number[];
  /** Score 0-1, or null where the cell has no score (land, missing, insufficient, outside the region). Never 0 for those. */
  values: (number | null)[][];
  /** -1 no score, 0 LOW, 1 MEDIUM, 2 HIGH, 3 CRITICAL */
  levels: number[][];
  /** See RISK_STATE */
  status: number[][];
  status_legend: Record<string, string>;
  min: number | null;
  max: number | null;
  counts: Record<string, number>;
  downsample_factor: number;
  coverage_note: string;
}

export interface RiskCell {
  dataset: string;
  source: RiskSource;
  cell: { lat: number; lon: number; lon_180: number };
  date: string;
  methodology: string;
  score: number | null;
  level: Level | null;
  status: RiskStatus;
  factors: RiskFactor[];
  reasons: string[];
  n_species: number | null;
  biodiversity_evidence: BiodiversityEvidence;
  evidence_completeness: number | null;
  unavailable_factors: Record<string, string>;
  used_factors: string[];
}

export const getRiskMap = (dataset: string, region: string, date?: string) =>
  get<RiskMapResponse>("/ecological-risk/map", { dataset, region, date });
export const getRiskCell = (lat: number, lon: number, dataset: string, date?: string) =>
  get<RiskCell>("/ecological-risk/location", { lat, lon, dataset, date });

// ---- plain-language explanations (built by the backend only from the structured evidence of the same response) --------------
export interface ExplanationSection {
  id: string;
  title: string;
  text: string;
  bullets: string[];
}

export interface Explanation {
  headline: string;
  sections: ExplanationSection[];
  grounded_in?: Record<string, unknown>;
  contributions?: { factor: string; label: string; value: number; level: Level | null; weight_share: number; score_points: number }[];
  kind: "risk_cell" | "heatwave_event" | "forecast";
}

export const getRiskExplanation = (lat: number, lon: number, dataset: string, date?: string) =>
  get<{ cell: RiskCell; explanation: Explanation }>("/ecological-risk/explain", { lat, lon, dataset, date });
