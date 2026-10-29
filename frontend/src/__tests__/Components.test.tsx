import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { dataset, PROVIDER, REGIONS } from "./fixtures";
import type { Alert } from "../types";

const intel = vi.hoisted(() => ({ listHeatwaveHistory: vi.fn(), getHeatwaveHistoryEvent: vi.fn(), getHeatwaveMap: vi.fn() }));
const env = vi.hoisted(() => ({ getAnomalyAnalysis: vi.fn(), getMap: vi.fn(), getRegions: vi.fn(), getDatasets: vi.fn(), getDates: vi.fn(), getReport: vi.fn() }));
vi.mock("../api/intelligence", async (orig) => ({ ...(await orig<typeof import("../api/intelligence")>()), ...intel }));
vi.mock("../api/environment", async (orig) => ({ ...(await orig<typeof import("../api/environment")>()), ...env }));
vi.mock("../components/SstMap", () => ({
  default: (p: { layer: { date: string } | null; overlay: { lon: number[] } | null }) => <div data-testid="map" data-date={p.layer?.date ?? ""} data-overlay-lon={p.overlay ? p.overlay.lon.join(",") : ""} />,
}));
vi.mock("recharts", () => {
  const Box = ({ children }: { children?: React.ReactNode }) => <div>{children}</div>;
  return { ResponsiveContainer: Box, ComposedChart: Box, Area: Box, Line: Box, XAxis: Box, YAxis: Box, CartesianGrid: Box, Tooltip: Box, Legend: Box, ReferenceLine: Box, BarChart: Box, Bar: Box };
});

import AlertCard from "../components/AlertCard";
import HeatwaveHistory from "../components/HeatwaveHistory";
import PacificAnomalies from "../components/PacificAnomalies";
import { ActiveSelectionProvider } from "../contexts/ActiveSelection";
import { clearCached } from "../hooks/useCached";

function alert(over: Partial<Alert["details"]> = {}): Alert {
  return {
    id: "a1", alert_type: "MARINE_HEATWAVE", severity: "HIGH", status: "NEW", latitude: -17.5, longitude: 210.5, timestamp: "2026-10-22T00:00:00Z", message: "Marine heatwave near Polynesia", resolved_at: null,
    details: { key: "k", driver: "Marine heatwave", region: "Polynesia", reasons: ["r"], data_sources: ["NOAA OISST v2.1 (observations)"], classification: "DERIVED METRIC", recommendation: "Monitor", dataset: "pacific", region_id: "polynesia",
      date: "2026-10-22", location: { lat: -17.5, lon_180: -149.5 }, event_id: "mhw-h20261010-s18e210", ...over },
  } as unknown as Alert;
}

const event = (over = {}) => ({
  id: "mhw-h20230716-n06e208", dataset: "pacific", status: "ENDED", start_date: "2023-07-16", end_date: "2023-09-20", duration_days: 67, peak_date: "2023-08-30", peak_area_km2: 2_500_000, peak_cells: 210, max_area_km2: 2_500_000,
  cell_days: 9000, mean_anomaly_c: 1.4, max_anomaly_c: 3.2, category: 2, category_name: "II (Strong)", cumulative_intensity_c_days: 80, centroid: { lat: 6, lon: 208, lon_180: -152 },
  bbox: { lat_min: 0, lat_max: 12, lon_min: 200, lon_max: 215 }, ...over,
});

beforeEach(() => {
  vi.clearAllMocks();
  clearCached();
});

describe("AlertCard deep links", () => {
  it("links an alert to the map with its date, region, layer, overlay and exact coordinates", async () => {
    render(<MemoryRouter><AlertCard alert={alert()} defaultOpen /></MemoryRouter>);
    const link = screen.getByRole("link", { name: /Exact map location/ });
    const u = new URL(link.getAttribute("href")!, "http://x");
    expect(u.pathname).toBe("/ocean-map");
    expect(Object.fromEntries(u.searchParams)).toMatchObject({ dataset: "pacific", region: "polynesia", date: "2026-10-22", layer: "heatwave", lat: "-17.5", lon: "-149.5", alerts: "1" });
    expect(screen.getByRole("link", { name: /Heatwave event/ })).toHaveAttribute("href", expect.stringContaining("event=mhw-h20261010-s18e210"));
  });

  it("opens a forecast alert on the forecast layer and a species alert with the species overlay", () => {
    const { unmount } = render(<MemoryRouter><AlertCard alert={alert({ driver: "Forecast" })} defaultOpen /></MemoryRouter>);
    expect(screen.getByRole("link", { name: /Exact map location/ }).getAttribute("href")).toContain("layer=forecast_anomaly");
    unmount();
    render(<MemoryRouter><AlertCard alert={alert({ driver: "Species exposure" })} defaultOpen /></MemoryRouter>);
    expect(screen.getByRole("link", { name: /Exact map location/ }).getAttribute("href")).toContain("species=1");
  });

  it("does not use development wording for any data source", () => {
    render(<MemoryRouter><AlertCard alert={alert({ is_observational: false })} defaultOpen /></MemoryRouter>);
    const text = document.body.textContent ?? "";
    expect(text).not.toMatch(/generated|fabricated|synthetic|mock|demo|temporary|development|not real data/i);
  });
});

