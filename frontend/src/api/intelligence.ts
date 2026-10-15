import { apiClient } from "./client";
import type { Level, HeatwaveEvent, RiskFactor, CellAssessment } from "./monitor";

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
export const getSpeciesRisk = (id: number) => get<SpeciesRisk>(`/species/${id}/risk`);
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

export const listHeatwaves = (p: Params = {}) => get<{ summary: HeatwaveSummary; total: number; items: HeatwaveEvent[] }>("/heatwaves", p);
export const getHeatwave = (id: string) =>
  get<{ event: HeatwaveEvent; explanation: string[]; summary: HeatwaveSummary; yearly: Record<string, YearStats>; species_in_area: SpeciesInArea[]; species_note: string }>(
    `/heatwaves/${id}`,
  );
export const getHeatwaveSeries = (days: number) =>
  get<{ dates: string[]; heatwave_area_km2: number[]; mean_sst: number[]; mean_anomaly: number[]; ocean_area_km2: number; yearly: Record<string, YearStats>; method: string }>(
    "/heatwaves/timeseries",
    { days },
  );

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
  bbox: { lat_min: number; lat_max: number; lon_min: number; lon_max: number };
}

export const getMethodology = () => get<Methodology>("/ecological-risk/methodology");
export const getRiskAreas = (min_level: Level, limit = 30, region = "all") =>
  get<{ date: string; total: number; items: RiskArea[]; factors_used: string[] }>("/ecological-risk/areas", { min_level, limit, region });
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
}

export const getRegions = () =>
  get<{ study_region: (import("./monitor").Coverage & { name: string; latest_observed_date: string }) | null; regions: OceanRegion[] }>("/ocean/regions");
export const getCoverage = () => get<{ items: SourceInfo[] }>("/ocean/coverage");
