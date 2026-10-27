import type { EnvironmentDatasetAvailable, EnvironmentMapResponse, LocationReportData, SpeciesLayer } from "../api/environment";

export const PROVIDER = {
  provider_id: "noaa_oisst_v2_1_pacific",
  provider_type: "observational",
  is_observational: true,
  description: "NOAA OISST v2.1",
  source: { short_name: "NOAA OISST v2.1", dataset: "NOAA Optimum Interpolation Sea Surface Temperature v2.1" },
};

export function dataset(over: Partial<EnvironmentDatasetAvailable> = {}): EnvironmentDatasetAvailable {
  return {
    available: true, id: "pacific", name: "Pacific Ocean", kind: "provider", is_default: true, provider: PROVIDER,
    extent: { lat_min: -60, lat_max: 65, lon_min: 100, lon_max: 290 }, resolution_deg: 1, units: "degC", lon_convention: "east longitude 0..360",
    grid_shape: [125, 190], total_cells: 23750, valid_cells: 16000, latest_date: "2026-10-22", first_date: "2012-01-01", n_dates: 5400,
    layers: { sst: { label: "Sea surface temperature", unit: "degC" }, anomaly: { label: "SST anomaly", unit: "degC" } },
    ...over,
  };
}

export const REGIONS = {
  regions: [
    { id: "pacific", name: "Entire Pacific Ocean", description: "", parent: null, children: [], map_extent: { lat_min: -60, lat_max: 65, lon_min: 100, lon_max: 290 } },
    { id: "polynesia", name: "Polynesia", description: "", parent: "pacific_islands", children: [], map_extent: { lat_min: -30, lat_max: 30, lon_min: 180, lon_max: 260 } },
    { id: "east_asia", name: "East Asia", description: "", parent: "western_pacific", children: [], map_extent: { lat_min: 25, lat_max: 65, lon_min: 100, lon_max: 160 } },
  ],
};

/** A small grid that straddles the date line: centres 178.5 .. 181.5 east. */
export function mapResponse(layer: "sst" | "anomaly", date: string, datasetId = "pacific"): EnvironmentMapResponse {
  return {
    dataset: dataset({ id: datasetId }), layer, label: layer === "sst" ? "Sea surface temperature" : "SST anomaly", unit: "degC", kind: "observed", diverging: layer === "anomaly",
    date, latest_available_date: "2026-10-22", region: { id: "pacific", name: "Entire Pacific Ocean" },
    lat: [0.5, 1.5], lon: [178.5, 179.5, 180.5, 181.5], values: [[27.1, 27.2, 27.3, null], [26.9, 27.0, null, 27.4]], min: 26.9, max: 27.4,
    coverage: { lat_min: 0, lat_max: 2, lon_min: 178, lon_max: 182 },
  } as unknown as EnvironmentMapResponse;
}

export function speciesLayer(): SpeciesLayer {
  const pt = (name: string, status: string, lat: number, lon: number, inHw = false) => ({
    aphia_id: name.length, scientific_name: name, common_name: null, conservation_status: status, lat, lon_180: lon, n_records: 3, in_heatwave: inHw, risk_level: null, alert_severity: null,
    taxon_group: "Mammals", latest: "2026-09-01", anomaly_c: 1.2, lon: lon < 0 ? lon + 360 : lon, conservation_source: "IUCN", records_in_heatwave: null,
  });
  return {
    dataset: "pacific", date: "2026-10-22", heatwave_computed: true, note: "Record locations are observations, not ranges.",
    summary: { points: 4, species: 4, records: 12, points_in_heatwave: 1, points_high_risk: 0, conservation_sensitive_species: 2, threatened_in_heatwave: 1, with_alert: 0 },
    items: [pt("Balaenoptera musculus", "EN", 10, -150, true), pt("Chelonia mydas", "VU", -5, 170), pt("Sardinops sagax", "LC", 30, 140), pt("Thunnus albacares", "NT", -20, 160)],
  } as unknown as SpeciesLayer;
}

export function report(over: Partial<LocationReportData> = {}): LocationReportData {
  const explanation = { headline: "h", sections: [{ id: "s", title: "t", text: "x", bullets: [] }] };
  return {
    dataset: "pacific", date: "2026-10-22", latest_available_date: "2026-10-22", query: { lat: 10, lon: -150 }, status: "valid", message: null,
    cell: { lat: 10.5, lon: 209.5, lon_180: -150.5, row: 70, col: 109 }, provider: PROVIDER, kind: "observed", region: { id: "polynesia", name: "Polynesia", contains: ["polynesia"] },
    conditions: { sst: 28.4, normal_sst: 27.1, anomaly: 1.3, unit: "degC" },
    anomaly: { value: 1.3, class: "Strongly warm", region_percentile: 91, historical_percentile: 98.4, historical_samples: 449, explanation } as never,
    heatwave: { available: true, inside: true, message: "This cell is inside a marine heatwave.", run_days: 12, event_id: "mhw-h20261010-n10e210", event_region: "Polynesia", why_it_matters: "Warm water stresses corals.",
      event: { id: "mhw-h20261010-n10e210", start_date: "2026-10-10", duration_days: 12, category_name: "II (Strong)", current_anomaly_c: 1.3, max_anomaly_c: 2.0, cumulative_intensity_c_days: 14, area_km2: 120000 } as never },
    risk: { status: "assessed", score: 0.62, level: "HIGH", evidence_completeness: 0.8, drivers: [], explanation } as never,
    species: { items: [], summary: "No records were available in this dataset within about 5° of this location. That is insufficient biodiversity coverage, not evidence that no species are present.", evidence: "insufficient_coverage", radius_deg: 5 },
    forecast: { available: true, issued_from: "2026-10-22", dates: ["2026-10-23"], forecast_sst: [28.6], forecast_anomaly: [1.4], persistence_sst: [28.4], typical_error_c: [0.4], direction: "warming", summary: "Forecast (model prediction): warming.",
      model: "ConvLSTM", trained_on: "northeast Pacific", beats_persistence: false },
    alerts: [],
    ...over,
  } as LocationReportData;
}
