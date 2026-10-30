import { render, screen, waitFor, within } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import type { Benchmark } from "../api/benchmark";

const api = vi.hoisted(() => ({ getBenchmark: vi.fn() }));
vi.mock("../api/benchmark", async (orig) => ({ ...(await orig<typeof import("../api/benchmark")>()), ...api }));
vi.mock("recharts", () => {
  const Box = ({ children }: { children?: React.ReactNode }) => <div>{children}</div>;
  return { ResponsiveContainer: Box, LineChart: Box, Line: Box, XAxis: Box, YAxis: Box, CartesianGrid: Box, Tooltip: Box, Legend: Box };
});

import ModelBenchmark from "../pages/ModelBenchmark";

const stat = (mean: number, std = 0.01) => ({ mean, std });
const model = (key: Benchmark["models"][number]["key"], label: string, rmse: number, params: number) => ({
  key, label, params, mean_rmse: stat(rmse), mean_mae: stat(rmse * 0.8), mean_acc: stat(0.9, 0.02),
  rmse_by_horizon: { mean: [rmse, rmse], std: [0.01, 0.01] }, mae_by_horizon: { mean: [rmse, rmse], std: [0.01, 0.01] }, train_seconds: 30,
});
const BENCH: Benchmark = {
  title: "3-year benchmark",
  test_period: ["2025-12-10", "2026-04-30"],
  horizons: [1, 2],
  models: [model("cnn_only", "CNN-only", 0.3, 127913), model("lstm_only", "LSTM-only", 0.4, 125895), model("hybrid_convlstm", "Hybrid ConvLSTM", 0.2, 127239)],
  baselines: {
    persistence: { mean_rmse: 0.5, mean_mae: 0.4, mean_acc: 0.93, rmse: [0.5, 0.5], mae: [0.4, 0.4] },
    climatology: { mean_rmse: 0.9, mean_mae: 0.8, mean_acc: null, rmse: [0.9, 0.9], mae: [0.8, 0.8] },
  },
  sample_map: { image: "data:image/png;base64,AAAA", date: "2026-02-25", horizon_days: 7 },
};

const renderPage = () => render(<MemoryRouter><ModelBenchmark /></MemoryRouter>);

beforeEach(() => vi.clearAllMocks());

describe("ModelBenchmark page", () => {
  it("shows the stored numbers for the three benchmarked architectures only", async () => {
    api.getBenchmark.mockResolvedValue(BENCH);
    renderPage();
    const table = await screen.findByRole("table");
    const rows = within(table).getAllByRole("row");
    expect(rows).toHaveLength(4); // header + CNN-only + LSTM-only + Hybrid ConvLSTM
    const hybrid = rows.find((r) => within(r).queryByText("Hybrid ConvLSTM"))!;
    expect(within(hybrid).getByText((127239).toLocaleString())).toBeInTheDocument();
    expect(within(hybrid).getByText("0.2000 ± 0.0100")).toBeInTheDocument();
    expect(screen.getAllByText(/test period 2025-12-10 to 2026-04-30/).length).toBeGreaterThan(0);
  });

  it("shows no persistence or climatology row, card or legend entry", async () => {
    api.getBenchmark.mockResolvedValue(BENCH);
    const { container } = renderPage();
    await screen.findByRole("table");
    expect(container.textContent).not.toMatch(/persistence|climatology/i);
  });

  it("summarises each model in a card and marks the lowest RMSE from the stored values", async () => {
    api.getBenchmark.mockResolvedValue(BENCH);
    renderPage();
    const list = await screen.findByRole("list", { name: "Benchmarked models" });
    const cards = within(list).getAllByRole("listitem");
    expect(cards).toHaveLength(3);
    const hybrid = cards.find((c) => c.getAttribute("data-model") === "hybrid_convlstm")!;
    expect(within(hybrid).getByText("Lowest RMSE")).toBeInTheDocument();
    expect(within(hybrid).getByText("0.200")).toBeInTheDocument();
    expect(within(list).getAllByText("Lowest RMSE")).toHaveLength(1);
  });

  it("shows the sample forecast map", async () => {
    api.getBenchmark.mockResolvedValue(BENCH);
    renderPage();
    const img = await screen.findByAltText(/Sample forecast maps/);
    expect(img).toHaveAttribute("src", "data:image/png;base64,AAAA");
    expect(screen.getByText(/7-day forecast for 2026-02-25/)).toBeInTheDocument();
  });

  it("shows results only: no notes, caveats or comparison sentences", async () => {
    api.getBenchmark.mockResolvedValue(BENCH);
    renderPage();
    await screen.findByRole("table");
    expect(screen.queryByText(/limitation/i)).toBeNull();
    expect(screen.queryByText(/not a reliable/i)).toBeNull();
  });

  it("says the data is unavailable (not empty) when the request fails", async () => {
    api.getBenchmark.mockRejectedValue(new Error("boom"));
    renderPage();
    await waitFor(() => expect(screen.getByRole("alert")).toHaveTextContent("Data unavailable"));
    expect(screen.queryByRole("table")).toBeNull();
  });
});
