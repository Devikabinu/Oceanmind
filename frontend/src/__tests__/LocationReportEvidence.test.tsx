import { cleanup, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import type { ForecastExplanation, ForecastModelInfo, LocationReportData } from "../api/environment";
import { report } from "./fixtures";

const env = vi.hoisted(() => ({ getReport: vi.fn(), getSpeciesExposure: vi.fn(), getForecastExplanation: vi.fn(), getForecastModel: vi.fn(), getDataDates: vi.fn(), getPhysicalDrivers: vi.fn() }));
vi.mock("../api/environment", async (orig) => ({ ...(await orig<typeof import("../api/environment")>()), ...env }));

import LocationReport from "../components/LocationReport";
import DataDatesNote from "../components/DataDatesNote";
import { ActiveSelectionProvider } from "../contexts/ActiveSelection";
import { clearCached } from "../hooks/useCached";

const driver = (factor: string, label: string, over: Record<string, unknown> = {}) => ({
  factor, label, weight: 0.25, effective_weight: 0.25, available: true, status: "contributing", status_text: "Evidence present and contributing to the score", raw: 1.2, raw_unit: "°C", saturation_at: 3,
  saturated: false, ratio: 0.4, value: 0.4, value_exact: 0.4, level: "MEDIUM", contribution: 0.1, weight_share: 0.25, explanation: `${label} explanation`, ...over,
});

const risk = (drivers: unknown[], over: Record<string, unknown> = {}) => ({
  status: "assessed", score: 0.41, level: "MEDIUM", evidence_completeness: 0.8, drivers, explanation: { headline: "h", sections: [{ id: "what", title: "t", text: "x", bullets: [] }] },
  score_breakdown: { terms: [], sum: 0.41, denominator_weight: 0.8, formula: "f", text: "0.14 + 0.10 + 0.08 + 0.09 = 0.41" }, ...over,
});

const SPECIES = { items: [], summary: "s", evidence: "observed", radius_deg: 5 };
const model = (): ForecastModelInfo => ({
  dataset: "pacific", name: "ConvLSTM (2 layers, 32 hidden channels)", checkpoint: { which: "best", epoch: 12, val_loss: 0.1 }, architecture: null, architecture_text: ["A ConvLSTM combines convolutions and an LSTM."],
  input: { window_days: 7, channels: ["sst", "sst_anom"], description: "The previous 7 daily maps", not_inputs: "Ocean currents, winds and ENSO are not inputs of this model." },
  output: { variable: "sst (°C)", horizons: [1, 2, 3, 4, 5, 6, 7], form: "residual" },
  normalisation: { method: "z-score", dataset_statistics: { sst: { mean: 20, std: 8 } }, statistics_period: ["2012-01-01", "2023-12-31"], applied: "converted" },
  training: { trained_on: "ne_pacific", retrained_for_this_dataset: false }, periods: { dataset_training: null, validation: null, test: { start: "2024-01-01", end: "2025-12-31", days: 730 } },
  evaluation: null, kinds: {},
});
const explanation = (over: Partial<ForecastExplanation> = {}): ForecastExplanation => ({
  available: true, dataset: "pacific", issued_from: "2026-10-27", latest_observation: "2026-10-27", model: model(),
  current: { date: "2026-10-27", sst_c: 28.4, climatological_sst_c: 27.1, anomaly_c: 1.3, relation: "warmer", recent_trend_c_per_day: 0.05, recent_change_c: 0.3, statement: "Current SST is 28.4 °C, approximately 1.3 °C above the climatological value.",
    trend_statement: "Over the 7 days the model was given, SST changed by +0.30 °C.", window: [0.9, 1.0, 1.1, 1.2, 1.2, 1.3, 1.3].map((a, k) => ({ date: `2026-10-${21 + k}`, sst_c: 28.0 + 0.06 * k, climatology_c: 27.1, anomaly_c: a })) },
  forecast: Array.from({ length: 7 }, (_, k) => ({ day: k + 1, date: `2026-10-${28 + k > 31 ? "0" : ""}${28 + k}`, sst_c: 28.5, anomaly_c: 1.3, change_vs_latest_c: 0.1, direction: "warmer", typical_error_c: 0.4,
    statement: `+${k + 1} day: SST is forecast to be 28.5 °C` })),
  model_explanation: [{ kind: "model_explanation", label: "Model explanation", text: "Which input day matters: the newest." }, { kind: "physical_cause", label: "Physical cause", text: "Not modelled: currents and winds." }],
  sensitivity: { method: "m", title: "Model sensitivity: not causal attribution", plain: "Each number is how many °C the forecast changes.", reading: "r", neighbourhood_deg: 8, block_deg: 8,
    temporal: { days: ["2026-10-27"], delta_c: [[0.1, 0.1, 0.1, 0.1, 0.1, 0.1, 0.1]] }, local_all_days_c: [0.2, 0.2, 0.2, 0.2, 0.2, 0.2, 0.2], everywhere_all_days_c: [0.3, 0.3, 0.3, 0.3, 0.3, 0.3, 0.3],
    spatial: { lat_edges: [0, 8], lon_edges: [0, 8], delta_c: Array.from({ length: 7 }, () => [[0.1]]), own_block: [0, 0] } },
  statement: "Model-predicted contributing patterns are different from a physical causal explanation.",
  interpretation: { direction: "warming", anomaly_trajectory: "strengthening", start_anomaly_c: 1.3, end_anomaly_c: 1.9, total_change_c: 0.6, sst_change_c: 0.4, forecast_outlook: "warming", anomaly_outlook: "strengthening",
    text: "The model predicts continued warming. The warm anomaly strengthens: +1.3 °C now to +1.9 °C at day +7.", plain: "The recent SST anomaly is +1.3 °C (positive) and the forecast takes it to +1.9 °C by day +7 (the anomaly is strengthening). SST was rising by 0.30 °C over the 7 input days and the forecast continues in the same direction, indicating warmer conditions over the forecast period." },
  inputs: { latest_observation: "2026-10-27", window: { start: "2026-10-21", end: "2026-10-27", days: 7 }, latest_sst_c: 28.4, latest_anomaly_c: 1.3, sst_trend_7d_c_per_day: 0.05, sst_change_7d_c: 0.3, anomaly_change_7d_c: 0.4, sst_trend_3d_c_per_day: 0.08,
    anomaly_change_3d_c: 0.2, grid: { rows: 125, cols: 190, resolution_deg: 1 }, cell: { lat: 10.5, lon: 209.5 }, channels: ["sst", "sst_anom", "sst_grad", "doy_sin", "doy_cos", "mask_sst"], window_days: 7, horizons: [1, 2, 3, 4, 5, 6, 7],
    spatial_context: "The network sees the whole grid at once: each place is processed together with its neighbourhood." },
  signals: [{ rank: 1, id: "newest_day", label: "Anomaly on the newest input day (2026-10-27)", contribution_c: 0.62, response_when_removed_c: -0.62, relative: 1, direction: "pushes the forecast warmer", sentence: "s1" },
    { rank: 2, id: "local", label: "Anomaly within ±8° of this place, all input days", contribution_c: 0.41, response_when_removed_c: -0.41, relative: 0.66, direction: "pushes the forecast warmer", sentence: "s2" },
    { rank: 3, id: "earlier_day", label: "Anomaly on the largest earlier input day (2026-10-25)", contribution_c: -0.08, response_when_removed_c: 0.08, relative: 0.13, direction: "no clear push", sentence: "s3" }],
  model_evidence: ["The model predicts continued warming. The warm anomaly strengthens: +1.3 °C now to +1.9 °C at day +7.", "Removing this anomaly would change the day +7 predicted anomaly by -0.62 °C, so the model prediction is sensitive to it."],
  physical_cause: "Cannot be established by this model. Ocean currents, winds and ENSO are not inputs of this model.",
  counterfactual: { horizon: 7, title: "Model sensitivity: not causal attribution", date: "2026-11-03", reading: "Removing the observed warm anomaly of the newest input day from the input sequence would reduce the day +7 predicted anomaly by 0.62 °C.",
    rows: [{ label: "Model output with the observed input", sst_c: 28.9, anomaly_c: 1.9, difference_c: 0, note: "" }, { label: "Anomaly of 2026-10-27 removed (replaced by normal conditions)", sst_c: 28.28, anomaly_c: 1.28, difference_c: -0.62, note: "" }] },
  ...over,
} as ForecastExplanation);

/** The report is in tabs; this opens one of them (the other tabs stay in the page but are hidden). */
const goTab = async (name: string) => { await userEvent.setup().click(await screen.findByRole("tab", { name: new RegExp(`^${name}`) })); };

function show(rep: LocationReportData) {
  env.getReport.mockResolvedValue(rep);
  return render(
    <MemoryRouter>
      <ActiveSelectionProvider>
        <LocationReport point={{ lat: 10, lon: -150 }} dataset="pacific" date={null} />
      </ActiveSelectionProvider>
    </MemoryRouter>,
  );
}

beforeEach(() => {
  vi.clearAllMocks();
  window.sessionStorage.clear();
  clearCached();
  env.getSpeciesExposure.mockResolvedValue({ available: false });
  env.getForecastModel.mockResolvedValue(model());
  env.getPhysicalDrivers.mockResolvedValue({ available: false, status: "disabled", message: "Physical-driver retrieval is switched off." });
  env.getForecastExplanation.mockResolvedValue(explanation());
});

describe("Why this risk?", () => {
  it("shows measured value, factor, weight and contribution for every contributing driver and the final sum", async () => {
    show(report({ risk: risk([driver("anomaly", "Anomaly"), driver("persistence", "Persistence", { raw: 12, raw_unit: "days", value: 0.86, contribution: 0.2 })]) as never }));
    const a = await screen.findByText("Anomaly explanation");
    const li = a.closest("li") as HTMLElement;
    expect(within(li).getByText(/Measured/)).toBeInTheDocument();
    expect(within(li).getByText("Factor (0–1)")).toBeInTheDocument();
    expect(within(li).getByText("Weight")).toBeInTheDocument();
    expect(within(li).getByText("Contribution")).toBeInTheDocument();
    expect(screen.getByTestId("score-sum")).toHaveTextContent("0.14 + 0.10 + 0.08 + 0.09 = 0.41");
  });

  it("does not call small-but-present evidence 'insufficient' and marks a saturated factor as saturated", async () => {
    show(report({ risk: risk([driver("anomaly", "Anomaly", { status: "below_threshold", value: 0.1, level: "LOW" }), driver("forecast", "Forecast", { saturated: true, value: 1, raw: 4.2 })]) as never }));
    expect(await screen.findByText("Active, low")).toBeInTheDocument();
    const panel = screen.getByTestId("score-sum").closest("details") as HTMLElement;
    expect(within(panel).queryByText(/insufficient/i)).not.toBeInTheDocument();
    expect(screen.getByText(/Saturated because the forecast anomaly exceeds the scoring threshold \(3 °C\)/)).toBeInTheDocument();
    expect(screen.getByText(/has reached the top of its 0–1 scale/)).toBeInTheDocument();
  });

  it("names the missing input of an unavailable driver instead of showing a number", async () => {
    show(report({ risk: risk([driver("overlap", "Species overlap", { available: false, status: "unavailable", value: null, contribution: null, raw: null, missing_input: "stored biodiversity records in this 2x2 degree block", explanation: "Missing input: x" })]) as never }));
    expect(await screen.findByText("Excluded from score")).toBeInTheDocument();
    expect(screen.getByText(/No stored data were found for this indicator \(stored biodiversity records in this 2x2 degree block\)/)).toBeInTheDocument();
  });
});

describe("risk with fewer indicators", () => {
  it("states the indicators used in one line and keeps unavailable ones under Data details", async () => {
    show(report({ risk: risk([driver("anomaly", "Anomaly"), driver("overlap", "Species overlap", { available: false, status: "unavailable", value: null, contribution: null, raw: null, missing_input: "stored biodiversity records in this 2x2 degree block", explanation: "x" })]) as never }));
    expect(await screen.findByTestId("indicators-used")).toHaveTextContent("Risk based on 1 available indicator: Anomaly.");
    const det = screen.getByTestId("data-details");
    expect(det).toHaveTextContent(/1 indicator excluded from the score/);
    expect(det).toHaveTextContent(/never counted as zero or as one/);
    expect(screen.getByTestId("score-sum").closest("details")).not.toContainElement(det);
  });
});

describe("species evidence label", () => {
  it("states exactly what is counted", async () => {
    show(report({ species: { ...SPECIES, counted: { observations: 66, distinct_species: 9, listed: 9, radius_deg: 5, window_days: 730, latest_record: "2026-09-01", label: "Species observations within about 5° of this location (last 2 years): 66; distinct species: 9." } } as never }));
    expect(await screen.findByTestId("species-counted")).toHaveTextContent("Species observations within about 5° of this location (last 2 years): 66; distinct species: 9.");
  });

  it("shows a coverage message, never 0, when there are no observations", async () => {
    show(report({ species: { ...SPECIES, evidence: "insufficient_coverage", counted: { observations: 0, distinct_species: 0, listed: 0, radius_deg: 5, window_days: 730, latest_record: null, label: "No stored biodiversity observations for this location and time period (a sampling gap, not absence)." } } as never }));
    expect(await screen.findByTestId("species-counted")).toHaveTextContent(/^No stored biodiversity observations/);
  });
});

describe("data availability and implications", () => {
  const dd = (aligned: boolean) => ({ sst_observation: { date: "2026-10-27", latest_available: "2026-10-27", note: "n" }, anomaly: { date: "2026-10-27", baseline: ["2012-01-01", "2023-12-31"] as [string, string] }, marine_heatwave: { date: aligned ? "2026-10-27" : "2026-10-22" },
    forecast: { initialised_from: aligned ? "2026-10-27" : "2026-10-22", valid_dates: ["2026-10-28", "2026-11-03"] }, species_records: { latest_record: "2026-09-01", window_days: 730 }, aligned,
    message: aligned ? "Every product of this report is for 2026-10-27." : "Not every product describes 2026-10-27: the forecast was issued from 2026-10-22." });

  it("lists every date and says when products lag", async () => {
    show(report({ data_dates: dd(false) } as never));
    expect(await screen.findByText(/Not every product describes 2026-10-27/)).toBeInTheDocument();
    expect(screen.getByText("Forecast initialised from")).toBeInTheDocument();
    expect(screen.getByText("dates differ")).toBeInTheDocument();
    expect(screen.getByText("Newest species record")).toBeInTheDocument();
  });

  it("shows cautious implications labelled by evidence kind", async () => {
    show(report({ data_dates: dd(true), implications: { available: true, kinds: {}, caveat: "These are possible implications, not observed damage.",
      items: [{ kind: "ecological_implication", label: "Ecological implication", text: "Sustained warm water may stress heat-sensitive species." }] } } as never));
    expect(await screen.findByText(/may stress heat-sensitive species/)).toBeInTheDocument();
    expect(screen.getByText(/not observed damage/)).toBeInTheDocument();
  });

  it("DataDatesNote summarises the dates of the dataset", async () => {
    env.getDataDates.mockResolvedValue({ ...dd(true), dataset: "pacific", freshness: { status: "current", message: "Current.", observation_date: "2026-10-27" } });
    render(<MemoryRouter><ActiveSelectionProvider><DataDatesNote /></ActiveSelectionProvider></MemoryRouter>);
    await waitFor(() => expect(screen.queryByTestId("data-dates")).not.toBeNull());
    expect(screen.getByTestId("data-dates")).toHaveTextContent(/Observations through 2026-10-27 · Forecast: 2026-10-28 → 2026-11-03/);
  });
});

describe("data status", () => {
  const refresh = (over: Record<string, unknown> = {}) => ({ attempted_at: "2026-10-29T06:00:12+00:00", outcome: "updated", message: "m", latest_observation: "2026-10-27", expected_latest: "2026-10-28", forecast_dates: null, consistent: true,
    problems: [], source_latest: "2026-10-27", processed_latest: "2026-10-27", last_success_at: "2026-10-29T06:00:12+00:00", last_update_at: "2026-10-29T06:00:12+00:00", ...over });
  const dd = (aligned: boolean) => ({ sst_observation: { date: "2026-10-27", latest_available: "2026-10-27", note: "n" }, anomaly: { date: "2026-10-27", baseline: ["2012-01-01", "2023-12-31"] as [string, string] }, marine_heatwave: { date: "2026-10-27" },
    forecast: { initialised_from: "2026-10-27", valid_dates: ["2026-10-28", "2026-11-03"] }, species_records: { latest_record: "2026-09-01", window_days: 730 }, aligned, message: "Every product of this report is for 2026-10-27." });
  const show2 = async (freshness: Record<string, unknown>) => {
    env.getDataDates.mockResolvedValue({ ...dd(true), dataset: "pacific", freshness: { message: "msg", observation_date: "2026-10-27", ...freshness } });
    render(<MemoryRouter><ActiveSelectionProvider><DataDatesNote /></ActiveSelectionProvider></MemoryRouter>);
    return screen.findByTestId("data-dates");
  };

  it("keeps the source observation, the processed observation, the last successful refresh and the forecast dates apart", async () => {
    const box = await show2({ status: "current", refresh: refresh() });
    expect(within(box).getByTestId("dd-source")).toHaveTextContent("2026-10-27");
    expect(within(box).getByTestId("dd-processed")).toHaveTextContent("2026-10-27");
    expect(within(box).getByTestId("dd-success")).toHaveTextContent("2026-10-29 06:00 UTC");
    expect(within(box).getByTestId("dd-state")).toHaveTextContent("current");
    expect(box).toHaveTextContent("Forecast initialised from");
    expect(box).toHaveTextContent("Forecast valid dates");
  });

  it("says when the data are delayed and the source has nothing newer", async () => {
    const box = await show2({ status: "delayed", refresh: refresh({ outcome: "unchanged", source_latest: "2026-10-27" }) });
    expect(box).toHaveAttribute("open");
    expect(within(box).getByTestId("dd-state")).toHaveTextContent("delayed");
    expect(box).toHaveTextContent(/· delayed/);
  });

  it("says when the last refresh failed, keeps the last success time and never shows the data as current", async () => {
    const box = await show2({ status: "refresh failed", refresh: refresh({ outcome: "source_unavailable", source_latest: null, last_success_at: "2026-10-28T06:00:00+00:00" }) });
    expect(within(box).getByTestId("dd-state")).toHaveTextContent("refresh failed (last attempt failed)");
    expect(within(box).getByTestId("dd-source")).toHaveTextContent("not confirmed by the last check");
    expect(within(box).getByTestId("dd-success")).toHaveTextContent("2026-10-28 06:00 UTC");
    expect(box.textContent).not.toMatch(/live/i);
  });

  it("shows the data state as a worded badge with its own symbol, never as colour alone, and only when not current", async () => {
    const box = await show2({ status: "delayed", refresh: refresh({ outcome: "unchanged" }) });
    const badge = within(box).getByTestId("dd-badge");
    expect(badge).toHaveTextContent("delayed");
    expect(badge.className).toMatch(/before:content-\['◐_'\]/);
    expect(within(box).getByRole("heading", { name: "Observations" })).toBeInTheDocument();
    expect(within(box).getByRole("heading", { name: "Forecast and records" })).toBeInTheDocument();
  });

  it("shows no state badge in the summary when the data are current", async () => {
    const box = await show2({ status: "current", refresh: refresh() });
    expect(within(box).queryByTestId("dd-badge")).not.toBeInTheDocument();
    expect(within(box).getByTestId("dd-state")).toHaveTextContent("current");
  });

  it("separates the last source check from the last dataset update, and says when the source was asked", async () => {
    const box = await show2({ status: "delayed", refresh: refresh({ outcome: "unchanged", source_latest: "2026-10-27", source_checked_at: "2026-10-29T10:50:08+00:00", last_success_at: "2026-10-29T10:50:08+00:00", last_update_at: "2026-10-29T06:51:18+00:00" }) });
    expect(box).toHaveTextContent("Last successful source check");
    expect(within(box).getByTestId("dd-success")).toHaveTextContent("2026-10-29 10:50 UTC");
    expect(within(box).getByTestId("dd-update")).toHaveTextContent("2026-10-29 06:51 UTC");
    expect(within(box).getByTestId("dd-source")).toHaveTextContent(/2026-10-27.*checked 2026-10-29 10:50 UTC/);
    expect(box).toHaveTextContent("Latest source observation (at the last check)");
  });

  it("shows a refresh that is running or was interrupted, never as a success", async () => {
    let box = await show2({ status: "delayed", refresh: refresh({ outcome: "running" }) });
    expect(within(box).getByTestId("dd-state")).toHaveTextContent("delayed (refresh running)");
    cleanup();
    box = await show2({ status: "refresh failed", refresh: refresh({ outcome: "interrupted" }) });
    expect(within(box).getByTestId("dd-state")).toHaveTextContent("refresh failed (last attempt interrupted)");
  });

  it("does not invent a refresh time when no refresh has run", async () => {
    const box = await show2({ status: "current", refresh: null });
    expect(within(box).getByTestId("dd-success")).toHaveTextContent("not yet");
  });
});

describe("🤖 Explainable AI — Why this forecast?", () => {
  it("loads only when opened and shows the actual inputs, seven predictions and the sensitivity caveat", async () => {
    const user = userEvent.setup();
    show(report());
    await goTab("Forecast");
    const summary = await screen.findByText("🤖 Explainable AI — Why this forecast?");
    expect(env.getForecastExplanation).not.toHaveBeenCalled();
    await user.click(summary);
    expect(await screen.findByTestId("xai-model-inputs")).toBeInTheDocument();
    expect(env.getForecastExplanation).toHaveBeenCalledWith("pacific", expect.any(Number), expect.any(Number));
    expect(within(screen.getByTestId("xai-predict-table")).getAllByRole("row")).toHaveLength(8);
    expect(screen.getAllByText(/Model sensitivity: not causal attribution/).length).toBeGreaterThan(0);
    expect(screen.getAllByText(/Model-based sensitivity explanation: not causal attribution/).length).toBeGreaterThan(0);
  });

  it("compares the ConvLSTM with persistence and says where persistence is as good", async () => {
    const user = userEvent.setup();
    const m = model();
    m.evaluation = { split: "test", date_range: ["2024-01-01", "2025-12-31"], n_windows: 700, horizons: [1, 2, 3, 4, 5, 6, 7], mean_mae: { convlstm: 0.2, persistence: 0.2, climatology: 0.5 }, mae: {},
      mae_skill_vs_persistence: [0.2, 0.1, 0.05, 0.0, -0.02, -0.05, -0.1], beats_persistence: false };
    env.getForecastExplanation.mockResolvedValue(explanation({ model: m }));
    show(report());
    await goTab("Forecast");
    await user.click(await screen.findByText("🤖 Explainable AI — Why this forecast?"));
    const sec = await screen.findByRole("region", { name: "ConvLSTM versus persistence" });
    expect(within(sec).getByText("Persistence °C")).toBeInTheDocument();
    expect(within(sec).getAllByRole("row")).toHaveLength(8);
    expect(sec).toHaveTextContent(/lower error than persistence at \+1, \+2, \+3/);
    expect(sec).toHaveTextContent(/did not improve on persistence at \+4, \+5, \+6, \+7/);
    expect(sec).toHaveTextContent(/Persistence assumes no change at all/);
  });

  it("does not claim any improvement when the skill is negative at every horizon", async () => {
    const user = userEvent.setup();
    const m = model();
    m.evaluation = { split: "test", date_range: ["2024-01-01", "2025-12-31"], n_windows: 700, horizons: [1, 2, 3, 4, 5, 6, 7], mean_mae: { convlstm: 0.3, persistence: 0.2, climatology: 0.5 }, mae: {},
      mae_skill_vs_persistence: [-0.05, -0.09, -0.1, -0.1, -0.11, -0.12, -0.12], beats_persistence: false };
    env.getForecastExplanation.mockResolvedValue(explanation({ model: m }));
    show(report());
    await goTab("Forecast");
    await user.click(await screen.findByText("🤖 Explainable AI — Why this forecast?"));
    const sec = await screen.findByRole("region", { name: "ConvLSTM versus persistence" });
    expect(sec).toHaveTextContent(/did not have a lower error than persistence at any horizon, so persistence was as good or better throughout/);
    expect(sec).not.toHaveTextContent(/improve on persistence at \+1/);
  });

  it("says plainly when the forecast cannot be explained", async () => {
    const user = userEvent.setup();
    env.getForecastExplanation.mockResolvedValue({ available: false, dataset: "pacific", message: "The forecast was issued from 2026-10-22 but the newest observation is 2026-10-27." });
    show(report());
    await goTab("Forecast");
    await user.click(await screen.findByText("🤖 Explainable AI — Why this forecast?"));
    expect(await screen.findByText(/issued from 2026-10-22 but the newest observation/)).toBeInTheDocument();
  });
});


describe("report structure and explanations from backend values", () => {
  const fc = (over: Record<string, unknown> = {}) => ({ available: true, issued_from: "2026-10-27", dates: ["2026-10-28", "2026-10-29", "2026-10-30"], forecast_sst: [28.6, 28.8, 28.9], forecast_anomaly: [1.5, 1.8, 2.0], persistence_sst: [28.4, 28.4, 28.4],
    typical_error_c: [0.1, 0.18, 0.24], direction: "warming", summary: "s", model: "ConvLSTM", trained_on: "northeast Pacific", beats_persistence: false, direction_by_day: ["warming", "warming", "warming"],
    reading: { label: "warming", anomaly_label: "strengthening", sst_change_c: 0.5, peak_day: 3, peak_anomaly_c: 2.0, max_abs_anomaly_c: 2.0, mean_anomaly_c: 1.77, anomaly_now_c: 1.3, anomaly_end_c: 2.0, days: 3,
      text: "The model predicts continued warming. The warm anomaly strengthens: +1.3 °C now to +2.0 °C at day +3." }, ...over });

  it("follows the flow conditions, anomaly, heatwave, biodiversity, context, forecast, model explanation, exposure, implications, risk, alerts, data", async () => {
    show(report({ forecast: fc() as never, risk: risk([driver("anomaly", "Anomaly")]) as never, implications: { available: true, kinds: {}, items: [], caveat: "c" } } as never));
    await screen.findByTestId("forecast-reading");
    const titles = screen.getAllByRole("heading", { level: 3, hidden: true }).map((h) => h.textContent);
    const order = ["How unusual is this?", "Marine heatwave analysis", "Sea surface temperature: last week and the next seven days", "Explainable AI: why this forecast", "Biodiversity & ecosystem context", "Ecological and physical context",
      "Potential exposure", "Potential environmental implications", "Risk assessment", "Why this risk level", "Alerts", "Data & methodology"];
    expect(screen.getAllByRole("tab").map((t) => t.textContent)).toEqual(expect.arrayContaining([expect.stringMatching(/^Overview/), expect.stringMatching(/^Marine heatwave/), expect.stringMatching(/^Forecast/), expect.stringMatching(/^Risk/), expect.stringMatching(/^Alerts/)]));
    const idx = order.map((t) => titles.indexOf(t));
    expect(idx.every((v) => v >= 0)).toBe(true);
    expect([...idx].sort((x, y) => x - y)).toEqual(idx);
  });

  it("shows all forecast days with predicted SST, anomaly and direction, and the reading", async () => {
    show(report({ forecast: fc() as never }));
    expect(await screen.findByTestId("forecast-reading")).toHaveTextContent(/continued warming.*strengthens/);
    await goTab("Forecast");
    const table = screen.getByRole("table", { name: "Forecast at this location" });
    expect(within(table).getAllByRole("row")).toHaveLength(4);
    expect(within(table).getByText("Direction")).toBeInTheDocument();
    expect(within(table).getAllByText("warming")).toHaveLength(3);
  });

  it("shows why the forecast is warmer, from the backend's own bullets", async () => {
    show(report({ forecast: fc() as never, analysis: { recent_anomaly: [], why_forecast: { direction: "warming", headline: "Why is the forecast warmer?", bullets: [
      { kind: "observed", label: "Observed measurement", text: "Recent trend: the anomaly here went from +0.8 °C on 2026-10-21 to +1.3 °C on 2026-10-27 (rising)." },
      { kind: "physical_cause", label: "Not established", text: "Why the ocean itself is changing cannot be established." }] } } } as never));
    const w = await screen.findByTestId("why-forecast");
    expect(w).toHaveTextContent("Why is the forecast warmer?");
    expect(w).toHaveTextContent(/Recent trend: the anomaly here went from \+0\.8/);
    expect(w).not.toHaveTextContent(/cannot be established|not established/i);          // the "not established" statement is not shown in the interface
  });

  it("explains an active marine heatwave and a missing one without calling it missing data", async () => {
    show(report({ heatwave: { available: true, inside: false, message: "No active marine heatwave at this location.", analysis: { active: false, lines: ["No active marine heatwave is detected at this location."], trend: null, continuation: null } } as never }));
    expect(await screen.findByTestId("heatwave-analysis")).toHaveTextContent("No active marine heatwave is detected at this location.");
    expect(screen.queryByText(/insufficient|missing/i, { selector: "[data-testid=heatwave-analysis] *" })).not.toBeInTheDocument();
  });

  it("shows the classification, normalisation and detail lines of a driver", async () => {
    show(report({ risk: risk([driver("anomaly", "SST anomaly", { classification: "High", normalization: "factor = min(|anomaly| / 3 °C, 1)", detail_lines: ["Observed anomaly +2.4 °C. Classified High."] })]) as never }));
    expect(await screen.findByTestId("classification")).toHaveTextContent("High");
    expect(screen.getByText(/Normalisation: factor = min\(\|anomaly\| \/ 3 °C, 1\)/)).toBeInTheDocument();
    expect(screen.getByText("Observed anomaly +2.4 °C. Classified High.")).toBeInTheDocument();
  });

  it("states why the level is what it is from the contributions", async () => {
    show(report({ risk: risk([driver("anomaly", "SST anomaly", { contribution: 0.2 }), driver("forecast", "Forecast conditions", { raw: 1.5, contribution: 0.1 })]) as never }));
    expect(await screen.findByTestId("risk-why")).toHaveTextContent(/MODERATE \(0\.41\): SST anomaly .* adds 0\.20; Forecast conditions .* adds 0\.10/);
  });

  it("the forecast explanation is labelled as model sensitivity, not causation, and shows the actual inputs", async () => {
    const user = userEvent.setup();
    show(report({ forecast: fc() as never }));
    await screen.findByTestId("forecast-reading");
    expect(screen.queryByText(/NOT ESTABLISHED/i)).not.toBeInTheDocument();
    await user.click(screen.getByText("🤖 Explainable AI — Why this forecast?"));
    expect(await screen.findByText(/Model-based sensitivity explanation: not causal attribution/)).toBeInTheDocument();                // kept in the explanation's own limits section
    expect(await screen.findByTestId("xai-inputs")).toHaveTextContent(/Channels supplied to the model on every input day: sea surface temperature.*SST gradient.*ocean\/land mask/);
  });

  it("labels regional biodiversity records as regional and shows the range used", async () => {
    show(report({ species: { ...SPECIES, counted: { observations: 1984, distinct_species: 14, listed: 12, radius_deg: 10, window_days: 730, latest_record: "2026-06-24", earliest_record: "2024-11-02", scope: "regional", historical: false,
      label: "Regional records within about 10° of this location (last 2 years): 1,984 observations; distinct species: 14; the 12 nearest are listed." } } as never }));
    expect(await screen.findByTestId("species-counted")).toHaveTextContent(/^Regional records within about 10°/);
    expect(screen.getByText(/14 species · 1,984 observations/)).toBeInTheDocument();
  });
});


describe("OBIS biodiversity, exposure, context and sources", () => {
  const obis = (over: Record<string, unknown> = {}) => ({
    available: true, status: "cached", scope: "regional", scope_label: "Regional occurrence", half_width_deg: 10, historical: false, window: { start: "2024-10-28", end: "2026-10-28" },
    label: "Regional records within about 10° of this location (last 2 years): 300 observations of 161 species.", caveats: ["An occurrence record shows where and when an animal was recorded, not its range."],
    trail: [{ half_width_deg: 0.5, scope: "local", records: 0, window: "last 2 years" }, { half_width_deg: 10, scope: "regional", records: 300, window: "last 2 years" }],
    counts: { observations: 300, observations_all_time: 137844, distinct_species: 161, threatened_species: 6, taxa: 164, sampled_records: 300, density_per_1000_km2: 0.61 },
    groups: [{ group: "Teleostei", species: 90, records: 200 }], threatened: [{ scientific_name: "Sphyrna lewini", common_name: "Scalloped hammerhead", group: "Elasmobranchii", conservation_status: "CR", threatened: true, records: 6, nearest_km: 1468,
      latest_record: "2025-06-05", recency: "Recent observation", scope_label: "Regional occurrence", records_in_heatwave: 3, records_in_forecast_area: 0, sampled_records: 6, datasets: [] }],
    items: [{ scientific_name: "Chaetodon trichrous", common_name: null, group: "Teleostei", conservation_status: "Not assessed", threatened: false, records: 5, nearest_km: 90, latest_record: "2019-01-01", recency: "Historical observation",
      scope_label: "Regional occurrence", records_in_heatwave: null, records_in_forecast_area: null, sampled_records: 5, datasets: [] }],
    exposure: { records_in_domain: 300, heatwave: { available: true, records: 90, species: 12, threatened_species: 3, share_pct: 30 }, forecast: { available: true, records: 60, species: 8, threatened_species: 2, share_pct: 20, threshold_c: 1 } },
    exposure_text: "12 recorded species lie inside the current marine-heatwave footprint, including 3 listed as threatened. These records indicate potential exposure to the observed or predicted thermal conditions; they are not evidence of biological damage.",
    provenance: {}, ...over });
  const fcast = () => ({ available: true, issued_from: "2026-10-27", dates: ["2026-10-28", "2026-10-29", "2026-10-30"], forecast_sst: [28.6, 28.8, 28.9], forecast_anomaly: [1.5, 1.8, 2.0], persistence_sst: [28.4, 28.4, 28.4],
    typical_error_c: [0.1, 0.18, 0.24], direction: "warming", summary: "s", model: "ConvLSTM", trained_on: "northeast Pacific", beats_persistence: false, direction_by_day: ["warming", "warming", "warming"] });

  it("labels the scope and shows counts, threatened species with status, distance and recency", async () => {
    show(report({ obis: obis() as never }));
    expect(await screen.findByTestId("obis-scope")).toHaveTextContent("Regional occurrence");
    expect(screen.getByTestId("species-counted")).toHaveTextContent(/^Regional records within about 10°/);
    const row = screen.getByText("Scalloped hammerhead").closest("li") as HTMLElement;
    expect(within(row).getByText("CR")).toBeInTheDocument();
    expect(row).toHaveTextContent(/6 records, nearest 1,468 km away, latest 2025-06-05/);
    expect(within(row).getByText("Recent observation")).toBeInTheDocument();
    expect(row).toHaveTextContent(/3 sampled record\(s\) inside the current marine-heatwave footprint/);
    expect(screen.getByText("Distinct species")).toBeInTheDocument();
    expect(screen.getByText("161")).toBeInTheDocument();
  });

  it("explains how the search area was chosen and keeps the stored records the score uses", async () => {
    show(report({ obis: obis() as never }));
    const trail = await screen.findByTestId("obis-trail");
    expect(trail).toHaveTextContent(/±0\.5° \(local, last 2 years\): 0 records/);
    expect(trail).toHaveTextContent(/±10° \(regional, last 2 years\): 300 records ← used/);
    expect(screen.getByTestId("stored-records")).toHaveTextContent("Stored project records (the selection the risk score uses)");
  });

  it("shows biodiversity exposure and potential forecast exposure as potential, never as damage", async () => {
    show(report({ obis: obis() as never }));
    const p = await screen.findByTestId("exposure-panel");
    expect(p).toHaveTextContent("Biodiversity exposure: current marine heatwave");
    expect(p).toHaveTextContent("Potential forecast exposure");
    expect(screen.getByTestId("exposure-text")).toHaveTextContent(/potential exposure.*not evidence of biological damage/);
  });

  it("falls back to the stored records, with a quiet note while OBIS is being fetched", async () => {
    show(report({ obis: { available: false, status: "refreshing", message: "Fetching" } as never }));
    expect(await screen.findByText(/Retrieving the latest OBIS records for this area/)).toBeInTheDocument();
    expect(screen.queryByTestId("obis-panel")).not.toBeInTheDocument();
    expect(screen.getByTestId("exposure-fallback")).toBeInTheDocument();
  });

  it("shows chlorophyll-a and currents as context with their sources, and says they are not model inputs", async () => {
    show(report({ context: { status: "cached", chlorophyll: { available: true, text: "Latest valid chlorophyll-a is 0.041 mg m⁻³ (2026-10-17).", source: "NOAA CoastWatch / STAR", dataset: "noaa_snpp_chla_daily", unit: "mg m^-3", spatial_resolution: "0.0375°",
      temporal_resolution: "daily", dataset_end: "2026-10-17", latest: { value: 0.041, date: "2026-10-17" } }, currents: { available: true, text: "The geostrophic surface current is 0.93 m/s toward the east.", caveat: "Geostrophic currents come from sea-surface height.",
      source: "NOAA CoastWatch (NESDIS/STAR)", dataset: "noaacwBLENDEDNRTcurrentsDaily", unit: "m/s", spatial_resolution: "0.25°", temporal_resolution: "daily", dataset_end: "2026-10-26", latest: { date: "2026-10-26", speed: 0.93, direction_deg: 87, u: 0.9, v: 0 } } } as never }));
    expect(await screen.findByTestId("chl-text")).toHaveTextContent("Latest valid chlorophyll-a is 0.041");
    expect(screen.getByTestId("current-text")).toHaveTextContent("toward the east");
    expect(screen.getByTestId("context-panel")).toHaveTextContent(/not inputs of the ConvLSTM.*not part of the risk score.*do not explain the forecast/);
  });

  it("says context is being retrieved instead of showing nothing", async () => {
    show(report({ context: { status: "refreshing", chlorophyll: null, currents: null } as never }));
    expect(await screen.findByText(/Retrieving NOAA chlorophyll-a and surface-current data/)).toBeInTheDocument();
  });

  it("lists every source with observation date, resolution and retrieval date", async () => {
    show(report({ sources: [{ topic: "Sea surface temperature and anomaly", source: "NOAA OISST v2.1", dataset: "NOAA OISST", observation_date: "2026-10-27", spatial_resolution: "0.25°", temporal_resolution: "daily", retrieved: "2026-10-28" },
      { topic: "Biodiversity", source: "Ocean Biodiversity Information System (OBIS)", dataset: "OBIS occurrence and checklist API v3", observation_date: "2024-10-28 to 2026-10-28", spatial_resolution: "point records", temporal_resolution: "individual dates", retrieved: "2026-10-27" }] as never }));
    const t = await screen.findByTestId("sources");
    expect(t).toHaveTextContent("NOAA OISST v2.1");
    expect(t).toHaveTextContent("Ocean Biodiversity Information System (OBIS)");
    expect(t).toHaveTextContent("2026-10-28");
    expect(t).not.toHaveTextContent(/copernicus/i);
  });

  it("asks again quietly when the report says data are being fetched, without replacing the report", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    try {
      show(report({ refresh_hint_s: 1, obis: { available: false, status: "refreshing" } as never }));
      await screen.findByText(/Retrieving the latest OBIS records/);
      env.getReport.mockClear();
      env.getReport.mockResolvedValue(report({ obis: obis() as never }));
      await vi.advanceTimersByTimeAsync(1500);
      expect(env.getReport).toHaveBeenCalledTimes(1);
      expect(await screen.findByTestId("obis-panel")).toBeInTheDocument();
      expect(screen.queryByText(/Loading the report for this location/)).not.toBeInTheDocument();
    } finally {
      vi.useRealTimers();
    }
  });

  it("shows the risk-dominance sentence and the heatwave forecast classification from the backend", async () => {
    show(report({ analysis: { recent_anomaly: [], why_forecast: null, risk_dominance: "The score of 0.76 is driven mostly by the SST anomaly (0.30 of 0.76) and the heatwave duration (0.25 of 0.76)." } as never,
      risk: risk([driver("anomaly", "SST anomaly")]) as never, heatwave: { available: true, inside: true, message: "Marine heatwave: YES.", analysis: { active: true, status: "Persisting", lines: ["Current status: a marine heatwave is active."], trend: "persisting", continuation: "persistence" } } as never }));
    expect(await screen.findByTestId("risk-dominance")).toHaveTextContent(/driven mostly by the SST anomaly \(0\.30 of 0\.76\)/);
    expect(screen.getByTestId("heatwave-status")).toHaveTextContent("Persisting");
  });

  it("shows each explanation panel once", async () => {
    show(report({ risk: risk([driver("anomaly", "SST anomaly")]) as never }));
    await screen.findByTestId("risk-why");
    expect(screen.getAllByText("Explain this risk in plain language")).toHaveLength(1);
    expect(screen.getAllByTestId("score-sum")).toHaveLength(1);
  });

  it("shows the recent trends and the change from the latest observation for each forecast day", async () => {
    show(report({ forecast: { ...fcast(), change_vs_latest_c: [0.2, 0.4, 0.5] } as never, analysis: { recent_anomaly: [], why_forecast: null, trends: { days: 7, sst_3d_c_per_day: 0.05, sst_7d_c_per_day: 0.03, anomaly_3d_change_c: 0.2, anomaly_7d_change_c: 0.5, from: "2026-10-21", to: "2026-10-27" } } as never }));
    expect(await screen.findByTestId("recent-trends")).toHaveTextContent(/SST \+0\.05 °C\/day over 3 days and \+0\.03 °C\/day over 7 days/);
    await goTab("Forecast");
    const table = screen.getByRole("table", { name: "Forecast at this location" });
    expect(within(table).getByText("Change from latest °C")).toBeInTheDocument();
    expect(within(table).getByText("+0.50")).toBeInTheDocument();
  });

  it("the explanation shows the numeric interpretation and the observed, perturbed and difference table", async () => {
    const user = userEvent.setup();
    env.getForecastExplanation.mockResolvedValue(explanation({
      interpretation: { direction: "warming", anomaly_trajectory: "persistent", start_anomaly_c: 1.3, end_anomaly_c: 1.8, total_change_c: 0.5, sst_change_c: 0.4, text: "The model predicts warming. The forecast anomaly increases from +1.3 °C to +1.8 °C (total change +0.5 °C). This is a model interpretation, not proof of physical causation." },
      counterfactual: { horizon: 7, title: "Model sensitivity: not causal attribution", date: "2026-11-03", reading: "Removing the observed warm anomaly of the newest input day from the input sequence would reduce the day +7 predicted anomaly by 0.42 °C. The model prediction is sensitive to the recent anomaly pattern.",
        rows: [{ label: "Model output with the observed input", sst_c: 28.9, anomaly_c: 1.8, difference_c: 0, note: "" }, { label: "Anomaly of 2026-10-27 removed (replaced by normal conditions)", sst_c: 28.48, anomaly_c: 1.38, difference_c: -0.42, note: "" }] },
      current: { ...explanation().current!, trend_3d_c_per_day: 0.04, anomaly_change_3d_c: 0.1, anomaly_change_7d_c: 0.4 } }));
    show(report({ forecast: fcast() as never }));
    await user.click(await screen.findByText("🤖 Explainable AI — Why this forecast?"));
    expect(await screen.findByTestId("xai-interpretation")).toHaveTextContent(/increases from \+1\.3 °C to \+1\.8 °C.*not proof of physical causation/);
    const table = screen.getByTestId("xai-counterfactual");
    expect(within(table).getByText("-0.42")).toBeInTheDocument();
    expect(screen.getByTestId("xai-counterfactual-reading")).toHaveTextContent(/reduce the day \+7 predicted anomaly by 0\.42 °C.*sensitive to the recent anomaly pattern/);
    expect(screen.getByTestId("xai-trends")).toHaveTextContent(/3-day trend \+0\.040 °C\/day/);
  });
});


