import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { dataset, mapResponse, REGIONS, report, speciesLayer } from "./fixtures";

const env = vi.hoisted(() => ({
  getDatasets: vi.fn(), getRegions: vi.fn(), getDates: vi.fn(), getMap: vi.fn(), getForecastMap: vi.fn(), getSpeciesLayer: vi.fn(), getReport: vi.fn(), getSpeciesExposure: vi.fn(),
}));
const intel = vi.hoisted(() => ({ getHeatwaveMap: vi.fn(), getRiskMap: vi.fn(), getSpeciesDistribution: vi.fn(), listHeatwaves: vi.fn(), listSpecies: vi.fn() }));
const outputs = vi.hoisted(() => ({ listAlerts: vi.fn() }));
vi.mock("../api/environment", async (orig) => ({ ...(await orig<typeof import("../api/environment")>()), ...env }));
vi.mock("../api/intelligence", async (orig) => ({ ...(await orig<typeof import("../api/intelligence")>()), ...intel }));
vi.mock("../api/modelOutputs", async (orig) => ({ ...(await orig<typeof import("../api/modelOutputs")>()), ...outputs }));

// Leaflet needs a real layout engine; the map component is replaced by a stub that exposes what it was given
vi.mock("../components/SstMap", () => ({
  default: (p: { layer: { label: string; date: string; lon: number[] } | null; markers?: { key: string; label: string; onClick?: () => void }[]; overlay: unknown; lonOrigin: number | null; unavailable?: boolean; selected?: { lat: number; lon: number } | null; onPick?: (a: number, b: number) => void }) => (
    <div data-testid="map" data-layer={p.layer?.label ?? ""} data-date={p.layer?.date ?? ""} data-overlay={p.overlay ? "yes" : "no"} data-origin={p.lonOrigin ?? ""} data-unavailable={String(!!p.unavailable)} data-selected={p.selected ? `${p.selected.lat},${p.selected.lon}` : ""}>
      <button type="button" onClick={() => p.onPick?.(10, -150)}>pick ocean</button>
      {p.markers?.map((m) => <button key={m.key} type="button" data-testid="marker" onClick={m.onClick}>{m.label}</button>)}
    </div>
  ),
}));

import { ActiveSelectionProvider } from "../contexts/ActiveSelection";
import { clearCached } from "../hooks/useCached";
import OceanMapPage from "../pages/OceanMapPage";

function renderAt(url = "/ocean-map") {
  return render(
    <MemoryRouter initialEntries={[url]}>
      <ActiveSelectionProvider>
        <OceanMapPage />
      </ActiveSelectionProvider>
    </MemoryRouter>,
  );
}

const hwMap = (date: string) => ({ dataset: "pacific", region: { id: "pacific", name: "Entire Pacific Ocean" }, layer: "heatwave", label: "Marine-heatwave anomaly", unit: "degC", kind: "derived", horizon: 0, date, diverging: true,
  coverage: { lat_min: 0, lat_max: 2, lon_min: 178, lon_max: 182 }, lat: [0.5, 1.5], lon: [178.5, 179.5], values: [[2.1, null], [null, 1.8]], min: 1.8, max: 2.1, active_cells: 2 });
const riskMap = (date: string) => ({ dataset: "pacific", region: { id: "pacific", name: "Entire Pacific Ocean" }, label: "Ecological risk", unit: "score", date, lat: [0.5, 1.5], lon: [178.5, 179.5], values: [[0.7, null], [null, 0.2]], status: [[0, 1], [3, 0]] });

