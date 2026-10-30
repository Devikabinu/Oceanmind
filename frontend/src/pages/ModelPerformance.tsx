import type { ReactNode } from "react";
import { CartesianGrid, Legend, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { getPerformance } from "../api/monitor";
import type { Performance } from "../api/monitor";
import SourceTag from "../components/SourceTag";
import Term from "../components/Term";
import PageHeader from "../components/PageHeader";
import Status from "../components/Status";
import { useAsync } from "../hooks/useAsync";
import { getDatasets, getForecast } from "../api/environment";
import type { EnvironmentDatasetAvailable } from "../api/environment";
import { cached } from "../hooks/useCached";

const BLUE = "#2563eb";
const tooltipFmt = (v: unknown) => (typeof v === "number" ? v.toFixed(4) : "–");

function Panel({ title, subtitle, children, className = "" }: { title: string; subtitle?: string; children: ReactNode; className?: string }) {
  return (
    <section className={`rounded-xl border border-slate-200 bg-white p-4 shadow-sm sm:p-5 ${className}`}>
      <h2 className="text-base font-semibold text-slate-900">{title}</h2>
      {subtitle && <p className="mt-0.5 text-sm text-slate-600">{subtitle}</p>}
      <div className="mt-3">{children}</div>
    </section>
  );
}

function Metric({ label, value, unit, note }: { label: ReactNode; value: string; unit?: string; note: string }) {
  return (
    <div className="rounded-xl border border-slate-200 bg-white p-4 shadow-sm" style={{ borderTop: `4px solid ${BLUE}` }}>
      <div className="text-xs font-semibold uppercase tracking-wide text-slate-600">{label}</div>
      <div className="mt-1 text-3xl font-semibold tabular-nums text-slate-900">{value}{unit && <span className="ml-1 text-base font-medium text-slate-600">{unit}</span>}</div>
      <div className="mt-1 text-sm text-slate-600">{note}</div>
    </div>
  );
}

function HorizonChart({ p, metric, label, unit, domain }: { p: Performance; metric: "mae" | "rmse" | "r2"; label: string; unit: string; domain: [number | string, number | string] }) {
  const data = p.horizons.map((h, i) => ({ horizon: `+${h} d`, value: p.models.convlstm[metric][i] }));
  return (
    <ResponsiveContainer width="100%" height={280}>
      <LineChart data={data} margin={{ top: 8, right: 20, bottom: 22, left: 4 }}>
        <CartesianGrid strokeDasharray="3 3" stroke="#d6e4ea" />
        <XAxis dataKey="horizon" tick={{ fontSize: 13 }} label={{ value: "Forecast horizon", position: "insideBottom", offset: -10, fontSize: 12 }} />
        <YAxis tick={{ fontSize: 13 }} width={60} domain={domain} label={{ value: unit ? `${label} (${unit})` : label, angle: -90, position: "insideLeft", fontSize: 12 }} />
        <Tooltip formatter={tooltipFmt} />
        <Legend verticalAlign="top" wrapperStyle={{ fontSize: 13, paddingBottom: 8 }} />
        <Line type="monotone" dataKey="value" name={`ConvLSTM ${label}`} stroke={BLUE} strokeWidth={3} dot={{ r: 4 }} activeDot={{ r: 6 }} />
      </LineChart>
    </ResponsiveContainer>
  );
}

function Content({ p }: { p: Performance }) {
  const c = p.models.convlstm;
  const last = p.horizons.length - 1;
  return (
    <div className="mt-4 space-y-4">
      <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 xl:grid-cols-4">
        <Metric label={<Term k="mae">Mean absolute error</Term>} value={c.mean_mae.toFixed(3)} unit="°C" note={`Average over forecast days 1–${p.horizons[last]}; day +1 ${c.mae[0].toFixed(3)} °C, day +${p.horizons[last]} ${c.mae[last].toFixed(3)} °C.`} />
        <Metric label={<Term k="rmse">Root mean square error</Term>} value={c.mean_rmse.toFixed(3)} unit="°C" note={`Day +1 ${c.rmse[0].toFixed(3)} °C, day +${p.horizons[last]} ${c.rmse[last].toFixed(3)} °C.`} />
        <Metric label={<Term k="r2">R²</Term>} value={c.mean_r2.toFixed(4)} note={`Day +1 ${c.r2[0].toFixed(4)}, day +${p.horizons[last]} ${c.r2[last].toFixed(4)}.`} />
        <Metric label="Evaluation" value={p.n_windows.toLocaleString()} unit="windows" note={`Held-out test period ${p.date_range[0]} to ${p.date_range[1]}${p.n_valid_cells ? `; about ${(p.n_valid_cells / 1e6).toFixed(0)} million ocean-cell forecasts` : ""}.`} />
      </div>

      <div className="grid grid-cols-1 gap-4 xl:grid-cols-3">
        <Panel title="MAE by forecast horizon" subtitle="Average distance from the observed temperature (lower is better).">
          <HorizonChart p={p} metric="mae" label="MAE" unit="°C" domain={[0, "auto"]} />
        </Panel>
        <Panel title="RMSE by forecast horizon" subtitle="Error weighted towards larger misses (lower is better).">
          <HorizonChart p={p} metric="rmse" label="RMSE" unit="°C" domain={[0, "auto"]} />
        </Panel>
        <Panel title="R² by forecast horizon" subtitle="Share of the variation in temperature the forecast reproduces.">
          <HorizonChart p={p} metric="r2" label="R²" unit="" domain={["auto", 1]} />
        </Panel>
      </div>

      <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
        <Panel title="Scores by forecast day">
          <div className="overflow-x-auto">
            <table className="w-full text-left text-sm">
              <caption className="sr-only">ConvLSTM error and R² for each forecast day</caption>
              <thead className="border-b border-slate-200 text-xs uppercase tracking-wide text-slate-600">
                <tr><th scope="col" className="py-2 pr-3">Forecast day</th><th scope="col" className="py-2 pr-3">MAE (°C)</th><th scope="col" className="py-2 pr-3">RMSE (°C)</th><th scope="col" className="py-2">R²</th></tr>
              </thead>
              <tbody>
                {p.horizons.map((h, i) => (
                  <tr key={h} className="border-t border-slate-100">
                    <td className="py-1.5 pr-3 font-medium text-slate-900">+{h} d</td>
                    <td className="py-1.5 pr-3 tabular-nums text-slate-800">{c.mae[i].toFixed(4)}</td>
                    <td className="py-1.5 pr-3 tabular-nums text-slate-800">{c.rmse[i].toFixed(4)}</td>
                    <td className="py-1.5 tabular-nums text-slate-800">{c.r2[i].toFixed(4)}</td>
                  </tr>
                ))}
                <tr className="border-t-2 border-slate-200 font-semibold text-slate-900">
                  <td className="py-1.5 pr-3">Mean</td><td className="py-1.5 pr-3 tabular-nums">{c.mean_mae.toFixed(4)}</td><td className="py-1.5 pr-3 tabular-nums">{c.mean_rmse.toFixed(4)}</td><td className="py-1.5 tabular-nums">{c.mean_r2.toFixed(4)}</td>
                </tr>
              </tbody>
            </table>
          </div>
        </Panel>

        <Panel title="How to read these scores">
          <ul className="space-y-2 text-sm leading-relaxed text-slate-800">
            <li><strong>MAE</strong> is how far, on average, the forecast is from the observed temperature: {c.mean_mae.toFixed(3)} °C over days 1–{p.horizons[last]}.</li>
            <li><strong>RMSE</strong> gives larger misses more weight, so it is always at least as large as MAE ({c.mean_rmse.toFixed(3)} °C here).</li>
            <li><strong>R²</strong> is close to 1 because sea surface temperature varies strongly with place and season; the error values carry the information about forecast quality.</li>
            <li>Error grows with the forecast horizon, from {c.mae[0].toFixed(3)} °C at day +1 to {c.mae[last].toFixed(3)} °C at day +{p.horizons[last]}.</li>
          </ul>
        </Panel>
      </div>

      {p.methodology && (
        <Panel title="Model and evaluation" subtitle="What the scores above describe.">
          <dl className="grid grid-cols-1 gap-x-8 gap-y-3 text-sm md:grid-cols-2">
            <div><dt className="text-xs font-semibold uppercase tracking-wide text-slate-600">Model</dt><dd className="mt-0.5 text-slate-900">{p.methodology.model}</dd></div>
            <div><dt className="text-xs font-semibold uppercase tracking-wide text-slate-600">Forecast horizon</dt><dd className="mt-0.5 text-slate-900">1 to {p.horizons[last]} days ahead</dd></div>
            <div className="md:col-span-2"><dt className="text-xs font-semibold uppercase tracking-wide text-slate-600">Task and inputs</dt><dd className="mt-0.5 text-slate-900">{p.methodology.task}</dd></div>
            <div className="md:col-span-2"><dt className="text-xs font-semibold uppercase tracking-wide text-slate-600">Evaluation</dt><dd className="mt-0.5 text-slate-900">Scored on held-out data: the test period ({p.date_range[0]} to {p.date_range[1]}, {p.n_windows} forecast windows) is never used for training or model selection. This is a retrospective evaluation of past data.</dd></div>
          </dl>
          <div className="mt-4 overflow-x-auto">
            <table className="w-full text-left text-sm">
              <caption className="sr-only">Training, validation and test periods</caption>
              <thead className="border-b border-slate-200 text-xs uppercase tracking-wide text-slate-600"><tr><th scope="col" className="py-2 pr-3">Split</th><th scope="col" className="py-2 pr-3">Period</th><th scope="col" className="py-2 pr-3">Days</th><th scope="col" className="py-2">Forecast windows</th></tr></thead>
              <tbody>
                {Object.entries(p.methodology.splits).map(([name, v]) => (
                  <tr key={name} className="border-t border-slate-100"><td className="py-1.5 pr-3 font-medium capitalize text-slate-900">{name}{name === "test" ? " (scored above)" : ""}</td><td className="py-1.5 pr-3 text-slate-800">{v.start} → {v.end}</td><td className="py-1.5 pr-3 tabular-nums text-slate-800">{v.days}</td><td className="py-1.5 tabular-nums text-slate-800">{v.windows}</td></tr>
                ))}
              </tbody>
            </table>
          </div>
        </Panel>
      )}

      {p.training && (
        <Panel title="Training" subtitle={`2-layer ConvLSTM, 32 hidden channels, 3×3 kernels, residual prediction head, ${p.training.epochs.length} epochs${p.checkpoint?.epoch != null ? `; best checkpoint at epoch ${p.checkpoint.epoch}${p.checkpoint.val_loss != null ? ` (validation loss ${p.checkpoint.val_loss.toFixed(6)})` : ""}` : ""}.`}>
          <ResponsiveContainer width="100%" height={260}>
            <LineChart data={p.training.epochs.map((e, i) => ({ epoch: e, train: p.training!.train_loss[i], validation: p.training!.val_loss[i] }))} margin={{ top: 8, right: 20, bottom: 18, left: 4 }}>
              <CartesianGrid strokeDasharray="3 3" stroke="#d6e4ea" />
              <XAxis dataKey="epoch" tick={{ fontSize: 13 }} label={{ value: "Epoch", position: "insideBottom", offset: -8, fontSize: 12 }} />
              <YAxis tick={{ fontSize: 13 }} width={60} domain={["auto", "auto"]} />
              <Tooltip formatter={tooltipFmt} />
              <Legend verticalAlign="top" wrapperStyle={{ fontSize: 13, paddingBottom: 8 }} />
              <Line type="monotone" dataKey="train" name="Training loss" stroke="#64748b" strokeWidth={2} dot />
              <Line type="monotone" dataKey="validation" name="Validation loss" stroke={BLUE} strokeWidth={2.5} dot />
            </LineChart>
          </ResponsiveContainer>
        </Panel>
      )}
    </div>
  );
}

/** The same ConvLSTM run on another dataset: scored on that dataset's own test split (the model was not retrained). */
function DatasetApplication() {
  const ds = useAsync(() => cached("env-datasets", getDatasets), []);
  const other = ds.data?.datasets.find((d): d is EnvironmentDatasetAvailable => d.available && d.id !== "ne_pacific");
  const fc = useAsync(() => (other ? getForecast(other.id, "pacific") : Promise.resolve(null)), [other?.id]);
  if (!other) return null;
  const p = fc.data?.performance;
  const c = p?.models.convlstm;
  return (
    <section className="mt-4 rounded-xl border border-slate-200 bg-white p-4 shadow-sm sm:p-5" aria-labelledby="pac-perf">
      <h2 id="pac-perf" className="border-l-4 border-lagoon pl-3 text-base font-semibold text-slate-900">The same ConvLSTM on the {other.name}</h2>
      <p className="mt-1 text-sm text-slate-700">The model was not retrained for this dataset; it was run and scored on that dataset&apos;s own held-out test period.</p>
      <Status isLoading={fc.isLoading} error={fc.error} hasData={!!p && !!c} emptyMessage="This model has not been evaluated on this dataset yet.">
        {p && c && fc.data && (
          <>
            <dl className="mt-3 grid grid-cols-2 gap-3 text-sm md:grid-cols-4">
              <div className="rounded-lg bg-slate-50 p-3"><dt className="text-xs font-semibold uppercase tracking-wide text-slate-600">Mean MAE</dt><dd className="mt-0.5 text-xl font-semibold tabular-nums text-slate-900">{c.mean_mae.toFixed(3)} °C</dd></div>
              <div className="rounded-lg bg-slate-50 p-3"><dt className="text-xs font-semibold uppercase tracking-wide text-slate-600">Mean RMSE</dt><dd className="mt-0.5 text-xl font-semibold tabular-nums text-slate-900">{c.mean_rmse.toFixed(3)} °C</dd></div>
              <div className="rounded-lg bg-slate-50 p-3"><dt className="text-xs font-semibold uppercase tracking-wide text-slate-600">Test period</dt><dd className="mt-0.5 font-semibold text-slate-900">{p.date_range[0]} to {p.date_range[1]}</dd></div>
              <div className="rounded-lg bg-slate-50 p-3"><dt className="text-xs font-semibold uppercase tracking-wide text-slate-600">Windows</dt><dd className="mt-0.5 text-xl font-semibold tabular-nums text-slate-900">{p.n_windows}</dd></div>
            </dl>
            <p className="mt-2 text-xs text-slate-600">Training period, validation period and checkpoint are those of the NE Pacific model: {fc.data.model.origin?.trained_on ?? "unknown"}.</p>
          </>
        )}
      </Status>
    </section>
  );
}

export default function ModelPerformance() {
  const { data, error, isLoading } = useAsync(getPerformance, []);
  return (
    <div>
      <PageHeader title="Model performance" actions={<SourceTag kind="evaluation" />}>
        How well does the ConvLSTM forecast sea surface temperature 1–7 days ahead? Measured on a held-out test period; lower error is better.
      </PageHeader>
      <Status isLoading={isLoading} error={error} hasData={!!data} emptyMessage="No evaluation found. Run: python -m oceanmind_model evaluate">
        {data && <Content p={data} />}
      </Status>
      <DatasetApplication />
    </div>
  );
}