describe("Heatwave history", () => {
  const list = (items = [event()]) => ({ dataset: "pacific", total: items.length, items, by_start_year: { "2023": 1 }, first_date: "2012-01-01", last_date: "2026-10-22", n_detected: 90, n_listed_in_record: 60, note: "The 60 largest events are listed." });
  const detail = (day = "2023-08-30") => ({
    event: event(), evolution: { dates: ["2023-08-29", "2023-08-30", "2023-08-31"], area_km2: [1, 2, 1], mean_anomaly_c: [1, 2, 1] },
    footprint: { date: day, cells: 210, returned: 2, lat: [5.5, 6.5], lon: [179.5, 180.5], lon_180: [179.5, -179.5], anomaly_c: [2, 2.1], resolution_deg: 1 }, current_event_ids: null,
    explanation: ["From 2023-07-16 to 2023-09-20 (67 days) sea surface temperature stayed above the seasonal 90th percentile."], species_in_area: [], provenance: undefined,
  });

  beforeEach(() => {
    intel.listHeatwaveHistory.mockImplementation(async () => list());
    intel.getHeatwaveHistoryEvent.mockImplementation(async (_id: string, _d: string, date?: string) => detail(date));
    intel.getHeatwaveMap.mockImplementation(async (_d: string, _r: string, date: string) => ({ dataset: "pacific", date, lat: [5.5], lon: [179.5], values: [[2]], label: "x", unit: "degC", diverging: true, coverage: { lat_min: 5, lat_max: 6, lon_min: 179, lon_max: 180 }, min: 2, max: 2, kind: "derived", layer: "heatwave", horizon: 0 }));
  });

  it("lists past events and filters them through the API", async () => {
    const user = userEvent.setup();
    render(<MemoryRouter><HeatwaveHistory dataset="pacific" region="pacific" /></MemoryRouter>);
    const item = await screen.findByRole("button", { name: /II \(Strong\)/ });
    expect(item).toHaveTextContent("2023-07-16 to 2023-09-20");
    expect(intel.listHeatwaveHistory).toHaveBeenLastCalledWith(expect.objectContaining({ dataset: "pacific", min_category: 1, sort: "start" }));
    await user.selectOptions(screen.getByLabelText("Year"), "2023");
    await user.selectOptions(screen.getByLabelText("Minimum category"), "3");
    await user.selectOptions(screen.getByLabelText("Status"), "ENDED");
    await waitFor(() => expect(intel.listHeatwaveHistory).toHaveBeenLastCalledWith(expect.objectContaining({ year: "2023", min_category: 3, status: "ENDED" })));
  });

  it("opens an event, shows its evolution and the footprint for the chosen day across the date line", async () => {
    const user = userEvent.setup();
    render(<MemoryRouter><HeatwaveHistory dataset="pacific" region="pacific" /></MemoryRouter>);
    await user.click(await screen.findByRole("button", { name: /II \(Strong\)/ }));
    const panel = await screen.findByLabelText("Historical event detail");
    expect(within(panel).getByText("67 days")).toBeInTheDocument();
    await waitFor(() => expect(screen.getByTestId("map")).toHaveAttribute("data-date", "2023-08-30"));
    expect(screen.getByTestId("map")).toHaveAttribute("data-overlay-lon", "179.5,180.5");       // one footprint on a continuous axis
    expect(within(panel).getByRole("link", { name: /Show on the Ocean Map/ }).getAttribute("href")).toContain("date=2023-08-30");
    expect(within(panel).getByText(/in the cells this event covered on 2023-08-30/)).toBeInTheDocument();
    expect(within(panel).getByText(/not evidence that no animals were present/)).toBeInTheDocument();
  });

  it("states plainly when history is not available", async () => {
    intel.listHeatwaveHistory.mockRejectedValue(new Error("Historical marine-heatwave events have not been built for this dataset"));
    render(<MemoryRouter><HeatwaveHistory dataset="pacific" region="pacific" /></MemoryRouter>);
    expect(await screen.findByText(/have not been built for this dataset/)).toBeInTheDocument();
  });
});

