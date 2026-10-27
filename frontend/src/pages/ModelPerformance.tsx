import type { ReactNode } from "react";
import { Bar, BarChart, CartesianGrid, Legend, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { getPerformance } from "../api/monitor";
import type { ModelStats, Performance } from "../api/monitor";
import SourceTag from "../components/SourceTag";
import WhyPanel from "../components/WhyPanel";
import Term from "../components/Term";
import PageHeader from "../components/PageHeader";
import Status from "../components/Status";
import { useAsync } from "../hooks/useAsync";
import { getDatasets, getForecast } from "../api/environment";
import type { EnvironmentDatasetAvailable } from "../api/environment";
import { cached } from "../hooks/useCached";

const COLORS = { convlstm: "#2563eb", persistence: "#f59e0b", climatology: "#94a3b8" } as const;
const NAMES = { convlstm: "ConvLSTM", persistence: "Persistence", climatology: "Climatology" } as const;
type ModelKey = keyof typeof NAMES;
const KEYS: ModelKey[] = ["convlstm", "persistence", "climatology"];

const tooltipFmt = (v: unknown) => (typeof v === "number" ? v.toFixed(4) : "–");

function Panel({ title, children }: { title: string; children: ReactNode }) {
  return (
    <div className="rounded-lg border border-slate-200 bg-white p-4">
      <h2 className="mb-3 text-sm font-semibold text-slate-900">{title}</h2>
      {children}
    </div>
  );
}

function MeanTable({ p }: { p: Performance }) {
  const best = (get: (m: ModelStats) => number, lowerIsBetter: boolean) => {
    const vals = KEYS.map((k) => get(p.models[k]));
    return lowerIsBetter ? Math.min(...vals) : Math.max(...vals);
  };
  const rows: { label: string; term: ReactNode; get: (m: ModelStats) => number; lower: boolean; digits: number }[] = [
    { label: "MAE (°C)", term: <><Term k="mae">Mean Absolute Error (MAE)</Term>, °C</>, get: (m) => m.mean_mae, lower: true, digits: 4 },
    { label: "RMSE (°C)", term: <><Term k="rmse">Root Mean Square Error (RMSE)</Term>, °C</>, get: (m) => m.mean_rmse, lower: true, digits: 4 },
    { label: "R²", term: <Term k="r2">R²</Term>, get: (m) => m.mean_r2, lower: false, digits: 4 },
  ];
  return (
    <table className="w-full text-left text-sm">
      <thead className="text-xs uppercase text-slate-500">
        <tr>
          <th className="py-1 pr-3">Mean over 1–7 days</th>
          {KEYS.map((k) => (
            <th key={k} className="py-1 pr-3">
              {NAMES[k]}
            </th>
          ))}
        </tr>
      </thead>
      <tbody>
        {rows.map((r) => (
          <tr key={r.label} className="border-t border-slate-100">
            <td className="py-1.5 pr-3 text-slate-700">{r.term}</td>
            {KEYS.map((k) => {
              const v = r.get(p.models[k]);
              return (
                <td key={k} className={`py-1.5 pr-3 ${v === best(r.get, r.lower) ? "font-semibold text-slate-900" : "text-slate-600"}`}>
                  {v.toFixed(r.digits)}
                </td>
              );
            })}
          </tr>
        ))}
      </tbody>
    </table>
  );
}

function HorizonLines({ p, metric, unit }: { p: Performance; metric: "mae" | "rmse" | "r2"; unit: string }) {
  const data = p.horizons.map((h, i) => ({
    horizon: `+${h} d`,
    convlstm: p.models.convlstm[metric][i],
    persistence: p.models.persistence[metric][i],
    climatology: p.models.climatology[metric][i],
  }));
  return (
    <ResponsiveContainer width="100%" height={240}>
      <LineChart data={data} margin={{ top: 8, right: 16, bottom: 18, left: 4 }}>
        <CartesianGrid strokeDasharray="3 3" stroke="#e2e8f0" />
        <XAxis dataKey="horizon" tick={{ fontSize: 12 }} label={{ value: "Forecast horizon", position: "insideBottom", offset: -4, fontSize: 11 }} />
        <YAxis tick={{ fontSize: 12 }} width={56} unit={unit} domain={metric === "r2" ? [0.97, 1] : [0, "auto"]} label={{ value: metric === "r2" ? "R²" : "Error (°C)", angle: -90, position: "insideLeft", fontSize: 11 }} />
        <Tooltip formatter={tooltipFmt} />
        <Legend verticalAlign="top" wrapperStyle={{ fontSize: 12, paddingBottom: 8 }} />
        {KEYS.map((k) => (
          <Line key={k} type="monotone" dataKey={k} name={NAMES[k]} stroke={COLORS[k]} strokeWidth={k === "convlstm" ? 2.5 : 1.75} dot={{ r: 3 }} />
        ))}
      </LineChart>
    </ResponsiveContainer>
  );
}

function Content({ p }: { p: Performance }) {
  const c = p.models.convlstm;
  const per = p.models.persistence;
  const allBetter = c.mae.every((v, i) => v < per.mae[i]);
  const skill = p.horizons.map((h, i) => ({
    horizon: `+${h} d`,
    "MAE skill": +(p.mae_skill_vs_persistence[i] * 100).toFixed(1),
    "RMSE skill": +(p.rmse_skill_vs_persistence[i] * 100).toFixed(1),
  }));

  return (
    <>
      <div className="mt-4 rounded-md border border-green-200 bg-green-50 px-4 py-3 text-sm text-green-900">
        <p>
          ConvLSTM improves mean MAE over persistence from <strong>{per.mean_mae.toFixed(4)} °C</strong> to{" "}
          <strong>{c.mean_mae.toFixed(4)} °C</strong> ({(((per.mean_mae - c.mean_mae) / per.mean_mae) * 100).toFixed(1)}% lower).
        </p>
        {allBetter && (
          <p className="mt-1">Forecast skill remains better than persistence across all 1–7 day horizons in this test evaluation.</p>
        )}
        <p className="mt-1 text-xs text-green-800">
          Held-out test period {p.date_range[0]} to {p.date_range[1]} ({p.n_windows} forecast windows). This is a
          retrospective evaluation, not a claim about real-time operational accuracy.
        </p>
      </div>

      <div className="mt-4">
        <WhyPanel
          title="How to read this"
          reasons={[
            `Lower Mean Absolute Error (MAE) means the forecast was closer to the observed temperature: on average ${c.mean_mae.toFixed(3)} °C away, versus ${per.mean_mae.toFixed(3)} °C for simply assuming nothing changes (persistence).`,
            `The improvement over persistence grows with the forecast horizon (from ${(p.mae_skill_vs_persistence[0] * 100).toFixed(0)}% at +1 day to ${(p.mae_skill_vs_persistence[p.mae_skill_vs_persistence.length - 1] * 100).toFixed(0)}% at +7 days).`,
            `Climatology (always predicting the long-term average) is much worse at ${p.models.climatology.mean_mae.toFixed(3)} °C, so day-to-day weather-driven change matters.`,
            `R² is close to 1 for every method because temperature is mostly seasonal; the error columns are the informative comparison.`,
            `Errors are averaged over about ${p.n_valid_cells ? (p.n_valid_cells / 1e6).toFixed(0) + " million" : "many"} ocean-cell forecasts in ${p.n_windows} test windows. A few tenths of a degree is typical; local errors can be larger.`,
          ]}
          classification="Evaluation on held-out data the model never saw during training. It says nothing about real-time operational accuracy."
        />
      </div>

      {p.methodology && (
        <section className="mt-4 rounded-lg border border-slate-200 bg-white p-4" aria-label="Model and evaluation method">
          <h2 className="text-sm font-semibold text-slate-900">Model and evaluation method</h2>
          <dl className="mt-2 grid grid-cols-1 gap-x-6 gap-y-2 text-sm md:grid-cols-2">
            <div><dt className="text-xs font-medium uppercase text-slate-500">Model</dt><dd className="text-slate-800">{p.methodology.model}</dd></div>
            <div><dt className="text-xs font-medium uppercase text-slate-500">Forecast horizon</dt><dd className="text-slate-800">1 to {p.horizons[p.horizons.length - 1]} days ahead</dd></div>
            <div className="md:col-span-2"><dt className="text-xs font-medium uppercase text-slate-500">Task and inputs</dt><dd className="text-slate-800">{p.methodology.task}</dd></div>
            <div><dt className="text-xs font-medium uppercase text-slate-500">Baselines</dt><dd className="text-slate-800">{p.methodology.baselines}</dd></div>
            <div><dt className="text-xs font-medium uppercase text-slate-500">Improvement over persistence (mean MAE)</dt><dd className="text-slate-800">{(((per.mean_mae - c.mean_mae) / per.mean_mae) * 100).toFixed(1)}% lower error ({c.mean_mae.toFixed(3)} vs {per.mean_mae.toFixed(3)} °C)</dd></div>
            <div className="md:col-span-2"><dt className="text-xs font-medium uppercase text-slate-500">Evaluation</dt><dd className="text-slate-800">{p.methodology.evaluation}</dd></div>
          </dl>
          <table className="mt-3 w-full text-left text-sm">
            <caption className="sr-only">Training, validation and test periods</caption>
            <thead className="text-xs uppercase text-slate-600"><tr><th scope="col" className="py-1 pr-3">Split</th><th scope="col" className="py-1 pr-3">Period</th><th scope="col" className="py-1 pr-3">Days</th><th scope="col" className="py-1">Forecast windows</th></tr></thead>
            <tbody>
              {Object.entries(p.methodology.splits).map(([name, v]) => (
                <tr key={name} className="border-t border-slate-100"><td className="py-1 pr-3 font-medium capitalize">{name}{name === "test" ? " (reported above)" : ""}</td><td className="py-1 pr-3">{v.start} → {v.end}</td><td className="py-1 pr-3">{v.days}</td><td className="py-1">{v.windows}</td></tr>
              ))}
            </tbody>
          </table>
        </section>
      )}

      <div className="mt-6 grid grid-cols-1 gap-4 lg:grid-cols-3">
        {KEYS.map((k) => (
          <div key={k} className="rounded-lg border border-slate-200 bg-white p-4" style={{ borderTop: `3px solid ${COLORS[k]}` }}>
            <div className="text-xs font-medium uppercase tracking-wide text-slate-500">{NAMES[k]}</div>
            <div className="mt-1 text-2xl font-semibold text-slate-900">{p.models[k].mean_mae.toFixed(3)} °C</div>
            <div className="text-xs text-slate-500">
              mean MAE · RMSE {p.models[k].mean_rmse.toFixed(3)} °C · R² {p.models[k].mean_r2.toFixed(4)}
            </div>
          </div>
        ))}
      </div>

      <div className="mt-6 grid grid-cols-1 gap-4 lg:grid-cols-2">
        <Panel title="Mean scores, three models">
          <MeanTable p={p} />
          <p className="mt-2 text-xs text-slate-400">
            Persistence = repeat the last observed map. Climatology = long-term normal for that day of the year. All
            three are scored on identical ocean cells. Bold = best in row.
          </p>
        </Panel>
        <Panel title="MAE improvement over persistence, by horizon (%)">
          <ResponsiveContainer width="100%" height={240}>
            <BarChart data={skill} margin={{ top: 8, right: 16, bottom: 4, left: 0 }}>
              <CartesianGrid strokeDasharray="3 3" stroke="#e2e8f0" />
              <XAxis dataKey="horizon" tick={{ fontSize: 12 }} />
              <YAxis tick={{ fontSize: 12 }} unit="%" width={44} />
              <Tooltip formatter={(v) => (typeof v === "number" ? `${v}%` : "–")} />
              <Legend verticalAlign="top" wrapperStyle={{ fontSize: 12, paddingBottom: 8 }} />
              <Bar dataKey="MAE skill" fill="#2563eb" radius={[3, 3, 0, 0]} />
              <Bar dataKey="RMSE skill" fill="#93c5fd" radius={[3, 3, 0, 0]} />
            </BarChart>
          </ResponsiveContainer>
        </Panel>
        <Panel title="MAE by forecast horizon (°C, lower is better)">
          <HorizonLines p={p} metric="mae" unit="°" />
        </Panel>
        <Panel title="RMSE by forecast horizon (°C, lower is better)">
          <HorizonLines p={p} metric="rmse" unit="°" />
        </Panel>
        <Panel title="R² by forecast horizon (higher is better)">
          <HorizonLines p={p} metric="r2" unit="" />
        </Panel>
        <Panel title="Per-horizon MAE (°C)">
          <table className="w-full text-left text-sm">
            <thead className="text-xs uppercase text-slate-500">
              <tr>
                <th className="py-1 pr-3">Horizon</th>
                {KEYS.map((k) => (
                  <th key={k} className="py-1 pr-3">
                    {NAMES[k]}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {p.horizons.map((h, i) => (
                <tr key={h} className="border-t border-slate-100">
                  <td className="py-1 pr-3 font-medium">+{h} d</td>
                  {KEYS.map((k) => (
                    <td key={k} className={`py-1 pr-3 ${k === "convlstm" ? "font-semibold text-blue-700" : "text-slate-600"}`}>
                      {p.models[k].mae[i].toFixed(4)}
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </Panel>
      </div>

      {p.training && (
        <details className="mt-6 rounded-lg border border-slate-200 bg-white p-4">
          <summary className="cursor-pointer text-sm font-semibold text-slate-900">Training details (secondary)</summary>
          <p className="mt-2 text-sm text-slate-500">
            2-layer ConvLSTM, 32 hidden channels, 3×3 kernels, residual prediction head, trained on CPU for{" "}
            {p.training.epochs.length} epochs.
            {p.checkpoint?.epoch != null &&
              ` Best checkpoint: epoch ${p.checkpoint.epoch}${p.checkpoint.val_loss != null ? `, validation loss ${p.checkpoint.val_loss.toFixed(6)}` : ""}.`}
          </p>
          <ResponsiveContainer width="100%" height={220}>
            <LineChart
              data={p.training.epochs.map((e, i) => ({ epoch: e, train: p.training!.train_loss[i], validation: p.training!.val_loss[i] }))}
              margin={{ top: 8, right: 16, bottom: 4, left: 0 }}
            >
              <CartesianGrid strokeDasharray="3 3" stroke="#e2e8f0" />
              <XAxis dataKey="epoch" tick={{ fontSize: 12 }} />
              <YAxis tick={{ fontSize: 12 }} width={56} domain={["auto", "auto"]} />
              <Tooltip formatter={tooltipFmt} />
              <Legend verticalAlign="top" wrapperStyle={{ fontSize: 12, paddingBottom: 8 }} />
              <Line type="monotone" dataKey="train" name="Train loss" stroke="#64748b" dot />
              <Line type="monotone" dataKey="validation" name="Validation loss" stroke="#2563eb" dot />
            </LineChart>
          </ResponsiveContainer>
        </details>
      )}
    </>
  );
}

/** The same ConvLSTM applied to another dataset: evaluated separately, on that dataset's own test split. Not a validation of the Pacific ocean. */
function DatasetApplication() {
  const ds = useAsync(() => cached("env-datasets", getDatasets), []);
  const other = ds.data?.datasets.find((d): d is EnvironmentDatasetAvailable => d.available && d.id !== "ne_pacific");
  const fc = useAsync(() => (other ? getForecast(other.id, "pacific") : Promise.resolve(null)), [other?.id]);
  if (!other) return null;
  const p = fc.data?.performance;
  return (
    <section className="mt-8 rounded-lg bg-white/70 p-4 ring-1 ring-slate-200" aria-labelledby="pac-perf">
      <h2 id="pac-perf" className="border-l-4 border-lagoon pl-3 text-lg font-semibold text-slate-900">The same model applied to the {other.name}</h2>
      <p className="mt-1 text-sm text-slate-700">
        The scores above were measured on observed NOAA OISST data of the NE Pacific. For the {other.id} dataset the model was <strong>not retrained</strong>; it was only run and scored on
        that dataset&apos;s own held-out test period. Those numbers describe how the model behaves on {other.provider.is_observational ? "that" : "modelled"} data, not how well it
        predicts the real Pacific.
      </p>
      <Status isLoading={fc.isLoading} error={fc.error} hasData={!!p} emptyMessage="This model has not been evaluated on this dataset, so no Pacific performance is claimed.">
        {p && fc.data && (
          <>
            <div className="mt-3 overflow-x-auto">
              <table className="w-full text-left text-sm">
                <caption className="sr-only">Measured error on the {other.id} dataset</caption>
                <thead className="text-xs uppercase text-slate-600">
                  <tr><th scope="col" className="py-1 pr-3">Model</th><th scope="col" className="py-1 pr-3">Mean MAE °C</th><th scope="col" className="py-1">Mean RMSE °C</th></tr>
                </thead>
                <tbody>
                  {Object.entries(p.models).map(([k, m]) => (
                    <tr key={k} className="border-t border-slate-100"><td className="py-1 pr-3 font-medium capitalize">{k === "convlstm" ? "ConvLSTM" : k}</td><td className="py-1 pr-3">{m.mean_mae.toFixed(3)}</td><td className="py-1">{m.mean_rmse.toFixed(3)}</td></tr>
                  ))}
                </tbody>
              </table>
            </div>
            <p className="mt-2 text-sm text-slate-800">
              Test period {p.date_range[0]} to {p.date_range[1]} ({p.n_windows} windows). {p.beats_persistence ? "The model beat persistence at every horizon." : "The model did not beat persistence at every horizon on this dataset."}{" "}
              MAE skill versus persistence: {p.mae_skill_vs_persistence.map((s) => `${(s * 100).toFixed(1)}%`).join(", ")}.
            </p>
            <p className="mt-1 text-xs text-slate-600">Training period, validation period and checkpoint are those of the NE Pacific model: {fc.data.model.origin?.trained_on ?? "unknown"}.</p>
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
        How well does the ConvLSTM forecast sea surface temperature 1–7 days ahead, compared with two simple baselines:{" "}
        <Term k="persistence">persistence</Term> and <Term k="climatology">climatology</Term>? Lower error is better.
      </PageHeader>
      <Status isLoading={isLoading} error={error} hasData={!!data} emptyMessage="No evaluation found. Run: python -m oceanmind_model evaluate">
        {data && <Content p={data} />}
      </Status>
      <DatasetApplication />
    </div>
  );
}
