import { describe, expect, it } from "vitest";
import { alertLayer, alertMapLink } from "../utils/alertLinks";
import { axisOrigin, extentToBounds, footprintToLayer, shiftGeoJson, toAxisLon } from "../utils/mapCoords";
import { providerLabel } from "../utils/format";

describe("antimeridian handling", () => {
  it("places any longitude on the continuous axis that starts at 100 east", () => {
    expect(toAxisLon(179.5, 100)).toBe(179.5);
    expect(toAxisLon(-179.5, 100)).toBe(180.5);       // just west of the date line continues past 180
    expect(toAxisLon(-120, 100)).toBe(240);
    expect(toAxisLon(300, 100)).toBe(300 - 0);        // 300 east is still inside [100, 460)
    expect(toAxisLon(-250, 100)).toBe(110);
  });

  it("finds the western edge of a grid from its cell centres", () => {
    expect(axisOrigin([100.5, 101.5, 102.5])).toBe(100);
    expect(axisOrigin([100.375])).toBe(100.375);
  });

  it("keeps a continuous axis across 180 when shifting GeoJSON", () => {
    const fc: GeoJSON.FeatureCollection = {
      type: "FeatureCollection",
      features: [{ type: "Feature", properties: {}, geometry: { type: "Polygon", coordinates: [[[179, 0], [-179, 0], [-179, 2], [179, 2], [179, 0]]] } }],
    };
    const out = shiftGeoJson(fc, 100);
    const ring = (out.features[0].geometry as GeoJSON.Polygon).coordinates[0];
    expect(ring.map((p) => p[0])).toEqual([179, 181, 181, 179, 179]);          // one polygon, no 358-degree jump
  });

  it("builds map bounds from a region extent", () => {
    expect(extentToBounds({ lat_min: -10, lat_max: 10, lon_min: 100, lon_max: 290 })).toEqual([[-10, 100], [10, 290]]);
  });
});

describe("heatwave footprints", () => {
  it("draws only the footprint cells, across the date line, never a bounding box", () => {
    const fp = { lat: [0.5, 0.5, 1.5], lon: [179.5, 180.5, 180.5], anomaly_c: [2.1, 2.4, 1.9], resolution_deg: 1 };
    const l = footprintToLayer(fp);
    expect(l.lon).toEqual([179.5, 180.5]);                    // continuous east longitude, crossing 180
    expect(l.values).toEqual([[2.1, 2.4], [null, 1.9]]);       // the empty corner stays null, not 0
    expect(l.coverage).toEqual({ lat_min: 0, lat_max: 2, lon_min: 179, lon_max: 181 });
  });
});

describe("alert links", () => {
  const base = { dataset: "pacific", region_id: "polynesia", date: "2026-10-22", location: { lat: -17.5, lon_180: -149.5 } };

  it("opens the map with the alert's date, region, layer, overlay and exact coordinates", () => {
    const url = new URL(alertMapLink({ ...base, driver: "Marine heatwave" }), "http://x");
    expect(url.pathname).toBe("/ocean-map");
    expect(Object.fromEntries(url.searchParams)).toEqual({ dataset: "pacific", region: "polynesia", alerts: "1", date: "2026-10-22", layer: "heatwave", lat: "-17.5", lon: "-149.5" });
  });

  it("chooses the layer from the kind of alert", () => {
    expect(alertLayer("Ecological risk")).toBe("risk");
    expect(alertLayer("Marine heatwave")).toBe("heatwave");
    expect(alertLayer("Forecast")).toBe("forecast_anomaly");
    expect(alertLayer("SST anomaly")).toBe("anomaly");
    expect(alertLayer(undefined)).toBe("anomaly");
  });

  it("switches the species overlay on for species-exposure alerts", () => {
    const url = new URL(alertMapLink({ ...base, driver: "Species exposure" }), "http://x");
    expect(url.searchParams.get("species")).toBe("1");
    expect(new URL(alertMapLink({ ...base, driver: "Ecological risk" }), "http://x").searchParams.has("species")).toBe(false);
  });

  it("falls back to the whole Pacific when an alert has no region or location", () => {
    const url = new URL(alertMapLink({ driver: "SST anomaly" }), "http://x");
    expect(url.searchParams.get("region")).toBe("pacific");
    expect(url.searchParams.has("lat")).toBe(false);
  });
});

describe("source names", () => {
  it("shows the real dataset name instead of an internal identifier", () => {
    expect(providerLabel({ provider_id: "noaa_oisst_v2_1_pacific", source: { short_name: "NOAA OISST v2.1" } })).toBe("NOAA OISST v2.1");
    expect(providerLabel({ provider_id: "x", description: "Reanalysis" })).toBe("Reanalysis");
    expect(providerLabel(null)).toBe("Unknown source");
  });
});