describe("Explainable AI panel", () => {
  const fcast = (over: Record<string, unknown> = {}) => ({ available: true, issued_from: "2026-10-27", dates: ["2026-10-28", "2026-10-29", "2026-10-30"], forecast_sst: [28.6, 28.8, 28.9], forecast_anomaly: [1.5, 1.8, 2.0],
    persistence_sst: [28.4, 28.4, 28.4], typical_error_c: [0.1, 0.18, 0.24], direction: "warming", summary: "s", model: "ConvLSTM", trained_on: "northeast Pacific", beats_persistence: false,
    direction_by_day: ["warming", "warming", "warming"], ...over,
    reading: { label: "warming", anomaly_label: "strengthening", sst_change_c: 0.5, peak_day: 3, peak_anomaly_c: 2.0, max_abs_anomaly_c: 2.0, mean_anomaly_c: 1.77, anomaly_now_c: 1.3, anomaly_end_c: 2.0, days: 3, text: "reading text", ...((over.reading as object) ?? {}) } });
  const open = async (rep: LocationReportData) => {
    const user = userEvent.setup();
    const view = show(rep);
    await goTab("Forecast");
    await user.click(await screen.findByText("🤖 Explainable AI — Why this forecast?"));
    return view;
  };
  const interp = (direction: string, traj: string, start: number, end: number, plain: string) => ({ direction, anomaly_trajectory: traj, start_anomaly_c: start, end_anomaly_c: end, total_change_c: end - start, sst_change_c: end - start,
    forecast_outlook: direction, anomaly_outlook: traj, text: `The model predicts ${direction}. ${traj}`, plain });

  it("renders the model line, inputs and predictions as soon as it is opened, before the sensitivity run has finished", async () => {
    let release: (v: ForecastExplanation) => void = () => undefined;
    env.getForecastExplanation.mockReturnValue(new Promise<ForecastExplanation>((res) => { release = res; }));
    await open(report({ forecast: fcast() as never }));
    expect(screen.getByTestId("xai-model-line")).toHaveTextContent("Model: ConvLSTM · Forecast input: previous 7 daily ocean fields · Forecast horizon: next 7 days");
    const t = screen.getByTestId("xai-predict-table");
    expect(within(t).getAllByRole("row")).toHaveLength(4);
    expect(t).toHaveTextContent("Day 1 · 2026-10-28");
    expect(t).toHaveTextContent("28.60");
    expect(screen.getByTestId("xai-outlooks")).toHaveTextContent(/Forecast outlook: warming.*Anomaly outlook: strengthening/);
    expect(screen.getAllByRole("status").some((e) => /already final/.test(e.textContent ?? ""))).toBe(true);
    release(explanation());
    expect(await screen.findByTestId("xai-model-inputs")).toBeInTheDocument();
  });

  it("shows the actual model inputs: dates, latest values, trends, grid and channels", async () => {
    await open(report({ forecast: fcast() as never }));
    const inp = await screen.findByTestId("xai-model-inputs");
    expect(inp).toHaveTextContent("2026-10-21 to 2026-10-27 (7 days)");
    expect(inp).toHaveTextContent("28.40 °C (2026-10-27)");
    expect(inp).toHaveTextContent(/\+0\.050 °C\/day over 7 days; \+0\.080 °C\/day over 3 days/);
    expect(inp).toHaveTextContent(/\+0\.40 °C over 7 days; \+0\.20 °C over 3 days/);
    expect(inp).toHaveTextContent("125 × 190 cells, 1° resolution");
    expect(screen.getByTestId("xai-inputs")).toHaveTextContent(/SST gradient.*day of year.*ocean\/land mask/);
  });

  it("the predictions table shows the real forecast with a direction per day, and the dates follow the latest observation", async () => {
    await open(report({ forecast: fcast() as never }));
    const t = await screen.findByTestId("xai-predict-table");
    const rows = within(t).getAllByRole("row").slice(1);
    expect(rows).toHaveLength(7);
    expect(rows[0]).toHaveTextContent(/Day 1 · 2026-10-28.*28\.50.*\+1\.30.*Warming/);
    expect(rows[6]).toHaveTextContent("Day 7");
    expect(screen.getByTestId("xai-model-inputs")).toHaveTextContent("2026-10-27");           // observations through 10-27: the first forecast day is 10-28
    expect(rows[0].textContent).toContain("2026-10-28");
  });

  it.each([
    ["warming", "warmer", "SST was rising by 0.30 °C over the 7 input days and the forecast continues in the same direction, indicating warmer conditions"],
    ["cooling", "cooler", "SST was falling by 0.40 °C over the 7 input days and the forecast continues in the same direction, indicating cooler conditions"],
    ["stable", "stable", "The predicted SST and anomaly change only slightly over the forecast period"],
  ])("the warmer/cooler explanation for a %s forecast is the backend's own text", async (direction, word, plain) => {
    env.getForecastExplanation.mockResolvedValue(explanation({ interpretation: interp(direction, "persistent", 1.3, 1.3, plain) as never }));
    await open(report({ forecast: fcast() as never }));
    const why = await screen.findByTestId("xai-why");
    expect(why).toHaveTextContent(`Why is it ${word}?`);
    expect(screen.getByTestId("xai-plain")).toHaveTextContent(plain);
  });

  it.each([["strengthening", 1.3, 1.9], ["weakening", 2.6, 1.8], ["changing sign", 1.5, -0.8], ["near normal", 0.2, 0.1]])("shows the anomaly outlook '%s' from the explanation", async (traj, a, b) => {
    env.getForecastExplanation.mockResolvedValue(explanation({ interpretation: interp("cooling", traj, a, b, "plain") as never }));
    await open(report({ forecast: fcast({ reading: { label: "cooling", anomaly_label: traj } }) as never }));
    await screen.findByTestId("xai-why");
    expect(screen.getByTestId("xai-outlooks")).toHaveTextContent(`Anomaly outlook: ${traj}`);
    expect(screen.getByTestId("xai-outlooks")).toHaveTextContent("Forecast outlook: cooling");
  });

  it("separates model evidence from the physical interpretation and does not present sensitivity as an oceanographic cause", async () => {
    await open(report({ forecast: fcast() as never }));
    expect(await screen.findByTestId("xai-evidence")).toHaveTextContent(/continued warming.*sensitive to it/);
    expect(screen.getByTestId("xai-physical")).toHaveTextContent(/interpreted separately in section B.*sensitivity does not show an oceanographic cause/i);
    expect(screen.getByTestId("xai-physical")).not.toHaveTextContent(/inconclusive|not assessable|evidence quality/i);
  });

  it("does not render the 'not established' physical-cause statement in the forecast explanation, and keeps the model explanation", async () => {
    await open(report({ forecast: fcast() as never }));
    await screen.findByTestId("xai-evidence");
    const more = screen.getByTestId("xai-more");
    expect(more).toHaveTextContent("Which input day matters: the newest.");
    expect(more).not.toHaveTextContent(/Not modelled: currents and winds/);
    expect(more.textContent).not.toMatch(/physical cause cannot be inferred|not established/i);
    expect(screen.getByTestId("xai-counterfactual")).toBeInTheDocument();
    expect(screen.getByTestId("xai-physical")).toHaveTextContent(/interpreted separately in section B/);
  });

  it("ranks the measured sensitivity signals with their values and directions, and does not add importance values of its own", async () => {
    await open(report({ forecast: fcast() as never }));
    await screen.findByTestId("xai-signals");
    const items = screen.getAllByTestId("xai-signal");
    expect(items).toHaveLength(3);
    expect(items[0]).toHaveTextContent(/1\..*newest input day.*\+0\.62 °C.*pushes the forecast warmer/);
    expect(items[1]).toHaveTextContent(/±8°.*\+0\.41 °C/);
    expect(items[2]).toHaveTextContent(/-0\.08 °C.*no clear push/);
    expect(screen.getByTestId("xai-signals")).not.toHaveTextContent(/%/);
    const resp = screen.getByTestId("xai-respond");
    expect(within(resp).getByTestId("xai-counterfactual")).toHaveTextContent(/None: the observed input.*Anomaly of 2026-10-27 removed.*-0\.62.*lower/);
    expect(screen.getByTestId("xai-counterfactual-reading")).toHaveTextContent(/reduce the day \+7 predicted anomaly by 0\.62 °C/);
  });

  it("omits the signal ranking when the backend measured none", async () => {
    env.getForecastExplanation.mockResolvedValue(explanation({ signals: [] }));
    await open(report({ forecast: fcast() as never }));
    await screen.findByTestId("xai-respond");
    expect(screen.queryByTestId("xai-signals")).not.toBeInTheDocument();
  });

  it("draws the observed and forecast anomaly in one small chart", async () => {
    await open(report({ forecast: fcast() as never }));
    const svg = await screen.findByTestId("xai-spark");
    expect(svg).toHaveAttribute("aria-label", expect.stringMatching(/Recent observed anomaly from \+0\.9 to \+1\.3 °C, forecast anomaly to \+1\.3 °C/));
    expect(svg.querySelectorAll("polyline")).toHaveLength(2);
  });

  it("shows how the forecast enters the risk score, from the backend's own factor, weight and contribution", async () => {
    const drv = driver("forecast", "Forecast conditions", { raw: 1.75, value: 0.58, effective_weight: 0.2, contribution: 0.12, saturation_at: 3 });
    await open(report({ forecast: fcast() as never, risk: risk([drv]) as never }));
    const r = await screen.findByTestId("xai-risk");
    expect(r).toHaveTextContent(/mean size of the predicted anomaly.*÷ 3 °C.*the rule is unchanged/);
    expect(r).toHaveTextContent(/1\.75 °C.*factor 0\.58.*weight 0\.20.*contribution 0\.12.*total score 0\.41 \(MODERATE\)/);
  });

  it("states the limits: not causal attribution, and persistence performs as well or better when the evaluation says so", async () => {
    const m = model();
    m.evaluation = { split: "test", date_range: ["2024-01-01", "2025-12-31"], n_windows: 700, horizons: [1, 2, 3, 4, 5, 6, 7], mean_mae: { convlstm: 0.3, persistence: 0.2, climatology: 0.5 }, mae: {},
      mae_skill_vs_persistence: [-0.05, -0.09, -0.1, -0.1, -0.11, -0.12, -0.12], beats_persistence: false };
    env.getForecastExplanation.mockResolvedValue(explanation({ model: m }));
    await open(report({ forecast: fcast() as never }));
    const l = await screen.findByTestId("xai-limits");
    expect(l).toHaveTextContent("Model-based sensitivity explanation: not causal attribution.");
    expect(l).toHaveTextContent("It does not prove that those patterns physically caused the observed or forecast ocean conditions.");
    expect(screen.getByTestId("xai-eval")).toHaveTextContent(/did not beat a persistence forecast at 7 of 7 horizons.*-5%.*persistence is currently as good or better/);
  });

  it("changes with the selected location", async () => {
    const user = userEvent.setup();
    env.getForecastExplanation.mockImplementation(async (_d: string, la: number) => explanation({ interpretation: interp(la > 0 ? "warming" : "cooling", "persistent", 1, 1, la > 0 ? "NORTH plain explanation" : "SOUTH plain explanation") as never }));
    env.getReport.mockImplementation(async (_d: string, la: number, lo: number) => report({ forecast: fcast() as never, query: { lat: la, lon: lo }, cell: { ...report().cell!, lat: la, lon_180: lo } }));
    const view = render(<MemoryRouter><ActiveSelectionProvider><LocationReport point={{ lat: 10, lon: -150 }} dataset="pacific" date={null} /></ActiveSelectionProvider></MemoryRouter>);
    await user.click(await screen.findByText("🤖 Explainable AI — Why this forecast?"));
    expect(await screen.findByTestId("xai-plain")).toHaveTextContent("NORTH plain explanation");
    view.rerender(<MemoryRouter><ActiveSelectionProvider><LocationReport point={{ lat: -30, lon: -120 }} dataset="pacific" date={null} /></ActiveSelectionProvider></MemoryRouter>);
    await user.click(await screen.findByText("🤖 Explainable AI — Why this forecast?"));
    await waitFor(() => expect(screen.getByTestId("xai-plain")).toHaveTextContent("SOUTH plain explanation"));
  });

  it("uses no causal language and invents no physical driver", async () => {
    await open(report({ forecast: fcast() as never }));
    await screen.findByTestId("xai-limits");
    const text = (screen.getByRole("complementary", { name: "Location report" }).textContent ?? "").replace(/not causal attribution/gi, "");
    expect(text).not.toMatch(/\b(?:was|were|is|are) caused by\b|\bbecause of the (?:wind|current|upwelling)|\bdue to (?:ENSO|El Ni|La Ni)|\bcaused the (?:warming|cooling|forecast)/i);
    expect(text).not.toMatch(/copernicus/i);
  });

  it("keeps its tables inside horizontally scrollable wrappers so a phone screen does not overflow", async () => {
    await open(report({ forecast: fcast() as never }));
    await screen.findByTestId("xai-counterfactual");
    for (const id of ["xai-predict-table", "xai-counterfactual"]) expect(screen.getByTestId(id).closest(".overflow-x-auto")).not.toBeNull();
  });
});


