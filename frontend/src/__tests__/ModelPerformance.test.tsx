import { render, screen, waitFor, within } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import type { Performance } from "../api/monitor";

const mon = vi.hoisted(() => ({ getPerformance: vi.fn() }));
const env = vi.hoisted(() => ({ getDatasets: vi.fn(), getForecast: vi.fn() }));
vi.mock("../api/monitor", async (orig) => ({ ...(await orig<typeof import("../api/monitor")>()), ...mon }));
vi.mock("../api/environment", async (orig) => ({ ...(await orig<typeof import("../api/environment")>()), ...env }));
vi.mock("recharts", () => {
  const Box = ({ children }: { children?: React.ReactNode }) => <div>{children}</div>;
  return { ResponsiveContainer: Box, LineChart: Box, BarChart: Box, Line: Box, Bar: Box, XAxis: Box, YAxis: Box, CartesianGrid: Box, Tooltip: Box, Legend: Box };
});

import ModelPerformance from "../pages/ModelPerformance";
import { clearCached } from "../hooks/useCached";

const stats = (b: number) => ({ mae: [b, b * 1.5, b * 2], rmse: [b * 1.3, b * 2, b * 2.6], r2: [0.999, 0.998, 0.997], mean_mae: b * 1.5, mean_rmse: b * 2, mean_r2: 0.998 });
const PERF: Performance = {
  split: "test", date_range: ["2025-01-01", "2026-10-27"], n_windows: 652, n_valid_cells: 11_000_000, horizons: [1, 2, 3],
  checkpoint: { which: "best", epoch: 5, val_loss: 0.004 },
  models: { convlstm: stats(0.2), persistence: stats(0.1), climatology: stats(0.9) },
  mae_skill_vs_persistence: [-0.5, -0.4, -0.3], rmse_skill_vs_persistence: [-0.5, -0.4, -0.3],
  training: { epochs: [1, 2], train_loss: [0.02, 0.01], val_loss: [0.03, 0.02] },
  methodology: {
    model: "ConvLSTM (2 layers, 32 hidden channels, 3x3 kernels, residual prediction head)", task: "Forecast daily SST 1-3 days ahead from the previous 7 days", baselines: "Persistence and climatology",
    evaluation: "All three methods are scored on identical ocean cells.", splits: { train: { start: "2002-01-01", end: "2022-12-31", days: 8000, windows: 7900 }, test: { start: "2025-01-01", end: "2026-10-27", days: 665, windows: 652 } },
  },
};

const renderPage = () => render(<MemoryRouter><ModelPerformance /></MemoryRouter>);

beforeEach(() => {
  vi.clearAllMocks();
  clearCached();
  env.getDatasets.mockResolvedValue({ datasets: [] });
});

describe("Model performance page", () => {
  it("shows the ConvLSTM's own measured scores", async () => {
    mon.getPerformance.mockResolvedValue(PERF);
    renderPage();
    expect(await screen.findByText("0.300")).toBeInTheDocument();                       // mean MAE of the ConvLSTM
    expect(screen.getAllByText("0.400").length).toBeGreaterThan(0);                              // mean RMSE
    expect(screen.getAllByText("0.9980").length).toBeGreaterThan(0);                             // mean R²
    expect(screen.getAllByText("652").length).toBeGreaterThan(0);
    expect(screen.getByText(/Held-out test period 2025-01-01 to 2026-10-27/)).toBeInTheDocument();
  });

  it("lists MAE, RMSE and R² for every forecast day, with their mean", async () => {
    mon.getPerformance.mockResolvedValue(PERF);
    renderPage();
    const table = await screen.findByRole("table", { name: /ConvLSTM error and R² for each forecast day/ });
    const rows = within(table).getAllByRole("row");
    expect(rows).toHaveLength(1 + 3 + 1);                                               // header, three days, mean
    expect(within(rows[1]).getByText("+1 d")).toBeInTheDocument();
    expect(within(rows[1]).getByText("0.2000")).toBeInTheDocument();
    expect(within(rows[4]).getByText("Mean")).toBeInTheDocument();
  });

  it("describes only the ConvLSTM: no persistence or climatology scores, charts, rows or wording", async () => {
    mon.getPerformance.mockResolvedValue(PERF);
    const { container } = renderPage();
    await screen.findByText("0.300");
    expect(container.textContent).not.toMatch(/persistence|climatology|baseline|skill/i);
    expect(container.textContent).not.toMatch(/0\.150|0\.100|0\.900/);                  // the baselines' stored scores are not shown
  });

  it("shows the training information and the splits that were used", async () => {
    mon.getPerformance.mockResolvedValue(PERF);
    renderPage();
    expect(await screen.findByText(/best checkpoint at epoch 5 \(validation loss 0.004000\)/)).toBeInTheDocument();
    const splits = screen.getByRole("table", { name: /Training, validation and test periods/ });
    expect(within(splits).getByText(/test \(scored above\)/)).toBeInTheDocument();
  });

  it("says that the evaluation is unavailable when it cannot be loaded", async () => {
    mon.getPerformance.mockRejectedValue(new Error("boom"));
    renderPage();
    await waitFor(() => expect(screen.getByRole("alert")).toHaveTextContent("Data unavailable"));
  });

  it("shows the same ConvLSTM on another dataset without any baseline comparison", async () => {
    mon.getPerformance.mockResolvedValue(PERF);
    env.getDatasets.mockResolvedValue({ datasets: [{ available: true, id: "pacific", name: "Pacific Ocean (basin-wide analysis)", provider: { is_observational: true } }] });
    env.getForecast.mockResolvedValue({ performance: { models: { convlstm: stats(0.3), persistence: stats(0.2), climatology: stats(0.9) }, date_range: ["2025-01-01", "2026-10-27"], n_windows: 652, beats_persistence: false, mae_skill_vs_persistence: [-0.1] }, model: { origin: { trained_on: "NE Pacific" } } });
    const { container } = renderPage();
    const section = await screen.findByRole("region", { name: /The same ConvLSTM on the Pacific/ });
    expect(await within(section).findByText("0.450 °C")).toBeInTheDocument();
    expect(container.textContent).not.toMatch(/persistence|climatology|skill/i);
  });
});
