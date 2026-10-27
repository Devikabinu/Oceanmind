import type { MapLayer } from "../api/monitor";
import type { EnvironmentExtent, EnvironmentMapResponse } from "../api/environment";
import type { RiskMapResponse } from "../api/intelligence";

/**
 * The ONLY place where longitude conventions are translated.
 * The environment API returns a continuous east-longitude axis (the Pacific is e.g. 100.5 .. 289.5, so it crosses 180 without a gap) and Leaflet
 * accepts those longitudes as they are, so map data are never re-wrapped. Only coordinates that arrive in -180..180 (mouse positions, species
 * records, alerts) are shifted onto the axis of the data being shown.
 */

/** A longitude in any convention placed on the continuous axis that starts at `origin`: result in [origin, origin + 360). */
export function toAxisLon(lon: number, origin: number): number {
  return origin + ((((lon - origin) % 360) + 360) % 360);
}

/** Western edge of the cell grid, i.e. where the continuous axis of a response starts. */
export function axisOrigin(lon: number[]): number {
  return lon.length > 1 ? lon[0] - (lon[1] - lon[0]) / 2 : lon[0];
}

/** Environment response in the shape the existing grid map draws. The coverage box is that of the returned grid, so hover and outline match the data. */
export function toMapLayer(m: EnvironmentMapResponse): MapLayer {
  const dLat = m.lat.length > 1 ? m.lat[1] - m.lat[0] : 0;
  const dLon = m.lon.length > 1 ? m.lon[1] - m.lon[0] : 0;
  return {
    layer: m.layer === "sst" ? "observed" : "observed_anomaly",
    label: m.label,
    kind: m.kind === "generated" ? "derived" : "observed",
    unit: m.unit,
    horizon: 0,
    date: m.date,
    diverging: m.diverging,
    coverage: {
      lat_min: m.lat[0] - dLat / 2,
      lat_max: m.lat[m.lat.length - 1] + dLat / 2,
      lon_min: m.lon[0] - dLon / 2,
      lon_max: m.lon[m.lon.length - 1] + dLon / 2,
    },
    lat: m.lat,
    lon: m.lon,
    values: m.values,
    min: m.min,
    max: m.max,
  };
}

/** Leaflet bounds [[south, west], [north, east]] for a region map extent from the backend. */
export function extentToBounds(e: EnvironmentExtent): [[number, number], [number, number]] {
  return [
    [e.lat_min, e.lon_min],
    [e.lat_max, e.lon_max],
  ];
}

/** Shift every coordinate of a GeoJSON collection onto the axis starting at `origin`. */
export function shiftGeoJson(fc: GeoJSON.FeatureCollection, origin: number): GeoJSON.FeatureCollection {
  const walk = (c: unknown): unknown =>
    Array.isArray(c) && typeof c[0] === "number" ? [toAxisLon(c[0], origin), ...(c.slice(1) as number[])] : Array.isArray(c) ? c.map(walk) : c;
  return {
    ...fc,
    features: fc.features.map((f) => ({
      ...f,
      geometry: f.geometry && "coordinates" in f.geometry ? ({ ...f.geometry, coordinates: walk(f.geometry.coordinates) } as GeoJSON.Geometry) : f.geometry,
    })),
  };
}

/** Risk map in the shape the grid map draws. Cells without a score keep null (never 0); `status` lets the map paint them as insufficient / unavailable. */
export function riskToMapLayer(m: RiskMapResponse): MapLayer & { status: number[][] } {
  const dLat = m.lat.length > 1 ? m.lat[1] - m.lat[0] : 0;
  const dLon = m.lon.length > 1 ? m.lon[1] - m.lon[0] : 0;
  return {
    layer: "risk",
    label: m.label,
    kind: "derived",
    unit: m.unit,
    horizon: 0,
    date: m.date,
    diverging: false,
    coverage: {
      lat_min: m.lat[0] - dLat / 2,
      lat_max: m.lat[m.lat.length - 1] + dLat / 2,
      lon_min: m.lon[0] - dLon / 2,
      lon_max: m.lon[m.lon.length - 1] + dLon / 2,
    },
    lat: m.lat,
    lon: m.lon,
    values: m.values,
    min: 0,
    max: 1,
    status: m.status,
  };
}

/** A heatwave footprint (cell centres on the dataset's own continuous longitude axis) as a sparse grid the map can draw as an overlay: cells of the footprint carry
 *  their anomaly, every other cell is null. The grid spans only the footprint's extent, so it never looks like a bounding rectangle. */
export function footprintToLayer(fp: { lat: number[]; lon: number[]; anomaly_c?: number[]; resolution_deg: number }, id = "footprint"): MapLayer {
  const res = fp.resolution_deg;
  const lat0 = Math.min(...fp.lat);
  const lon0 = Math.min(...fp.lon);
  const nLat = Math.round((Math.max(...fp.lat) - lat0) / res) + 1;
  const nLon = Math.round((Math.max(...fp.lon) - lon0) / res) + 1;
  const lat = Array.from({ length: nLat }, (_, i) => lat0 + i * res);
  const lon = Array.from({ length: nLon }, (_, j) => lon0 + j * res);
  const values: (number | null)[][] = lat.map(() => lon.map(() => null));
  fp.lat.forEach((la, k) => {
    values[Math.round((la - lat0) / res)][Math.round((fp.lon[k] - lon0) / res)] = fp.anomaly_c?.[k] ?? 1;
  });
  return {
    layer: id, label: "Heatwave footprint", kind: "derived", unit: "degC", horizon: 0, date: "", diverging: true,
    coverage: { lat_min: lat0 - res / 2, lat_max: lat[nLat - 1] + res / 2, lon_min: lon0 - res / 2, lon_max: lon[nLon - 1] + res / 2 },
    lat, lon, values, min: Math.min(...fp.anomaly_c ?? [0]), max: Math.max(...fp.anomaly_c ?? [1]),
  } as MapLayer;
}