beforeEach(() => {
  vi.clearAllMocks();
  window.sessionStorage.clear();
  clearCached();
  env.getDatasets.mockResolvedValue({ default: "pacific", datasets: [dataset(), dataset({ id: "ne_pacific", name: "NE Pacific study region" })] });
  env.getRegions.mockResolvedValue(REGIONS);
  env.getDates.mockImplementation(async (id: string) => ({ dataset: id, first_date: "2012-01-01", latest_date: "2026-10-22", n_dates: 5400 }));
  env.getMap.mockImplementation(async (q: { layer: "sst" | "anomaly"; date: string; dataset: string }) => mapResponse(q.layer, q.date === "latest" ? "2026-10-22" : q.date, q.dataset));
  env.getForecastMap.mockResolvedValue({ dataset: "pacific", region: { id: "pacific", name: "x" }, horizon: 7, label: "Forecast SST", unit: "degC", date: "2026-10-29", diverging: false, coverage: { lat_min: 0, lat_max: 2, lon_min: 178, lon_max: 182 }, lat: [0.5], lon: [178.5], values: [[27]], min: 27, max: 27 });
  env.getSpeciesLayer.mockResolvedValue(speciesLayer());
  env.getReport.mockResolvedValue(report());
  env.getSpeciesExposure.mockResolvedValue({ available: false });
  intel.getHeatwaveMap.mockImplementation(async (_d: string, _r: string, date?: string) => hwMap(date ?? "2026-10-22"));
  intel.getRiskMap.mockImplementation(async (_d: string, _r: string, date?: string) => riskMap(date ?? "2026-10-22"));
  intel.listHeatwaves.mockResolvedValue({ summary: {}, total: 2, items: [{}, {}], dataset: "pacific" });
  intel.listSpecies.mockResolvedValue({ items: [], total: 0 });
  intel.getSpeciesDistribution.mockResolvedValue({ geojson: null });
  outputs.listAlerts.mockResolvedValue({ items: [
    { id: "a1", severity: "CRITICAL", alert_type: "MARINE_HEATWAVE", latitude: 12, longitude: 200, timestamp: "2026-10-22T00:00:00Z" },
    { id: "a2", severity: "MEDIUM", alert_type: "SST_ANOMALY", latitude: -20, longitude: 175, timestamp: "2026-10-22T00:00:00Z" },
  ], total: 2 });
});

const map = () => screen.getByTestId("map");