describe("B. Physical explanation", () => {
  const src = (id: string, label: string, over: Record<string, unknown> = {}) => ({ id, label, status: "ok", source: "NOAA", dataset: `${id}-dataset`, variable: null, unit: null, kind: "measurement", spatial_resolution: "0.25°", temporal_resolution: "daily",
    dataset_end: "2026-10-27", lag_days_behind_sst: 0, retrieved: "2026-10-28", message: null, caveat: null, ...over });
  const mech = (id: string, name: string, verdict: string, over: Record<string, unknown> = {}) => ({ id, name, kind: "measurement", verdict, favours: "warming", evidence_for: [], evidence_against: [], data: [], caveat: "A caveat.", evidence_quality: "low", ...over });
  const dates = Array.from({ length: 14 }, (_, k) => `2026-10-${14 + k}`);
  const physical = (over: Record<string, unknown> = {}) => ({
    available: true, status: "live", cell: { lat: 0.1, lon: -150 },
    observed: { date: "2026-10-27", sst_c: 30.6, anomaly_c: 3.9, classification: "Extreme", trends: null, text: "On 2026-10-27 sea surface temperature at this place is 30.6 °C, +3.9 °C relative to its 2002-2023 climatological baseline." },
    mechanisms: [
      mech("wind", "Wind-driven mixing and evaporative heat exchange", "consistent", { evidence_for: ["The 7-day mean wind speed was 4.1 m/s, 2.4 m/s below the 2016-2025 average for the same dates (z = -2.4)."], evidence_against: ["A 7-day mean says nothing about the timing of the SST response."],
        data: [{ label: "Mean wind speed", value: 4.13, unit: "m/s", period: "2026-10-21 to 2026-10-27", kind: "measurement (analysis)" }, { label: "Departure of wind speed from the 2016-2025 same-week mean", value: -2.37, unit: "m/s", period: "z = -2.4", kind: "derived" }] }),
      mech("heat_flux", "Air–sea heat exchange (radiation, latent and sensible heat)", "not assessable", { kind: "climatology", caveat: "Only the usual seasonal heat budget is available; a current flux anomaly is not, so this remains unresolved.",
        data: [{ label: "Normal net heat flux into the ocean, first day", value: 95.8, unit: "W/m²", period: "2026-10-27 (1991-2020 climatology)", kind: "climatology" }] }),
      mech("sea_level", "Upper-ocean heat content (sea level anomaly)", "not consistent", { favours: "cooling", evidence_against: ["That points to a cool layer, opposite to the warm SST anomaly."] }),
      mech("enso", "ENSO state (climate-scale context)", "consistent", { kind: "context", evidence_for: ["NOAA's Niño 3.4 anomaly was +2.84 °C in 2026-09, i.e. El Niño conditions."] }),
    ],
    forecast_relationship: { dates: { sst_observation: "2026-10-27", forecast_issued_from: "2026-10-27", forecast_valid: ["2026-10-28", "2026-11-03"],
      drivers: { winds: { label: "Winds (CCMP)", observation_date: "2026-10-27", lag_days_behind_sst: 0 }, currents: { label: "Currents", observation_date: "2026-10-26", lag_days_behind_sst: 1 }, heat_flux: { label: "Heat-flux climatology", observation_date: "climatology", lag_days_behind_sst: null } } },
      statements: ["The ConvLSTM predicts cooling (-0.27 °C over 7 days).", "The physical indicators describe the latest observations (up to 2026-10-27); they are not forecasts of winds, currents or fluxes, and no forecast of them is available here.",
        "Agreement between these observations and the forecast does not establish causation. The ConvLSTM did not use any of these variables."], agreement: "not clearly consistent" },
    confidence: { level: "mixed", text: "Evidence from the wind field is consistent with the anomaly, while evidence from satellite altimetry is not.", attribution: "No causal attribution is made." },
    series: { dates, sst_anomaly_c: dates.map(() => 3.0), wind_speed_ms: dates.map((_, k) => (k % 5 === 2 ? null : 4 + k * 0.05)), zonal_stress_nm2: dates.map(() => 0.01), sea_level_anomaly_m: dates.map(() => null) },
    sources: [src("winds", "Wind and wind stress", { source: "RSS CCMP v2.1 (NOAA PIFSC ERDDAP)" }), src("heat_flux", "Surface heat flux (climatology)", { dataset_end: "climatology (no end date)", lag_days_behind_sst: null, kind: "climatology (not an observation of this year)" }),
      src("sea_level", "Sea level anomaly", { status: "stale", dataset_end: "2026-03-05", lag_days_behind_sst: 236 }), src("currents", "Surface currents"), src("enso", "ENSO indices", { status: "unavailable", dataset_end: null, lag_days_behind_sst: null, message: "could not be retrieved" })],
    method: ["Wind: the 7-day mean wind speed is compared with the same 7 calendar days of 2016-2025."], limitations: ["A current heat-flux anomaly could not be assessed: no verified NOAA flux product reaches October 2026."], ...over });

  const interpretation = (over: Record<string, unknown> = {}) => ({
    headline: "3.9 °C above normal, inside a marine heatwave that has lasted 41 days at this cell: persistent warm water",
    summary: "Sea surface temperature is 30.6 °C on 2026-10-27, 3.9 °C above the 26.7 °C normal for the date (extreme anomaly).",
    mechanisms: [
      { id: "wind", name: "Wind-driven mixing and evaporative heat exchange", support: "local_measurements", explanation: "Weaker winds mix the surface layer less and evaporate less heat from it, so the surface warms more easily.",
        evidence: ["The 7-day mean wind speed was 4.1 m/s, 2.4 m/s below the 2016-2025 average for the same dates."], evidence_ids: ["E3"], complications: ["Sea level points the other way: a cool layer."] },
      { id: "enso", name: "ENSO state (climate-scale context)", support: "climate_context", explanation: "El Niño shifts the winds and the depth of warm water across the tropical Pacific.", evidence: ["Niño 3.4 was +2.84 °C in 2026-09."], evidence_ids: ["E9"], complications: [] },
    ],
    near_term: { text: "The model expects cooling of 0.3 °C over 7 days. Wind, current and radiation values are the latest observations, not forecasts." },
    implications: { measured: ["SST is 3.9 °C above the normal for the date (observed, NOAA OISST)."], general: ["Sustained above-normal temperature may increase thermal stress in temperature-sensitive organisms."] },
    confidence: { level: "mixed", justification: "Wind evidence is consistent with the anomaly, while satellite altimetry is not.", criteria: [{ text: "Independent lines of evidence consistent with the anomaly: 1 (wind field (CCMP))", met: false }, { text: "Indicators that contradict it: satellite altimetry", met: false }] },
    key_measurements: [{ label: "SST anomaly", value: 3.9, unit: "°C", period: "2026-10-27", kind: "derived" }, { label: "Departure of wind speed from the 2016-2025 same-week mean", value: -2.37, unit: "m/s", period: "z = -2.4", kind: "derived" }],
    provider: { name: "Deterministic evidence narrator", ai_generated: false, status: "not_configured", note: "No AI provider is configured." }, ...over });
  const openXai = async () => {
    const user = userEvent.setup();
    show(report({ forecast: { available: true, issued_from: "2026-10-27", dates: ["2026-10-28"], forecast_sst: [28.6], forecast_anomaly: [1.5], persistence_sst: [28.4], typical_error_c: [0.1], direction: "warming", summary: "s", model: "ConvLSTM",
      trained_on: "x", beats_persistence: false, direction_by_day: ["warming"], reading: { label: "warming", anomaly_label: "persistent", sst_change_c: 0.2, peak_day: 1, peak_anomaly_c: 1.5, max_abs_anomaly_c: 1.5, mean_anomaly_c: 1.5, anomaly_now_c: 1.3, anomaly_end_c: 1.5, days: 1, text: "t" } } as never }));
    await goTab("Forecast");
    await user.click(await screen.findByText("🤖 Explainable AI — Why this forecast?"));
  };

  it("separates the model explanation (A) from the physical explanation (B), keeping both", async () => {
    env.getPhysicalDrivers.mockResolvedValue(physical());
    await openXai();
    expect(await screen.findByTestId("xai-part-a")).toHaveTextContent("A. Model explanation: what does the ConvLSTM predict?");
    expect(await screen.findByTestId("phys-panel")).toHaveTextContent("B. Physical explanation: what environmental processes may explain these conditions?");
    expect(screen.getByTestId("xai-model-line")).toBeInTheDocument();
    expect(env.getPhysicalDrivers).toHaveBeenCalledWith("pacific", expect.any(Number), expect.any(Number));
  });

  it("distinguishes an observed anomaly, a plausible mechanism and a verified attribution", async () => {
    env.getPhysicalDrivers.mockResolvedValue(physical());
    await openXai();
    const d = await screen.findByTestId("phys-definitions");
    expect(d).toHaveTextContent(/observed anomaly.*plausible mechanism.*verified causal attribution.*does not provide one/);
    expect(screen.getByTestId("phys-observed")).toHaveTextContent("+3.9 °C relative to its 2002-2023 climatological baseline");
  });

  it("shows the measured evidence with units, periods and the type of each value", async () => {
    env.getPhysicalDrivers.mockResolvedValue(physical());
    await openXai();
    const t = await screen.findByTestId("phys-evidence");
    expect(t).toHaveTextContent(/Mean wind speed.*4\.13.*m\/s.*2026-10-21 to 2026-10-27.*measurement \(analysis\)/);
    expect(t).toHaveTextContent(/Departure of wind speed.*-2\.37.*z = -2\.4.*derived/);
    expect(t).toHaveTextContent(/Normal net heat flux into the ocean.*95\.8.*W\/m².*1991-2020 climatology.*climatology/);
  });

  it("shows each mechanism with its verdict, evidence for, evidence against and limits", async () => {
    env.getPhysicalDrivers.mockResolvedValue(physical());
    await openXai();
    const cards = await screen.findAllByTestId("phys-mechanism");
    expect(cards).toHaveLength(4);
    const wind = cards.find((c) => c.getAttribute("data-mechanism") === "wind") as HTMLElement;
    expect(within(wind).getByTestId("phys-verdict")).toHaveTextContent("consistent");
    expect(wind).toHaveTextContent(/Evidence consistent with this mechanism.*2\.4 m\/s below the 2016-2025 average/);
    expect(wind).toHaveTextContent(/Evidence complicating it.*timing of the SST response/);
    const sl = cards.find((c) => c.getAttribute("data-mechanism") === "sea_level") as HTMLElement;
    expect(within(sl).getByTestId("phys-verdict")).toHaveTextContent("not consistent");
    expect(sl).not.toHaveTextContent("Evidence consistent with this mechanism");
    const hf = cards.find((c) => c.getAttribute("data-mechanism") === "heat_flux") as HTMLElement;
    expect(within(hf).getByTestId("phys-verdict")).toHaveTextContent("not assessable");
    expect(hf).toHaveTextContent("Climatology");
    expect(hf).toHaveTextContent(/remains unresolved/);
    expect(within(cards.find((c) => c.getAttribute("data-mechanism") === "enso") as HTMLElement).getByText("Climate context")).toBeInTheDocument();
  });

  it("keeps the observation, driver and forecast dates apart and states that drivers are not forecasts", async () => {
    env.getPhysicalDrivers.mockResolvedValue(physical());
    await openXai();
    const d = await screen.findByTestId("phys-dates");
    expect(d).toHaveTextContent("Latest observed SST2026-10-27");
    expect(d).toHaveTextContent("Forecast issued from2026-10-27");
    expect(d).toHaveTextContent("Forecast valid2026-10-28 to 2026-11-03");
    expect(d).toHaveTextContent("Winds (CCMP)2026-10-27 (same day as SST)");
    expect(d).toHaveTextContent("Currents2026-10-26 (1 d before SST)");
    expect(d).toHaveTextContent("Heat-flux climatologyclimatology");
    expect(screen.getByTestId("phys-forecast")).toHaveTextContent(/not forecasts of winds, currents or fluxes.*does not establish causation.*did not use any of these variables/);
  });

  it("states the evidence strength and that no causal attribution is made", async () => {
    env.getPhysicalDrivers.mockResolvedValue(physical());
    await openXai();
    const c = await screen.findByTestId("phys-confidence");
    expect(c).toHaveTextContent(/Evidence: mixed\..*No causal attribution is made\./);
    expect(c).toHaveTextContent("A current heat-flux anomaly could not be assessed");
  });

  it("lists every source with its status, resolution, data end and lag, marking stale and unavailable ones", async () => {
    env.getPhysicalDrivers.mockResolvedValue(physical());
    await openXai();
    const t = await screen.findByTestId("phys-sources");
    const row = (id: string) => t.querySelector(`[data-source=${id}]`) as HTMLElement;
    expect(row("winds")).toHaveTextContent(/RSS CCMP v2\.1.*0\.25° · daily.*2026-10-27.*ok/);
    expect(row("sea_level")).toHaveTextContent(/2026-03-05.*236 d before the SST date.*stale/);
    expect(row("enso")).toHaveTextContent(/unavailable.*could not be retrieved/);
    expect(row("heat_flux")).toHaveTextContent(/climatology \(not an observation of this year\)/);
  });

  it("plots a series with its gaps as gaps, and leaves out a series that has no data instead of filling it", async () => {
    env.getPhysicalDrivers.mockResolvedValue(physical());
    await openXai();
    const charts = await screen.findAllByTestId("phys-series");
    expect(charts).toHaveLength(2);                                                                           // the sea-level series is all gaps: not drawn
    const wind = charts.find((c) => c.textContent?.includes("Wind speed")) as HTMLElement;
    expect(wind.querySelectorAll("polyline").length).toBeGreaterThan(1);                                      // the missing days split the line
    expect(screen.getByTestId("phys-charts")).toHaveTextContent("gaps are missing days, not zeros");
    expect(screen.queryByText("Sea level anomaly", { selector: "figcaption" })).not.toBeInTheDocument();
  });

  it("renders without fabricated data when the sources are unavailable, and leaves the model explanation in place", async () => {
    env.getPhysicalDrivers.mockResolvedValue({ available: false, status: "unavailable", message: "The external environmental datasets could not be reached just now; the SST and forecast explanation above are unaffected." });
    await openXai();
    expect(await screen.findByTestId("phys-unavailable")).toHaveTextContent(/could not be reached just now.*unaffected/);
    expect(screen.queryByTestId("phys-evidence")).not.toBeInTheDocument();
    expect(screen.queryByTestId("phys-mechanisms")).not.toBeInTheDocument();
    expect(screen.queryByTestId("phys-charts")).not.toBeInTheDocument();
    expect(screen.getByTestId("xai-part-a")).toBeInTheDocument();
    expect(screen.getByTestId("xai-predict-table")).toBeInTheDocument();
  });

  it("shows a request failure briefly without breaking the panel", async () => {
    env.getPhysicalDrivers.mockRejectedValue(new Error("Network Error"));
    await openXai();
    expect(await screen.findByText(/The physical context could not be retrieved/)).toBeInTheDocument();
    expect(screen.getByTestId("xai-part-a")).toBeInTheDocument();
  });

  it("asks again quietly while the sources are being retrieved, then shows the evidence", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    try {
      env.getPhysicalDrivers.mockResolvedValueOnce({ available: false, status: "refreshing", refresh_hint_s: 1, message: "Retrieving the measured winds, sea level, currents and climate indices for this place." });
      await openXai();
      expect(await screen.findByTestId("phys-unavailable")).toHaveTextContent(/Retrieving the measured winds/);
      env.getPhysicalDrivers.mockResolvedValue(physical());
      await vi.advanceTimersByTimeAsync(1500);
      expect(await screen.findByTestId("phys-mechanisms")).toBeInTheDocument();
      expect(screen.queryByTestId("phys-unavailable")).not.toBeInTheDocument();
    } finally {
      vi.useRealTimers();
    }
  });

  it("a partial result shows what exists and marks the rest not assessable, without a placeholder number", async () => {
    const p = physical({ mechanisms: [mech("wind", "Wind-driven mixing and evaporative heat exchange", "not assessable", { caveat: "Wind data were not retrieved.", data: [] }), mech("enso", "ENSO state (climate-scale context)", "inconclusive", { kind: "context" })],
      series: null, sources: [src("winds", "Wind and wind stress", { status: "no_data", message: "Fewer than 7 complete days" }), src("enso", "ENSO indices")] });
    env.getPhysicalDrivers.mockResolvedValue(p);
    await openXai();
    const cards = await screen.findAllByTestId("phys-mechanism");
    expect(within(cards[0]).getByTestId("phys-verdict")).toHaveTextContent("not assessable");
    expect(screen.queryByTestId("phys-charts")).not.toBeInTheDocument();
    expect(screen.getByTestId("phys-sources").querySelector("[data-source=winds]")).toHaveTextContent("no data here");
  });


  it("shows the interpretation first, under the requested headings, before any evidence table", async () => {
    env.getPhysicalDrivers.mockResolvedValue(physical({ interpretation: interpretation() }));
    await openXai();
    const view = await screen.findByTestId("interp");
    for (const h of ["Why is this area warming or cooling?", "Likely physical drivers", "What the environmental data show", "What may happen next", "Potential marine implications"]) expect(within(view).getByRole("heading", { name: h })).toBeInTheDocument();
    expect(screen.getByTestId("interp-headline")).toHaveTextContent("41 days");
    expect(view.compareDocumentPosition(screen.getByTestId("phys-details")) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    expect(view.textContent).not.toMatch(/inconclusive|not assessable|evidence quality|cannot be established/i);
  });

  it("shows at most three leading mechanisms with their measurements and how each is supported", async () => {
    env.getPhysicalDrivers.mockResolvedValue(physical({ interpretation: interpretation() }));
    await openXai();
    const cards = await screen.findAllByTestId("interp-mechanism");
    expect(cards.length).toBeLessThanOrEqual(3);
    expect(within(cards[0]).getByTestId("interp-support")).toHaveTextContent("Local measurements");
    expect(within(cards[0]).getByTestId("interp-evidence")).toHaveTextContent("4.1 m/s");
    expect(within(cards[1]).getByTestId("interp-support")).toHaveTextContent("Climate context");
    expect(screen.getAllByTestId("interp-measurement").length).toBeGreaterThanOrEqual(2);
  });

  it("keeps complications in an expandable block and the full evidence and limitations in a collapsed section", async () => {
    env.getPhysicalDrivers.mockResolvedValue(physical({ interpretation: interpretation() }));
    await openXai();
    await screen.findByTestId("interp");
    expect(screen.getByTestId("interp-complications")).toHaveTextContent("Sea level points the other way");
    expect(screen.getByTestId("interp-complications").closest("details")).not.toHaveAttribute("open");
    const details = screen.getByTestId("phys-details");
    expect(details).not.toHaveAttribute("open");
    expect(details.querySelector("summary")).toHaveTextContent("Evidence and limitations");
    expect(within(details).getByTestId("phys-sources")).toBeInTheDocument();
  });

  it("explains the confidence qualitatively, with its criteria and no percentage", async () => {
    env.getPhysicalDrivers.mockResolvedValue(physical({ interpretation: interpretation() }));
    await openXai();
    const box = await screen.findByTestId("interp-confidence");
    expect(screen.getByTestId("interp-level")).toHaveTextContent("Mixed");
    expect(box).toHaveTextContent("Wind evidence is consistent");
    expect(screen.getByTestId("interp-criteria").querySelectorAll("li").length).toBeGreaterThanOrEqual(2);
    expect(box.textContent).not.toMatch(/\d+\s?%/);
    expect(box).toHaveTextContent(/not a probability/);
  });

  it("separates measured implications from general scientific context", async () => {
    env.getPhysicalDrivers.mockResolvedValue(physical({ interpretation: interpretation() }));
    await openXai();
    expect(await screen.findByTestId("interp-measured")).toHaveTextContent("observed, NOAA OISST");
    expect(screen.getByTestId("interp-general")).toHaveTextContent("may increase thermal stress");
    expect(screen.getByTestId("interp-implications")).toHaveTextContent("not observed here");
    expect(screen.getByTestId("interp-implications").textContent).not.toMatch(/bleach|mortality|die-off/i);
  });

  it("says plainly whether the wording is AI-assisted or the evidence-based summary", async () => {
    env.getPhysicalDrivers.mockResolvedValue(physical({ interpretation: interpretation() }));
    await openXai();
    expect(await screen.findByTestId("interp-provider")).toHaveTextContent("Evidence-based summary");
  });

  it("labels AI-written wording with the provider", async () => {
    env.getPhysicalDrivers.mockResolvedValue(physical({ interpretation: interpretation({ provider: { name: "anthropic:test-model", ai_generated: true, status: "ok", note: "checked" } }) }));
    await openXai();
    expect(await screen.findByTestId("interp-provider")).toHaveTextContent("AI-assisted wording (anthropic:test-model)");
  });

  it("tells the user while an AI model is still writing the wording", async () => {
    env.getPhysicalDrivers.mockResolvedValue(physical({ interpretation: interpretation({ provider: { name: "anthropic:test-model", ai_generated: false, status: "generating", note: "n" } }) }));
    await openXai();
    expect(await screen.findByText(/writing the wording/)).toBeInTheDocument();
    expect(screen.getByTestId("interp-provider")).toHaveTextContent("Evidence-based summary");
  });

  it("does not show an unassessable current-transport card, but keeps other cards and a valid current-transport result", async () => {
    const adv = (verdict: string) => mech("advection", "Horizontal heat transport by ocean currents", verdict, { caveat: "The geostrophic approximation fails within about 3° of the equator.", evidence_for: verdict === "consistent" ? ["The current advects warmer water."] : [] });
    env.getPhysicalDrivers.mockResolvedValue(physical({ interpretation: interpretation(), mechanisms: [mech("wind", "Wind-driven mixing and evaporative heat exchange", "consistent"), adv("not assessable"), mech("enso", "ENSO state (climate-scale context)", "consistent", { kind: "context" })] }));
    await openXai();
    const cards = await screen.findAllByTestId("phys-mechanism");
    expect(cards.map((c) => c.getAttribute("data-mechanism"))).toEqual(["wind", "enso"]);
    const panel = screen.getByTestId("phys-panel").textContent ?? "";
    expect(panel).not.toMatch(/Horizontal heat transport by ocean currents/);
    expect(panel).not.toMatch(/geostrophic approximation fails/);
    expect(screen.getByTestId("interp")).toBeInTheDocument();
    cleanup();
    env.getPhysicalDrivers.mockResolvedValue(physical({ interpretation: interpretation(), mechanisms: [adv("consistent")] }));
    await openXai();
    const ok = await screen.findAllByTestId("phys-mechanism");
    expect(ok).toHaveLength(1);
    expect(ok[0]).toHaveTextContent("Horizontal heat transport by ocean currents");
    expect(within(ok[0]).getByTestId("phys-verdict")).toHaveTextContent("consistent");
  });

  it("a failing model explanation shows its own error and leaves the physical interpretation and the report in place", async () => {
    env.getForecastExplanation.mockRejectedValue(new Error("The sensitivity analysis could not be run: ModuleNotFoundError: No module named 'torch'"));
    env.getPhysicalDrivers.mockResolvedValue(physical({ interpretation: interpretation() }));
    await openXai();
    expect(await screen.findByRole("alert")).toHaveTextContent(/sensitivity explanation could not be produced/);
    expect(await screen.findByTestId("interp")).toBeInTheDocument();
    expect(screen.getByRole("complementary", { name: "Location report" })).toBeInTheDocument();
  });

  it("shows the day each source was actually used and the source's own end when they differ", async () => {
    const sources = [src("winds", "Wind and wind stress", { dataset_end: "2026-10-27", used_through: "2026-10-24", lag_days_behind_sst: 3 }), src("sea_level", "Sea level anomaly", { dataset_end: "2026-10-27", used_through: "2026-10-27", lag_days_behind_sst: 0 })];
    env.getPhysicalDrivers.mockResolvedValue(physical({ sources }));
    await openXai();
    const t = await screen.findByTestId("phys-sources");
    expect(t).toHaveTextContent("Latest day used");
    expect(t.querySelector("[data-source=winds]")).toHaveTextContent(/2026-10-24.*source runs to 2026-10-27.*3 d before the SST date/);
    expect(t.querySelector("[data-source=sea_level]")).not.toHaveTextContent("source runs to");
  });

  it("describes evidence as consistent with a mechanism, never as proof or support of a cause", async () => {
    env.getPhysicalDrivers.mockResolvedValue(physical());
    await openXai();
    const text = (await screen.findByTestId("phys-panel")).textContent ?? "";
    expect(text).toMatch(/Evidence consistent with this mechanism/);
    expect(text).not.toMatch(/Evidence supporting|supports the cause|opposes|confirms/i);
  });

  it("headlines each mechanism by what it is: against, inconclusive or complicating", async () => {
    const p = physical({ mechanisms: [mech("sea_level", "Sea level", "not consistent", { favours: "cooling", evidence_against: ["Points the other way."] }), mech("advection", "Currents", "inconclusive", { evidence_against: ["The tendency is too small."] }),
      mech("wind", "Wind", "consistent", { evidence_for: ["Weaker winds."], evidence_against: ["Timing is unknown."] })] });
    env.getPhysicalDrivers.mockResolvedValue(p);
    await openXai();
    const cards = await screen.findAllByTestId("phys-mechanism");
    const by = (id: string) => cards.find((c) => c.getAttribute("data-mechanism") === id) as HTMLElement;
    expect(by("sea_level")).toHaveTextContent("Evidence against this mechanism");
    expect(by("advection")).toHaveTextContent("Why this is inconclusive");
    expect(by("advection")).not.toHaveTextContent(/Evidence against/);
    expect(by("wind")).toHaveTextContent("Evidence complicating it");
  });

  it("labels a bulk heat-flux estimate as an estimate, not as a local measurement", async () => {
    env.getPhysicalDrivers.mockResolvedValue(physical({ interpretation: interpretation({ mechanisms: [
      { id: "heat_flux", name: "Air–sea heat exchange", support: "local_estimate", explanation: "The estimated net heat entering the ocean is above normal.", evidence: ["+33 W/m²"], evidence_ids: ["E4"], complications: [] },
      { id: "wind", name: "Wind", support: "local_measurements", explanation: "Weaker winds.", evidence: ["4.9 m/s"], evidence_ids: ["E3"], complications: [] }] }) }));
    await openXai();
    const cards = await screen.findAllByTestId("interp-mechanism");
    expect(within(cards[0]).getByTestId("interp-support")).toHaveTextContent("Estimate from local data");
    expect(within(cards[0]).getByTestId("interp-support")).not.toHaveTextContent("measurements");
    expect(within(cards[1]).getByTestId("interp-support")).toHaveTextContent("Local measurements");
  });

  it("renders a different interpretation for a different location", async () => {
    env.getPhysicalDrivers.mockResolvedValue(physical({ interpretation: interpretation({ headline: "2.6 °C below normal: persistent cold water", mechanisms: [] }) }));
    await openXai();
    expect(await screen.findByTestId("interp-headline")).toHaveTextContent("2.6 °C below normal");
    expect(screen.queryAllByTestId("interp-mechanism")).toHaveLength(0);
    expect(screen.getByTestId("interp-drivers")).toHaveTextContent("do not single out a leading process");
  });

  it("keeps the interpretation free of causal claims", async () => {
    env.getPhysicalDrivers.mockResolvedValue(physical({ interpretation: interpretation() }));
    await openXai();
    const text = (await screen.findByTestId("interp")).textContent ?? "";
    expect(text).not.toMatch(/\bcaus(?:ed|es|ing)\b|\bproves?\b|cause established|bleaching has/i);
  });

  it("uses no causal language, no invented driver and no removed provider", async () => {
    env.getPhysicalDrivers.mockResolvedValue(physical());
    await openXai();
    const panel = await screen.findByTestId("phys-panel");
    const text = (panel.textContent ?? "").replace(/No causal attribution is made\./g, "").replace(/does not establish causation/g, "");
    expect(text).not.toMatch(/cause established|\bwas caused by\b|\bis caused by\b|\bproves\b|\bbecause of the (?:wind|current|upwelling)\b|\bcaused the (?:warming|cooling|anomaly)\b/i);
    expect(text).not.toMatch(/copernicus/i);
  });

  it("keeps its tables in horizontally scrollable wrappers so a phone screen does not overflow", async () => {
    env.getPhysicalDrivers.mockResolvedValue(physical());
    await openXai();
    await screen.findByTestId("phys-evidence");
    for (const id of ["phys-evidence", "phys-sources"]) expect(screen.getByTestId(id).querySelector("table")!.closest(".overflow-x-auto")).not.toBeNull();
  });
});

