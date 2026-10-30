import type { ReactNode } from "react";
import { CartesianGrid, Legend, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { getBenchmark } from "../api/benchmark";
import type { Benchmark, BenchmarkModel, MeanSd } from "../api/benchmark";
import PageHeader from "../components/PageHeader";
import SourceTag from "../components/SourceTag";
import Status from "../components/Status";
import { useAsync } from "../hooks/useAsync";

const COLORS: Record<string, string> = { cnn_only: "#7c3aed", lstm_only: "#ea580c", hybrid_convlstm: "#2563eb" };

function Panel({ title, subtitle, tag, children }: { title: string; subtitle?: string; tag?: ReactNode; children: ReactNode }) {
  return (
    <section className="rounded-xl border border-slate-200 bg-white p-4 shadow-sm sm:p-5">
      <div className="mb-3 flex flex-wrap items-start justify-between gap-2">
        <div>
          <h2 className="text-base font-semibold text-slate-900">{title}</h2>
          {subtitle && <p className="mt-0.5 text-sm text-slate-600">{subtitle}</p>}
        </div>
        {tag}
      </div>
      {children}
    </section>
  );
}

const pm = (v: MeanSd, d = 4) => `${v.mean.toFixed(d)} ± ${v.std.toFixed(d)}`;

/** One card per benchmarked architecture; the model with the lowest mean RMSE is marked (the comparison is made from the stored numbers, nothing else is added). */
function ModelCards({ b }: { b: Benchmark }) {
  const best = b.models.reduce((x, y) => (y.mean_rmse.mean < x.mean_rmse.mean ? y : x)).key;
  return (
    <ul className="grid grid-cols-1 gap-3 md:grid-cols-3" aria-label="Benchmarked models">
      {b.models.map((m: BenchmarkModel) => (
        <li key={m.key} className="rounded-xl border border-slate-200 bg-white p-4 shadow-sm" style={{ borderTop: `4px solid ${COLORS[m.key]}` }} data-model={m.key}>
          <div className="flex items-start justify-between gap-2">
            <h3 className="text-base font-semibold text-slate-900">{m.label}</h3>
            {m.key === best && <span className="rounded bg-blue-100 px-2 py-0.5 text-xs font-semibold text-blue-900">Lowest RMSE</span>}
          </div>
          <div className="mt-2 text-3xl font-semibold tabular-nums text-slate-900">{m.mean_rmse.mean.toFixed(3)} <span className="text-base font-medium text-slate-600">°C RMSE</span></div>
          <dl className="mt-3 grid grid-cols-2 gap-x-3 gap-y-2 text-sm">
            <div><dt className="text-slate-500">MAE</dt><dd className="font-semibold tabular-nums text-slate-900">{m.mean_mae.mean.toFixed(3)} °C</dd></div>
            <div><dt className="text-slate-500">ACC</dt><dd className="font-semibold tabular-nums text-slate-900">{m.mean_acc.mean.toFixed(3)}</dd></div>
            <div><dt className="text-slate-500">Parameters</dt><dd className="font-semibold tabular-nums text-slate-900">{m.params.toLocaleString()}</dd></div>
            <div><dt className="text-slate-500">Training time</dt><dd className="font-semibold tabular-nums text-slate-900">{m.train_seconds.toFixed(0)} s</dd></div>
          </dl>
        </li>
      ))}
    </ul>
  );
}

function ResultsTable({ b }: { b: Benchmark }) {
  return (
    <div className="overflow-x-auto">
      <table className="w-full text-left text-sm">
        <caption className="sr-only">Mean test scores over forecast days 1 to 7</caption>
        <thead className="border-b border-slate-200 text-xs uppercase tracking-wide text-slate-600">
          <tr>
            <th scope="col" className="py-2 pr-4">Model</th>
            <th scope="col" className="py-2 pr-4">Parameters</th>
            <th scope="col" className="py-2 pr-4">RMSE (°C)</th>
            <th scope="col" className="py-2 pr-4">MAE (°C)</th>
            <th scope="col" className="py-2 pr-4">ACC</th>
            <th scope="col" className="py-2">Training time</th>
          </tr>
        </thead>
        <tbody>
          {b.models.map((m) => (
            <tr key={m.key} className="border-t border-slate-100">
              <td className="py-2 pr-4 font-medium text-slate-900">
                <span className="mr-2 inline-block h-2.5 w-2.5 rounded-full" style={{ background: COLORS[m.key] }} aria-hidden />
                {m.label}
              </td>
              <td className="py-2 pr-4 tabular-nums text-slate-700">{m.params.toLocaleString()}</td>
              <td className="py-2 pr-4 tabular-nums text-slate-700">{pm(m.mean_rmse)}</td>
              <td className="py-2 pr-4 tabular-nums text-slate-700">{pm(m.mean_mae)}</td>
              <td className="py-2 pr-4 tabular-nums text-slate-700">{pm(m.mean_acc, 3)}</td>
              <td className="py-2 tabular-nums text-slate-700">{m.train_seconds.toFixed(0)} s</td>
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
    return row;
  });
  return (
    <ResponsiveContainer width="100%" height={300}>
      <LineChart data={data} margin={{ top: 8, right: 20, bottom: 22, left: 4 }}>
        <CartesianGrid strokeDasharray="3 3" stroke="#d6e4ea" />
        <XAxis dataKey="horizon" tick={{ fontSize: 13 }} label={{ value: "Forecast horizon", position: "insideBottom", offset: -10, fontSize: 12 }} />
        <YAxis tick={{ fontSize: 13 }} width={60} domain={[0, "auto"]} label={{ value: `${metric.toUpperCase()} (°C)`, angle: -90, position: "insideLeft", fontSize: 12 }} />
        <Tooltip formatter={(v: unknown) => (typeof v === "number" ? `${v.toFixed(4)} °C` : "–")} />
        <Legend verticalAlign="top" wrapperStyle={{ fontSize: 13, paddingBottom: 8 }} />
        {b.models.map((m) => (
          <Line key={m.key} type="monotone" dataKey={m.key} name={m.label} stroke={COLORS[m.key]} strokeWidth={m.key === "hybrid_convlstm" ? 3 : 2} dot={{ r: 3.5 }} activeDot={{ r: 6 }} />
        ))}
      </LineChart>
    </ResponsiveContainer>
  );
}

function Content({ b }: { b: Benchmark }) {
  return (
    <div className="mt-4 space-y-4">
      <ModelCards b={b} />
      <Panel title="Mean scores over forecast days 1–7" subtitle={`${b.title}; test period ${b.test_period[0]} to ${b.test_period[1]}.`} tag={<SourceTag kind="evaluation" />}>
        <ResultsTable b={b} />
      </Panel>
      <div className="grid grid-cols-1 gap-4 xl:grid-cols-2">
        <Panel title="RMSE by forecast horizon" subtitle="Lower is better." tag={<SourceTag kind="evaluation" />}>
          <HorizonChart b={b} metric="rmse" />
        </Panel>
        <Panel title="MAE by forecast horizon" subtitle="Lower is better." tag={<SourceTag kind="evaluation" />}>
          <HorizonChart b={b} metric="mae" />
        </Panel>
      </div>
      {b.sample_map.image && (
        <Panel
          title={`Sample forecast vs truth${b.sample_map.date ? `, ${b.sample_map.horizon_days}-day forecast for ${b.sample_map.date}` : ""}`}
          subtitle="Each model's forecast beside the observed sea surface temperature."
          tag={<SourceTag kind="forecast" />}
        >
          <img src={b.sample_map.image} alt="Sample forecast maps for each model beside the observed sea surface temperature" className="mx-auto w-full max-w-5xl rounded-lg" />
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
