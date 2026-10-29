import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import type { SstHistory } from "../api/environment";
import { dataset } from "./fixtures";

const env = vi.hoisted(() => ({ getSstHistory: vi.fn() }));
vi.mock("../api/environment", async (orig) => ({ ...(await orig<typeof import("../api/environment")>()), ...env }));
// the chart is replaced by a table of what it was asked to draw
vi.mock("recharts", () => {
  const Box = ({ children }: { children?: React.ReactNode }) => <div>{children}</div>;
  const Line = ({ dataKey, name, strokeDasharray }: { dataKey: string; name: string; strokeDasharray?: string }) => <i data-line={dataKey} data-name={name} data-dashed={strokeDasharray ? "yes" : "no"} />;
  const ComposedChart = ({ data, children }: { data: unknown[]; children?: React.ReactNode }) => <div data-testid="chart" data-rows={JSON.stringify(data)}>{children}</div>;
  return { ResponsiveContainer: Box, ComposedChart, Line, XAxis: Box, YAxis: Box, CartesianGrid: Box, Tooltip: Box, Legend: Box, ReferenceLine: Box, Brush: Box };
});

import HistoricalSst from "../components/HistoricalSst";
import { ActiveSelectionProvider } from "../contexts/ActiveSelection";
import { buildRows } from "../utils/sstHistory";

const annual = (y: number, m: number | null, an: number | null, complete = true) => ({ year: y, mean_sst: m, mean_anomaly: an, min_sst: m, max_sst: m, observations: m == null ? 0 : 360, expected_days: 365, coverage: m == null ? 0 : 0.99, complete });

function history(over: Partial<SstHistory> = {}): SstHistory {
  return {
    dataset: dataset(), scope: { type: "region", name: "Entire Pacific Ocean" }, region: { id: "pacific", name: "Entire Pacific Ocean" }, location: null, aggregation: "monthly",
    period: { start: "2018-01-01", end: "2022-12-31", available_start: "2018-01-01", available_end: "2022-12-31", years: 5 }, baseline: ["2018-01-01", "2021-12-31"],
    series: [{ date: "2018-01-01", sst: 22.1, anomaly: 0.1, observations: 31 }, { date: "2018-03-01", sst: 22.9, anomaly: 0.2, observations: 31 }],
    annual_summary: [annual(2018, 22.0, 0.0), annual(2019, 22.2, 0.2), annual(2020, 22.4, 0.4)],
    trend: { method: "ols", slope_per_year: 0.2, direction: "warming", significant: true, message: "A statistically significant warming trend over the available record (2018-2020); this is not an attribution to climate change.", n_years: 3, years_used: [2018, 2019, 2020], min_years_required: 3, ci95: [0.1, 0.3], reference_year: 2019, anomaly_at_reference_year: 0.2 },
    change: { from_year: 2018, to_year: 2020, mean_sst_change: 0.4, mean_anomaly_change: 0.4, basis: "last minus first complete year" }, percent_change: null, percent_change_note: "A percentage change of a Celsius temperature is not meaningful.",
    statistics: { mean_sst: 22.3, min_sst: 20.1, max_sst: 24.9, min_date: "2018-02-01", max_date: "2020-03-01", observations: 1700, expected_days: 1826, missing_days: 126, cells: 3000, complete_years: 3, years_without_data: [] },
    forecast: { kind: "forecast", label: "Forecast (model prediction, not an observation)", issued_from: "2022-12-31", model: "ConvLSTM", beats_persistence: false, series: [{ date: "2023-01-01", sst: 25.0, anomaly: 0.5 }, { date: "2023-01-02", sst: 25.1, anomaly: 0.6 }] },
    kind: "observed", statement: "SST trend over the available historical record (2018-2022); a record of this length does not by itself establish climate change.", limitations: [], ...over,
  };
}

function renderAt(url = "/") {
  return render(<MemoryRouter initialEntries={[url]}><ActiveSelectionProvider><HistoricalSst /></ActiveSelectionProvider></MemoryRouter>);
}
const rows = () => JSON.parse(screen.getByTestId("chart").getAttribute("data-rows")!) as { date: string; observed: number | null; forecast: number | null }[];

beforeEach(() => {
  vi.clearAllMocks();
  env.getSstHistory.mockImplementation(async (p: { lat?: number }) => (p.lat != null ? history({ scope: { type: "location", name: "5.50°N, 150.50°W" }, location: { latitude: p.lat, longitude: -150, cell: { lat: 5.5, lon: 209.5, lon_180: -150.5 } } }) : history()));
});

describe("buildRows", () => {
  it("leaves a visible gap for a month without data and never turns it into zero", () => {
    const r = buildRows("sst", "monthly", history().series, [], null, null);
    expect(r.map((x) => [x.date, x.observed])).toEqual([["2018-01-01", 22.1], ["2018-02-01", null], ["2018-03-01", 22.9]]);
  });
  it("keeps forecast values in their own column, after the observations", () => {
    const f = history().forecast!.series;
    const r = buildRows("sst", "monthly", history().series, [], f, null);
    const obs = r.filter((x) => x.observed != null), fc = r.filter((x) => x.forecast != null);
    expect(fc).toHaveLength(2);
    expect(fc.every((x) => x.observed === null)).toBe(true);
    expect(obs.every((x) => x.forecast === null)).toBe(true);
    expect(fc[0].t).toBeGreaterThan(obs[obs.length - 1].t);
  });
  it("builds one row per year for the annual view, with the trend only for complete years", () => {
    const a = [annual(2018, 22.0, 0.0), annual(2019, null, null, false), annual(2020, 22.4, 0.4, false)];
    const r = buildRows("annual", "annual", [], a, null, history().trend);
    expect(r.map((x) => x.observed)).toEqual([22.0, null, 22.4]);
    expect(r[0].trend).not.toBeNull();
    expect(r[2].trend).toBeNull();
  });
  it("uses the anomaly values in the anomaly view", () => {
    expect(buildRows("anomaly", "monthly", history().series, [], null, null)[0].observed).toBe(0.1);
  });
});