describe("Ocean Map: layers, dates and datasets", () => {
  it("opens on the whole-Pacific SST layer for the latest date", async () => {
    renderAt();
    await waitFor(() => expect(map()).toHaveAttribute("data-layer", "Sea surface temperature"));
    expect(env.getMap).toHaveBeenCalledWith(expect.objectContaining({ dataset: "pacific", layer: "sst", date: "latest", region: "pacific" }));
    expect(map()).toHaveAttribute("data-date", "2026-10-22");
  });

  it("switches between layers and requests exactly the data of the chosen layer", async () => {
    const user = userEvent.setup();
    renderAt();
    await waitFor(() => expect(map()).toHaveAttribute("data-layer", "Sea surface temperature"));
    await user.click(screen.getByRole("radio", { name: "Anomaly" }));
    await waitFor(() => expect(map()).toHaveAttribute("data-layer", "SST anomaly"));
    await user.click(screen.getByRole("radio", { name: "Marine heatwaves" }));
    await waitFor(() => expect(map()).toHaveAttribute("data-layer", "Marine-heatwave anomaly"));
    await user.click(screen.getByRole("radio", { name: "Ecological risk" }));
    await waitFor(() => expect(map()).toHaveAttribute("data-layer", "Ecological risk"));
    await user.click(screen.getByRole("radio", { name: "Forecast SST" }));
    await waitFor(() => expect(map()).toHaveAttribute("data-layer", "Forecast SST"));
    expect(env.getForecastMap).toHaveBeenCalledWith("pacific", 7, "pacific", "sst");
  });

  it("passes the selected date to the observed, heatwave and risk layers", async () => {
    const user = userEvent.setup();
    renderAt("/ocean-map?date=2026-09-15&layer=heatwave");
    await waitFor(() => expect(map()).toHaveAttribute("data-date", "2026-09-15"));
    expect(intel.getHeatwaveMap).toHaveBeenCalledWith("pacific", "pacific", "2026-09-15");
    await user.click(screen.getByRole("radio", { name: "Ecological risk" }));
    await waitFor(() => expect(intel.getRiskMap).toHaveBeenCalledWith("pacific", "pacific", "2026-09-15"));
    await user.click(screen.getByRole("radio", { name: "SST" }));
    await waitFor(() => expect(env.getMap).toHaveBeenCalledWith(expect.objectContaining({ layer: "sst", date: "2026-09-15" })));
  });

  it("changing the date requests that date and never leaves a stale layer on screen", async () => {
    let releaseSlow: (v: unknown) => void = () => undefined;
    env.getMap.mockImplementation((q: { layer: "sst" | "anomaly"; date: string; dataset: string }) => {
      if (q.date === "2026-10-01") return new Promise((res) => { releaseSlow = res; });
      return Promise.resolve(mapResponse(q.layer, q.date === "latest" ? "2026-10-22" : q.date));
    });
    renderAt();
    await waitFor(() => expect(map()).toHaveAttribute("data-date", "2026-10-22"));
    const date = await screen.findByLabelText("Date");
    await waitFor(() => expect(date).toBeEnabled());
    fireEvent.change(date, { target: { value: "2026-10-01" } });
    await waitFor(() => expect(env.getMap).toHaveBeenCalledWith(expect.objectContaining({ date: "2026-10-01" })));
    expect(map()).toHaveAttribute("data-layer", "");                              // nothing from another date is shown while the new one loads
    fireEvent.change(date, { target: { value: "2026-10-05" } });
    await waitFor(() => expect(map()).toHaveAttribute("data-date", "2026-10-05"));
    await act(async () => releaseSlow(mapResponse("sst", "2026-10-01")));         // the older request finishes last
    expect(map()).toHaveAttribute("data-date", "2026-10-05");                     // and is ignored
  });

  it("switching dataset reloads the map for that dataset and resets the date", async () => {
    const user = userEvent.setup();
    renderAt("/ocean-map?date=2026-09-15");
    await waitFor(() => expect(map()).toHaveAttribute("data-date", "2026-09-15"));
    await user.selectOptions(screen.getByLabelText("Dataset"), "ne_pacific");
    await waitFor(() => expect(env.getMap).toHaveBeenCalledWith(expect.objectContaining({ dataset: "ne_pacific", date: "latest" })));
    expect((screen.getByRole("radio", { name: "Forecast SST" }) as HTMLButtonElement).disabled).toBe(true);   // that dataset has no forecast: layer unavailable, not faked
  });

  it("keeps the antimeridian grid on one continuous east-longitude axis", async () => {
    renderAt();
    await waitFor(() => expect(map()).toHaveAttribute("data-layer", "Sea surface temperature"));
    expect(map()).toHaveAttribute("data-origin", "178");                          // 178 .. 182 east: the grid crosses 180 without being re-wrapped
  });
});