describe("Pacific anomalies page", () => {
  const cell = (lat: number, lon: number, v: number, pct: number | null) => ({ lat, lon: lon < 0 ? lon + 360 : lon, lon_180: lon, anomaly_c: v, region: { id: "polynesia", name: "Polynesia" }, historical_percentile: pct, historical_samples: pct == null ? 4 : 449 });
  const analysis = () => ({
    dataset: dataset(), region: { id: "pacific", name: "Entire Pacific Ocean" }, date: "2026-10-22", latest_available_date: "2026-10-22", baseline: ["2012-01-01", "2023-12-31"], threshold_c: 1,
    summary: { mean_anomaly_c: 0.4, valid_cells: 16000, share_warm: 0.12, share_cold: 0.03, persistent_cells: 300, persistent_share: 0.019 },
    strongest_warm: [cell(10, -150, 3.4, 99.8)], strongest_cold: [cell(-40, 160, -2.1, 0.7), cell(-45, -100, -1.5, null)],
    persistent: [{ lat: 5, lon: 210, lon_180: -150, days: 40, anomaly_c: 1.8, direction: "warm", region: { id: "polynesia", name: "Polynesia" }, capped: false }], persistence_min_days: 7,
    timeline: { dates: ["2026-10-21", "2026-10-22"], mean_anomaly_c: [0.3, 0.4], share_warm: [0.1, 0.12], share_cold: [0.03, 0.03] },
    regions: [{ id: "polynesia", name: "Polynesia", mean_anomaly_c: 1.1, share_warm: 0.4, share_cold: 0, valid_cells: 900 }], method: "Anomaly = daily SST minus the daily climatology.", limits: ["No cause is claimed."],
  });

  beforeEach(() => {
    env.getAnomalyAnalysis.mockResolvedValue(analysis());
    env.getRegions.mockResolvedValue(REGIONS);
    env.getDatasets.mockResolvedValue({ default: "pacific", datasets: [dataset()] });
    env.getDates.mockResolvedValue({ dataset: "pacific", first_date: "2012-01-01", latest_date: "2026-10-22", n_dates: 5400 });
    env.getMap.mockResolvedValue({ dataset: dataset(), layer: "anomaly", label: "SST anomaly", unit: "degC", kind: "observed", diverging: true, date: "2026-10-22", region: { id: "pacific", name: "x" }, lat: [0.5], lon: [178.5], values: [[1]], min: 1, max: 1, coverage: { lat_min: 0, lat_max: 1, lon_min: 178, lon_max: 179 } });
    env.getReport.mockRejectedValue(new Error("not needed"));
  });

  it("answers what is strongest, what has lasted and how regions compare, with honest percentiles", async () => {
    render(<MemoryRouter><ActiveSelectionProvider><PacificAnomalies /></ActiveSelectionProvider></MemoryRouter>);
    const warm = await screen.findByLabelText("Strongest warm anomalies");
    expect(within(warm).getByText(/\+3\.4 °C/)).toBeInTheDocument();
    expect(within(warm).getByText(/warmer than 100% of 449 comparable days|warmer than 99% of 449/)).toBeInTheDocument();
    const cold = screen.getByLabelText("Strongest cold anomalies");
    expect(within(cold).getByText(/colder than 99% of 449 comparable days/)).toBeInTheDocument();
    expect(within(cold).getByText("History too short to rank")).toBeInTheDocument();         // too few earlier days: not ranked, not guessed
    expect(within(screen.getByLabelText("Persistent anomalies")).getByText(/40 consecutive days/)).toBeInTheDocument();
    expect(within(screen.getByLabelText("Regional comparison")).getByText("Polynesia")).toBeInTheDocument();
    expect(screen.getByText(/No cause is claimed/)).toBeInTheDocument();
    expect(env.getAnomalyAnalysis).toHaveBeenCalledWith("pacific", "pacific", undefined);
  });

  it("reports a failed analysis request", async () => {
    env.getAnomalyAnalysis.mockRejectedValue(new Error("Anomaly analysis failed"));
    render(<MemoryRouter><ActiveSelectionProvider><PacificAnomalies /></ActiveSelectionProvider></MemoryRouter>);
    expect(await screen.findByText(/Anomaly analysis failed/)).toBeInTheDocument();
  });

  it("uses the provider's real source name", () => {
    expect(PROVIDER.source.short_name).toBe("NOAA OISST v2.1");
  });
});
