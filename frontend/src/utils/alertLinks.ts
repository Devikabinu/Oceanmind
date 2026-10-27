import type { AlertDetails } from "../types";

type Link = Pick<AlertDetails, "dataset" | "region_id" | "date" | "driver" | "location">;

/** The map layer an alert is about, so the link opens the map on the layer that shows the evidence. */
export function alertLayer(driver: string | undefined | null): string {
  switch (driver) {
    case "Ecological risk":
      return "risk";
    case "Marine heatwave":
      return "heatwave";
    case "Forecast":
      return "forecast_anomaly";
    default:
      return "anomaly";
  }
}

/** Ocean Map link for an alert: its dataset, region, date, layer, overlay and exact coordinates. Species-exposure alerts also switch the species overlay on. */
export function alertMapLink(d: Link | null | undefined): string {
  if (!d) return "/ocean-map";
  const q = new URLSearchParams();
  q.set("dataset", d.dataset ?? "pacific");
  q.set("region", d.region_id ?? "pacific");
  q.set("alerts", "1");
  if (d.date) q.set("date", d.date);
  q.set("layer", alertLayer(d.driver));
  if (d.driver === "Species exposure") q.set("species", "1");
  if (d.location) {
    q.set("lat", String(Math.round(d.location.lat * 1000) / 1000));
    q.set("lon", String(Math.round(d.location.lon_180 * 1000) / 1000));
  }
  return `/ocean-map?${q.toString()}`;
}