describe("Historical SST section", () => {
  it("shows the period, mean, change, trend and number of data points from the API", async () => {
    renderAt();
    const summary = await screen.findByLabelText("Historical SST summary");
    expect(summary).toHaveTextContent("2018–2022");
    expect(summary).toHaveTextContent("22.3 °C");
    expect(summary).toHaveTextContent("+0.40 °C");
    expect(summary).toHaveTextContent("+0.20 °C/year");
    expect(summary).toHaveTextContent("1,700");
    expect(screen.getByText(/SST trend over the available historical record \(2018-2022\)/)).toBeInTheDocument();
    expect(env.getSstHistory).toHaveBeenCalledWith({ dataset: "pacific", region: "pacific", lat: undefined, lon: undefined, aggregation: "monthly" });
  });

  it("draws observations and the forecast as separate lines, the forecast dashed and labelled", async () => {
    renderAt();
    await screen.findByTestId("chart");
    const lines = [...document.querySelectorAll("[data-line]")].map((l) => [l.getAttribute("data-line"), l.getAttribute("data-name"), l.getAttribute("data-dashed")]);
    expect(lines).toContainEqual(["observed", "Observed SST (°C)", "no"]);
    expect(lines).toContainEqual(["forecast", "Forecast (model prediction)", "yes"]);
    expect(screen.getByText(/it is a prediction, not an observation/)).toBeInTheDocument();
    expect(rows().filter((r) => r.forecast != null).every((r) => r.observed === null)).toBe(true);
  });

  it("uses the place picked on the map and returns to the region when it is cleared", async () => {
    const user = userEvent.setup();
    renderAt("/?lat=5.5&lon=-150.5");
    await waitFor(() => expect(env.getSstHistory).toHaveBeenCalledWith(expect.objectContaining({ lat: 5.5, lon: -150.5 })));
    expect(await screen.findByText(/5.50°N, 150.50°W/)).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: /instead/ }));
    await waitFor(() => expect(env.getSstHistory).toHaveBeenLastCalledWith(expect.objectContaining({ lat: undefined, lon: undefined })));
    expect(await screen.findByText(/Entire Pacific Ocean/)).toBeInTheDocument();
  });

  it("switches between SST, anomaly and annual mean", async () => {
    const user = userEvent.setup();
    renderAt();
    await screen.findByTestId("chart");
    await user.click(screen.getByRole("radio", { name: "SST anomaly" }));
    expect(document.querySelector('[data-line="observed"]')).toHaveAttribute("data-name", "Observed anomaly (°C)");
    expect(rows()[0].observed).toBe(0.1);
    await user.click(screen.getByRole("radio", { name: "Annual mean SST" }));
    expect(document.querySelector('[data-line="observed"]')).toHaveAttribute("data-name", "Observed annual mean (°C)");
    expect(document.querySelector('[data-line="trend"]')).toBeInTheDocument();
    expect(document.querySelector('[data-line="forecast"]')).not.toBeInTheDocument();
    expect(rows().map((r) => r.observed)).toEqual([22.0, 22.2, 22.4]);
  });

  it("asks for daily values when chosen", async () => {
    const user = userEvent.setup();
    renderAt();
    await screen.findByTestId("chart");
    await user.selectOptions(screen.getByLabelText("Resolution"), "daily");
    await waitFor(() => expect(env.getSstHistory).toHaveBeenLastCalledWith(expect.objectContaining({ aggregation: "daily" })));
  });

  it("says plainly when there is too little history for a trend", async () => {
    env.getSstHistory.mockResolvedValue(history({ trend: { method: "ols", slope_per_year: null, direction: "insufficient_data", significant: null, message: "Insufficient historical data for trend estimation: 2 complete year(s) with data, at least 8 are needed.", n_years: 2, years_used: [], min_years_required: 8 }, change: null }));
    renderAt();
    const summary = await screen.findByLabelText("Historical SST summary");
    expect(summary).toHaveTextContent("n/a");
    expect(summary).toHaveTextContent("record too short");
    expect(screen.getByText(/Insufficient historical data for trend estimation/)).toBeInTheDocument();
  });

  it("says so when there are no observations, and when the backend fails", async () => {
    env.getSstHistory.mockResolvedValueOnce(history({ series: [], annual_summary: [], forecast: null }));
    const { unmount } = renderAt();
    expect(await screen.findByText(/No SST observations are available for this place and period/)).toBeInTheDocument();
    unmount();
    env.getSstHistory.mockRejectedValue(new Error("The backend server could not be reached."));
    renderAt();
    expect(await screen.findByText(/could not be reached/)).toBeInTheDocument();
    expect(screen.queryByTestId("chart")).not.toBeInTheDocument();
  });

  it("reports a land or unusable location returned by the API instead of drawing anything", async () => {
    env.getSstHistory.mockRejectedValue(new Error("This location is land: there is no SST history for it."));
    renderAt("/?lat=30&lon=120");
    expect(await screen.findByText(/This location is land/)).toBeInTheDocument();
  });
});