describe("Ocean Map: overlays, markers and filters", () => {
  it("shows only threatened species by default and filters by conservation status", async () => {
    const user = userEvent.setup();
    renderAt("/ocean-map?species=1");
    await waitFor(() => expect(screen.getAllByTestId("marker")).toHaveLength(2));
    expect(screen.getAllByTestId("marker").some((m) => m.textContent?.includes("· LC"))).toBe(false);          // the least-concern record is filtered out
    expect(screen.getAllByTestId("marker").some((m) => m.textContent?.includes("· EN") && m.textContent?.includes("inside a marine heatwave"))).toBe(true);
    const status = screen.getByLabelText("Conservation status");
    await user.selectOptions(status, "ALL");
    await waitFor(() => expect(screen.getAllByTestId("marker")).toHaveLength(4));
    expect(screen.getAllByTestId("marker").every((m) => m.textContent?.includes("record density, not a range"))).toBe(true);
    await user.selectOptions(status, "EN");
    await waitFor(() => expect(screen.getAllByTestId("marker")).toHaveLength(1));
    expect(screen.getByTestId("marker").textContent).toContain("· EN");
    await user.selectOptions(status, "VU");
    await waitFor(() => expect(screen.getAllByTestId("marker")).toHaveLength(1));
    expect(screen.getByTestId("marker").textContent).toContain("· VU");
    await user.selectOptions(status, "CR");
    await waitFor(() => expect(screen.queryAllByTestId("marker")).toHaveLength(0));                           // none recorded: no markers, nothing invented
    await user.selectOptions(status, "NT");
    await waitFor(() => expect(screen.getAllByTestId("marker")).toHaveLength(1));
    expect(screen.getByTestId("marker").textContent).toContain("· NT");
  });

  it("limits species and alerts to the selected region only when asked; the base map stays whole", async () => {
    const user = userEvent.setup();
    renderAt("/ocean-map?species=1&alerts=1");
    await waitFor(() => expect(env.getSpeciesLayer).toHaveBeenCalledWith("pacific", "pacific", undefined));
    await user.selectOptions(screen.getByLabelText("Region"), "polynesia");
    expect(env.getMap).not.toHaveBeenCalledWith(expect.objectContaining({ region: "polynesia" }));        // regions only zoom the map
    await user.click(screen.getByLabelText("Limit markers to region"));
    await waitFor(() => expect(env.getSpeciesLayer).toHaveBeenCalledWith("pacific", "polynesia", undefined));
    await waitFor(() => expect(outputs.listAlerts).toHaveBeenCalledWith(expect.objectContaining({ region: "polynesia", dataset: "pacific" })));
  });

  it("filters alert markers by severity", async () => {
    const user = userEvent.setup();
    renderAt("/ocean-map?alerts=1");
    await waitFor(() => expect(screen.getAllByTestId("marker")).toHaveLength(2));
    await user.selectOptions(screen.getByLabelText("Alert severity"), "HIGH");
    await waitFor(() => expect(screen.getAllByTestId("marker")).toHaveLength(1));
    expect(screen.getByTestId("marker").textContent).toContain("CRITICAL alert");
  });

  it("turns the marine-heatwave footprint overlay on and off", async () => {
    const user = userEvent.setup();
    renderAt();
    await waitFor(() => expect(map()).toHaveAttribute("data-overlay", "yes"));
    await user.click(screen.getByLabelText(/Marine heatwave footprints/));
    await waitFor(() => expect(map()).toHaveAttribute("data-overlay", "no"));
  });
});

describe("Ocean Map: location report and deep links", () => {
  it("opens the unified report for a clicked place, for the shown dataset and date", async () => {
    const user = userEvent.setup();
    renderAt("/ocean-map?date=2026-10-20");
    await waitFor(() => expect(map()).toHaveAttribute("data-date", "2026-10-20"));
    await user.click(screen.getByRole("button", { name: "pick ocean" }));
    await waitFor(() => expect(env.getReport).toHaveBeenCalledWith("pacific", 10, -150, "2026-10-20"));
    const rep = await screen.findByRole("complementary", { name: "Location report" });
    expect(await within(rep).findByText(/This cell is inside a marine heatwave/)).toBeInTheDocument();
    expect(within(rep).getByText(/Historical context: warmer than 98% of 449 same-season anomalies/)).toBeInTheDocument();
    expect(within(rep).getAllByText("HIGH").length).toBeGreaterThan(0);
    expect(within(rep).getByText(/not evidence that no species are present/)).toBeInTheDocument();
    expect(within(rep).getByText(/Forecast \(model prediction\)/)).toBeInTheDocument();
    expect(within(rep).getByText(/NOAA OISST v2.1 \(observations\)/)).toBeInTheDocument();
  });

  it("an alert link restores the layer, date and exact place it points to", async () => {
    renderAt("/ocean-map?dataset=pacific&region=polynesia&alerts=1&date=2026-10-18&layer=risk&lat=-17.5&lon=-149.5");
    await waitFor(() => expect(map()).toHaveAttribute("data-layer", "Ecological risk"));
    expect(intel.getRiskMap).toHaveBeenCalledWith("pacific", "pacific", "2026-10-18");
    expect(map()).toHaveAttribute("data-selected", "-17.5,-149.5");
    await waitFor(() => expect(env.getReport).toHaveBeenCalledWith("pacific", -17.5, -149.5, "2026-10-18"));
    expect(outputs.listAlerts).toHaveBeenCalled();
  });

  it("clicking an alert marker opens the report at the alert's coordinates", async () => {
    const user = userEvent.setup();
    renderAt("/ocean-map?alerts=1");
    const marker = (await screen.findAllByTestId("marker"))[0];
    await user.click(marker);
    await waitFor(() => expect(env.getReport).toHaveBeenCalledWith("pacific", 12, -160, undefined));      // longitude 200 east is -160
  });
});

