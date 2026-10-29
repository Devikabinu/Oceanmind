import type { ReactNode } from "react";
import { CartesianGrid, Legend, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { getBenchmark } from "../api/benchmark";
import type { Benchmark, MeanSd } from "../api/benchmark";
import PageHeader from "../components/PageHeader";
import SourceTag from "../components/SourceTag";
import Status from "../components/Status";
import { useAsync } from "../hooks/useAsync";

const COLORS: Record<string, string> = {
  cnn_only: "#7c3aed",
  lstm_only: "#f97316",
  hybrid_convlstm: "#2563eb",
  persistence: "#f59e0b",
  climatology: "#94a3b8",
};

function Panel({ title, tag, children }: { title: string; tag?: ReactNode; children: ReactNode }) {
  return (
    <div className="rounded-lg border border-slate-200 bg-white p-4">
      <div className="mb-3 flex items-center justify-between gap-2">
        <h2 className="text-sm font-semibold text-slate-900">{title}</h2>
        {tag}
      </div>
      {children}
    </div>
  );
}

const pm = (v: MeanSd, d = 4) => `${v.mean.toFixed(d)} ± ${v.std.toFixed(d)}`;

function ResultsTable({ b }: { b: Benchmark }) {
  const rows = [
    ...b.models.map((m) => ({ key: m.key, name: m.label, params: m.params.toLocaleString(), rmse: pm(m.mean_rmse), mae: pm(m.mean_mae), acc: pm(m.mean_acc, 3), time: `${m.train_seconds.toFixed(0)} s` })),
    { key: "persistence", name: "Persistence", params: "–", rmse: b.baselines.persistence.mean_rmse.toFixed(4), mae: b.baselines.persistence.mean_mae.toFixed(4), acc: b.baselines.persistence.mean_acc?.toFixed(3) ?? "–", time: "–" },
    { key: "climatology", name: "Climatology", params: "–", rmse: b.baselines.climatology.mean_rmse.toFixed(4), mae: b.baselines.climatology.mean_mae.toFixed(4), acc: "–", time: "–" },
  ];
  return (
    <div className="overflow-x-auto">
      <table className="w-full text-left text-sm">
        <caption className="sr-only">Mean test scores over forecast days 1 to 7</caption>
        <thead className="text-xs uppercase text-slate-500">
          <tr>
            <th scope="col" className="py-1 pr-4">Model</th>
            <th scope="col" className="py-1 pr-4">Parameters</th>
            <th scope="col" className="py-1 pr-4">RMSE (°C)</th>
            <th scope="col" className="py-1 pr-4">MAE (°C)</th>
            <th scope="col" className="py-1 pr-4">ACC</th>
            <th scope="col" className="py-1">Training time</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((r) => (
            <tr key={r.key} className="border-t border-slate-100">
              <td className="py-1.5 pr-4 font-medium text-slate-900">
                <span className="mr-2 inline-block h-2.5 w-2.5 rounded-full" style={{ background: COLORS[r.key] }} aria-hidden />
                {r.name}
              </td>
              <td className="py-1.5 pr-4 text-slate-700">{r.params}</td>
              <td className="py-1.5 pr-4 text-slate-700">{r.rmse}</td>
              <td className="py-1.5 pr-4 text-slate-700">{r.mae}</td>
              <td className="py-1.5 pr-4 text-slate-700">{r.acc}</td>
              <td className="py-1.5 text-slate-700">{r.time}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function HorizonChart({ b, metric }: { b: Benchmark; metric: "rmse" | "mae" }) {
  const data = b.horizons.map((h, i) => {
    const row: Record<string, number | string> = { horizon: `+${h} d` };
    for (const m of b.models) row[m.key] = metric === "rmse" ? m.rmse_by_horizon.mean[i] : m.mae_by_horizon.mean[i];
    row.persistence = b.baselines.persistence[metric][i];
    row.climatology = b.baselines.climatology[metric][i];
    return row;
  });
  const names: Record<string, string> = { persistence: "Persistence", climatology: "Climatology", ...Object.fromEntries(b.models.map((m) => [m.key, m.label])) };
  return (
    <ResponsiveContainer width="100%" height={260}>
      <LineChart data={data} margin={{ top: 8, right: 16, bottom: 18, left: 4 }}>
        <CartesianGrid strokeDasharray="3 3" stroke="#e2e8f0" />
        <XAxis dataKey="horizon" tick={{ fontSize: 12 }} label={{ value: "Forecast horizon", position: "insideBottom", offset: -4, fontSize: 11 }} />
        <YAxis tick={{ fontSize: 12 }} width={56} domain={[0, "auto"]} label={{ value: `${metric.toUpperCase()} (°C)`, angle: -90, position: "insideLeft", fontSize: 11 }} />
        <Tooltip formatter={(v: unknown) => (typeof v === "number" ? v.toFixed(4) : "–")} />
        <Legend verticalAlign="top" wrapperStyle={{ fontSize: 12, paddingBottom: 8 }} />
        {Object.keys(names).map((k) => (
          <Line key={k} type="monotone" dataKey={k} name={names[k]} stroke={COLORS[k]} strokeWidth={k === "hybrid_convlstm" ? 2.75 : 1.75} dot={{ r: 3 }} />
        ))}
      </LineChart>
    </ResponsiveContainer>
  );
}

function Content({ b }: { b: Benchmark }) {
  return (
    <div className="mt-4 space-y-4">
      <Panel title={`${b.title}: mean scores over forecast days 1–7`} tag={<SourceTag kind="evaluation" />}>
        <ResultsTable b={b} />
      </Panel>
      <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
        <Panel title="RMSE by forecast horizon (°C)" tag={<SourceTag kind="evaluation" />}>
          <HorizonChart b={b} metric="rmse" />
        </Panel>
        <Panel title="MAE by forecast horizon (°C)" tag={<SourceTag kind="evaluation" />}>
          <HorizonChart b={b} metric="mae" />
        </Panel>
      </div>
      {b.sample_map.image && (
        <Panel
          title={`Sample forecast vs truth${b.sample_map.date ? `, ${b.sample_map.horizon_days}-day forecast for ${b.sample_map.date}` : ""}`}
          tag={<SourceTag kind="forecast" />}
        >
          <img src={b.sample_map.image} alt="Sample forecast maps for each model beside the observed sea surface temperature" className="w-full rounded" />
        </Panel>
      )}
    </div>
  );
}

export default function ModelBenchmark() {
  const { data, error, isLoading } = useAsync(getBenchmark, []);
  return (
    <div>
      <PageHeader title="Model benchmark">
        CNN-only, LSTM-only and Hybrid ConvLSTM, trained and tested on the same data
        {data ? ` (${data.title}, test period ${data.test_period[0]} to ${data.test_period[1]})` : ""}.
      </PageHeader>
      <Status isLoading={isLoading} error={error} hasData={!!data} emptyMessage="No benchmark results were found in processed/benchmark/.">
        {data && <Content b={data} />}
      </Status>
    </div>
  );
}
