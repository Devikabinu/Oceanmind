import { apiClient } from "./client";

export interface MeanSd {
  mean: number;
  std: number;
}

export interface BenchmarkModel {
  key: "cnn_only" | "lstm_only" | "hybrid_convlstm";
  label: string;
  params: number;
  mean_rmse: MeanSd;
  mean_mae: MeanSd;
  mean_acc: MeanSd;
  rmse_by_horizon: { mean: number[]; std: number[] };
  mae_by_horizon: { mean: number[]; std: number[] };
  train_seconds: number;
}

export interface BenchmarkBaseline {
  mean_rmse: number;
  mean_mae: number;
  mean_acc: number | null;
  rmse: number[];
  mae: number[];
}

/** Saved results of the CNN-only / LSTM-only / ConvLSTM benchmark. Read-only; every number comes from the stored run. */
export interface Benchmark {
  title: string;
  test_period: [string, string];
  horizons: number[];
  models: BenchmarkModel[];
  baselines: { persistence: BenchmarkBaseline; climatology: BenchmarkBaseline };
  sample_map: { image: string | null; date: string | null; horizon_days: number | null };
}

export const getBenchmark = async (): Promise<Benchmark> => (await apiClient.get<Benchmark>("/monitor/benchmark")).data;