describe("Ocean Map: missing data and failures", () => {
  it("says so when the layer cannot be loaded, without drawing anything", async () => {
    env.getMap.mockRejectedValue(new Error("No data for this date"));
    renderAt();
    expect(await screen.findByRole("alert")).toHaveTextContent(/Map data unavailable/);
    expect(map()).toHaveAttribute("data-layer", "");
    expect(map()).toHaveAttribute("data-unavailable", "true");
  });

  it("reports an unreachable dataset service instead of an empty map", async () => {
    env.getDatasets.mockRejectedValue(new Error("Network Error"));
    renderAt();
    expect(await screen.findByRole("alert")).toHaveTextContent(/Environmental datasets unavailable/);
  });

  it("reports a dataset that the backend does not provide", async () => {
    renderAt("/ocean-map?dataset=atlantic");
    expect(await screen.findByRole("alert")).toHaveTextContent(/does not provide a dataset called "atlantic"/);
  });

  it("shows the report error when the report request fails", async () => {
    const user = userEvent.setup();
    env.getReport.mockRejectedValue(new Error("report failed"));
    renderAt();
    await waitFor(() => expect(map()).toHaveAttribute("data-layer", "Sea surface temperature"));
    await user.click(screen.getByRole("button", { name: "pick ocean" }));
    expect(await screen.findByText(/Location report unavailable/)).toBeInTheDocument();
  });

  it("explains land and no-data cells in the report instead of showing zeros", async () => {
    const user = userEvent.setup();
    env.getReport.mockResolvedValue(report({ status: "land", message: "This location is land.", conditions: undefined, anomaly: undefined, heatwave: undefined, risk: undefined }));
    renderAt();
    await waitFor(() => expect(map()).toHaveAttribute("data-layer", "Sea surface temperature"));
    await user.click(screen.getByRole("button", { name: "pick ocean" }));
    expect(await screen.findByText("This location is land.")).toBeInTheDocument();
    expect(screen.queryByText(/°C sea surface temperature/)).not.toBeInTheDocument();
  });
});

describe("Ocean Map: small screens", () => {
  it("keeps the controls behind one button until opened", async () => {
    const user = userEvent.setup();
    renderAt();
    const toggle = screen.getByRole("button", { name: /Layers and controls/ });
    expect(toggle).toHaveAttribute("aria-expanded", "false");
    const group = screen.getByRole("radiogroup", { name: "Map layer" });
    expect(group.closest("div.hidden")).not.toBeNull();                      // hidden below the xl breakpoint until opened
    await user.click(toggle);
    expect(screen.getByRole("button", { name: /Hide layers and controls/ })).toHaveAttribute("aria-expanded", "true");
    expect(group.closest("div.hidden")).toBeNull();
  });

  it("shows the report as a bottom sheet once a place is selected", async () => {
    const user = userEvent.setup();
    const { container } = renderAt();
    await waitFor(() => expect(map()).toHaveAttribute("data-layer", "Sea surface temperature"));
    expect(container.querySelector(".fixed.inset-x-0.bottom-0")).toBeNull();
    await user.click(screen.getByRole("button", { name: "pick ocean" }));
    expect(container.querySelector(".fixed.inset-x-0.bottom-0")).not.toBeNull();
  });
});