describe("the report as tabs with visual metrics", () => {
  const fc = (over: Record<string, unknown> = {}) => ({ available: true, issued_from: "2026-10-27", dates: ["2026-10-28", "2026-10-29", "2026-10-30"], forecast_sst: [28.6, 28.8, 28.9], forecast_anomaly: [1.5, 1.8, 2.0], persistence_sst: [28.4, 28.4, 28.4],
    typical_error_c: [0.1, 0.18, 0.24], direction: "warming", summary: "s", model: "ConvLSTM", trained_on: "northeast Pacific", beats_persistence: false, direction_by_day: ["warming", "warming", "warming"],
    reading: { label: "warming", anomaly_label: "strengthening", sst_change_c: 0.5, peak_day: 3, peak_anomaly_c: 2.0, max_abs_anomaly_c: 2.0, mean_anomaly_c: 1.77, anomaly_now_c: 1.3, anomaly_end_c: 2.0, days: 3,
      text: "The model predicts continued warming. The warm anomaly strengthens: +1.3 °C now to +2.0 °C at day +3." }, ...over });
  it("opens on an overview with the key values as tiles", async () => {
    show(report({ forecast: fc() as never }));
    expect(await screen.findByTestId("tile-sst")).toHaveTextContent(/Sea surface temperature/);
    expect(screen.getByTestId("tile-normal")).toHaveTextContent(/Normal for this day/);
    expect(screen.getByTestId("tile-anomaly")).toHaveTextContent(/Anomaly/);
    expect(screen.getByTestId("tile-heatwave")).toHaveTextContent(/Marine heatwave/);
    expect(screen.getByRole("tab", { name: /^Overview/ })).toHaveAttribute("aria-selected", "true");
  });

  it("shows one tab at a time, reachable by click and by the arrow keys", async () => {
    const user = userEvent.setup();
    show(report({ forecast: fc() as never }));
    await screen.findByTestId("tile-sst");
    const tabs = screen.getAllByRole("tab");
    expect(tabs.map((t) => t.textContent)).toEqual(expect.arrayContaining([expect.stringMatching(/^Overview/), expect.stringMatching(/^Forecast/), expect.stringMatching(/^Risk/), expect.stringMatching(/^Alerts/)]));
    expect(screen.getAllByRole("tabpanel")).toHaveLength(1);                                    // hidden panels are not exposed
    await user.click(screen.getByRole("tab", { name: /^Forecast/ }));
    expect(screen.getByRole("tab", { name: /^Forecast/ })).toHaveAttribute("aria-selected", "true");
    expect(screen.getByRole("tabpanel")).toHaveAttribute("id", "lr-panel-forecast");
    screen.getByRole("tab", { name: /^Forecast/ }).focus();
    await user.keyboard("{ArrowRight}");
    expect(screen.getByRole("tab", { name: /^Biodiversity/ })).toHaveAttribute("aria-selected", "true");
    await user.keyboard("{Home}");
    expect(screen.getByRole("tab", { name: /^Overview/ })).toHaveAttribute("aria-selected", "true");
  });

  it("lets the reader compare the anomaly with the normal, with this cell's history and with the region", async () => {
    const user = userEvent.setup();
    show(report({ forecast: fc() as never }));
    await screen.findByTestId("tile-sst");
    expect(screen.getByRole("img", { name: /Anomaly .* on a scale from -4 to \+4/ })).toBeInTheDocument();
    await user.click(screen.getByRole("radio", { name: "This cell's history" }));
    expect(screen.getByRole("img", { name: /of this cell's own history/ })).toBeInTheDocument();
    await user.click(screen.getByRole("radio", { name: "Region today" }));
    expect(screen.getByRole("img", { name: /among the ocean cells of the region/ })).toBeInTheDocument();
  });

  it("expands to a larger view and closes it with Escape, without losing the report", async () => {
    const user = userEvent.setup();
    show(report({ forecast: fc() as never }));
    await screen.findByTestId("tile-sst");
    await user.click(screen.getByRole("button", { name: "Expand" }));
    expect(screen.getByRole("button", { name: "Collapse" })).toHaveAttribute("aria-pressed", "true");
    expect(screen.getByTestId("tile-sst")).toBeInTheDocument();
    await user.keyboard("{Escape}");
    expect(screen.getByRole("button", { name: "Expand" })).toBeInTheDocument();
  });

  it("draws the forecast as a chart with a day-by-day strip and never shows a persistence column or a 'not established' statement", async () => {
    const user = userEvent.setup();
    show(report({ forecast: fc() as never }));
    await screen.findByTestId("tile-sst");
    await user.click(screen.getByRole("tab", { name: /^Forecast/ }));
    expect(screen.getByRole("img", { name: /Observed sea surface temperature of the last days and the forecast/ })).toBeInTheDocument();
    expect(screen.getByRole("list", { name: "Forecast days" }).querySelectorAll("li")).toHaveLength(3);
    const text = screen.getByRole("complementary", { name: "Location report" }).textContent ?? "";
    expect(text).not.toMatch(/not established|cannot be inferred from this model/i);
    expect(screen.queryByText("Persistence °C")).not.toBeInTheDocument();
  });

  it("shows the marine-heatwave category, duration and area as visual indicators", async () => {
    const user = userEvent.setup();
    show(report({ forecast: fc() as never, heatwave: { available: true, inside: true, message: "Marine heatwave: YES.", run_days: 40, event_region: "Eastern Pacific", why_it_matters: "w", analysis: { active: true, status: "Persisting", lines: ["a line"], trend: null, continuation: null },
      event: { id: "mhw-1", start_date: "2026-06-27", duration_days: 123, area_km2: 44884939, cells: 1, category: 3, category_name: "III (Severe)", current_anomaly_c: 2.5, max_anomaly_c: 8, cumulative_intensity_c_days: 219 } } as never }));
    await screen.findByTestId("tile-heatwave");
    expect(screen.getByTestId("tile-heatwave")).toHaveTextContent("YES");
    await user.click(screen.getByRole("tab", { name: /^Marine heatwave/ }));
    expect(screen.getByRole("list", { name: "Marine heatwave category scale" }).querySelector("[aria-current=true]")).toHaveTextContent("Severe");
    expect(screen.getByText("44.9 million km²")).toBeInTheDocument();
    expect(screen.getByRole("img", { name: /Days in heatwave state at this cell: 40 days/ })).toBeInTheDocument();
  });
});
