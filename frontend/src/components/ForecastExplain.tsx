import { useState } from "react";
import { getForecastExplanation, getForecastModel } from "../api/environment";
import type { ForecastExplanation, ForecastModelInfo, KindedStatement, ReportDriver } from "../api/environment";
import { useAsync } from "../hooks/useAsync";
import PhysicalPanel from "./PhysicalPanel";

const signed = (v: number | null | undefined, d = 2) => (v == null ? "–" : `${v > 0 ? "+" : ""}${v.toFixed(d)}`);
const KIND_TONE: Record<string, string> = {
  observed: "bg-teal-100 text-teal-900", model_prediction: "bg-orange-100 text-orange-900", statistical: "bg-slate-200 text-slate-800", model_explanation: "bg-violet-100 text-violet-900",
  physical_cause: "bg-amber-100 text-amber-900", possible_explanation: "bg-yellow-100 text-yellow-900", ecological_implication: "bg-lime-100 text-lime-900",
};

/** One statement with the kind of evidence it is, so observations, predictions, associations and explanations are never read as the same thing. */
export function Statement({ s }: { s: KindedStatement }) {
  return (
    <li className="flex flex-col gap-1 py-1 text-sm text-slate-800 sm:flex-row sm:gap-2">
      <span className={`mt-0.5 h-fit max-w-full shrink-0 rounded px-1.5 py-0.5 text-[10px] font-semibold uppercase tracking-wide sm:max-w-[10rem] ${KIND_TONE[s.kind] ?? "bg-slate-100 text-slate-700"}`}>{s.label}</span>
      <span>{s.text}</span>
    </li>
  );
}

/** How the forecast model is built and tested; every value is read from the processed dataset's own files. */
export function ModelInputs({ dataset, preloaded }: { dataset: string; preloaded?: ForecastModelInfo }) {
  const m = useAsync(() => (preloaded ? Promise.resolve(preloaded) : getForecastModel(dataset)), [dataset, preloaded]);
  if (m.error) return <p className="text-xs text-amber-800">Model information unavailable: {m.error}</p>;
  const d = m.data;
  if (!d) return <p className="text-xs text-slate-500">Loading model information…</p>;
  const a = d.architecture;
  const ev = d.evaluation;
  return (
    <div className="space-y-2 text-sm text-slate-800" aria-label="Model inputs">
      <p><strong>{d.name}.</strong> {d.architecture_text.join(" ")}</p>
      <dl className="grid grid-cols-1 gap-x-4 gap-y-1 sm:grid-cols-2">
        <div><dt className="text-xs font-semibold uppercase text-slate-500">Input window</dt><dd>The previous <strong>{d.input.window_days}</strong> daily maps of: {d.input.channels.map((c) => CHANNEL_WORDS[c] ?? c).join("; ")}. Every grid cell sees its spatial neighbourhood through 3×3 convolutions.</dd></div>
        <div><dt className="text-xs font-semibold uppercase text-slate-500">Output</dt><dd>{d.output.variable}, forecast days +{d.output.horizons[0]} to +{d.output.horizons[d.output.horizons.length - 1]}; {d.output.form}.</dd></div>
        {a && <div><dt className="text-xs font-semibold uppercase text-slate-500">Architecture</dt><dd>{a.layers} ConvLSTM layers, {a.hidden_channels} hidden channels, {a.kernel_size}×{a.kernel_size} kernels, then a small convolutional head ({a.head_channels} channels).</dd></div>}
        <div><dt className="text-xs font-semibold uppercase text-slate-500">Checkpoint</dt><dd>{d.checkpoint.which}, epoch {d.checkpoint.epoch ?? "?"}{d.checkpoint.val_loss != null ? `, validation loss ${d.checkpoint.val_loss.toFixed(4)}` : ""}</dd></div>
        <div><dt className="text-xs font-semibold uppercase text-slate-500">Weights trained on</dt><dd>{d.training.trained_on}{d.training.retrained_for_this_dataset ? "" : " (not retrained for this dataset)"}</dd></div>
        <div><dt className="text-xs font-semibold uppercase text-slate-500">This dataset's periods</dt><dd>
          {d.periods.dataset_training && <>training {d.periods.dataset_training.start} to {d.periods.dataset_training.end}; </>}
          {d.periods.validation && <>validation {d.periods.validation.start} to {d.periods.validation.end}; </>}
          {d.periods.test && <>test {d.periods.test.start} to {d.periods.test.end}</>}</dd></div>
        <div className="sm:col-span-2"><dt className="text-xs font-semibold uppercase text-slate-500">Pre-processing and normalisation</dt>
          <dd>Fields are aligned to the analysis grid, quality-controlled and land-masked; each channel is {d.normalisation.method}. {d.normalisation.applied}. Dataset statistics (SST mean {d.normalisation.dataset_statistics.sst?.mean}, std {d.normalisation.dataset_statistics.sst?.std}) come from {d.normalisation.statistics_period ? `${d.normalisation.statistics_period[0].slice(0, 4)}–${d.normalisation.statistics_period[1].slice(0, 4)}` : "the training period"}.</dd></div>
        <div className="sm:col-span-2"><dt className="text-xs font-semibold uppercase text-slate-500">Not inputs</dt><dd>{d.input.not_inputs}</dd></div>
      </dl>
      {ev ? (
        <div>
          <p className="text-xs font-semibold uppercase text-slate-500">Baseline comparison on {ev.date_range[0]} to {ev.date_range[1]} ({ev.n_windows} windows)</p>
          <p>Mean absolute error: ConvLSTM {ev.mean_mae.convlstm.toFixed(3)} °C, persistence {ev.mean_mae.persistence.toFixed(3)} °C, climatology {ev.mean_mae.climatology.toFixed(3)} °C.
            {ev.beats_persistence ? " The model beat persistence at every horizon." : " The model did not beat persistence at every horizon, so a persistence forecast is at least as reliable in places."} Skill versus persistence by day: {ev.mae_skill_vs_persistence.map((s) => `${(s * 100).toFixed(0)}%`).join(", ")} (positive = better).</p>
        </div>
      ) : <p>The model has not been evaluated on this dataset, so no accuracy is claimed.</p>}
    </div>
  );
}

const CHANNEL_WORDS: Record<string, string> = {
  sst: "sea surface temperature", sst_anom: "SST anomaly (difference from the normal for the day)", sst_grad: "SST gradient (local temperature contrast)",
  doy_sin: "day of year (seasonal position, sine)", doy_cos: "day of year (seasonal position, cosine)", mask_sst: "ocean/land mask",
};

/** ConvLSTM against persistence for each forecast day, with the model's measured skill; says honestly where persistence is as good or better. */
function VersusPersistence({ E }: { E: ForecastExplanation }) {
  const fc = E.forecast ?? [];
  const last = E.current?.sst_c;
  const skill = E.model.evaluation?.mae_skill_vs_persistence;
  if (!fc.length || last == null) return null;
  const better = skill ? fc.filter((_, i) => skill[i] > 0).map((f) => `+${f.day}`) : [];
  const worse = skill ? fc.filter((_, i) => skill[i] <= 0).map((f) => `+${f.day}`) : [];
  const end = fc[fc.length - 1];
  return (
    <section aria-label="ConvLSTM versus persistence">
      <h4 className="text-xs font-semibold uppercase tracking-wide text-slate-600">ConvLSTM versus persistence</h4>
      <div className="overflow-x-auto"><table className="w-full text-left text-xs"><caption className="sr-only">ConvLSTM and persistence forecast by day</caption>
        <thead className="text-slate-500"><tr><th scope="col" className="pr-2">Date</th><th scope="col" className="pr-2">ConvLSTM °C</th><th scope="col" className="pr-2">Anomaly °C</th><th scope="col" className="pr-2">Direction</th><th scope="col" className="pr-2">Persistence °C</th><th scope="col" className="pr-2">Difference °C</th><th scope="col" className="pr-2">Typical error</th><th scope="col">Skill vs persistence</th></tr></thead>
        <tbody>{fc.map((f, i) => (
          <tr key={f.day} className="border-t border-slate-100"><td className="pr-2">{f.date}</td><td className="pr-2">{f.sst_c.toFixed(2)}</td><td className="pr-2">{signed(f.anomaly_c, 1)}</td><td className="pr-2">{f.direction}</td><td className="pr-2 text-slate-500">{last.toFixed(2)}</td>
            <td className="pr-2">{signed(f.sst_c - last)}</td><td className="pr-2">{f.typical_error_c != null ? `±${f.typical_error_c.toFixed(2)}` : "n/a"}</td>
            <td>{skill ? `${(skill[i] * 100).toFixed(0)}%` : "not evaluated"}</td></tr>))}</tbody></table></div>
      <ul className="mt-1 list-disc space-y-0.5 pl-5 text-xs text-slate-700">
        <li>The ConvLSTM predicts {end.direction === "about the same" ? "little change" : end.direction === "warmer" ? "warming" : "cooling"} by day +{end.day} ({signed(end.change_vs_latest_c)} °C). Persistence assumes no change at all, so it predicts neither warming nor cooling.</li>
        {skill ? (
          <li>{better.length ? `On the test period the ConvLSTM had a lower error than persistence at ${better.join(", ")}` : "On the test period the ConvLSTM did not have a lower error than persistence at any horizon"}{better.length && worse.length ? `; it did not improve on persistence at ${worse.join(", ")}, where persistence was as good or better` : !better.length ? ", so persistence was as good or better throughout" : ""}. Skill is the percentage reduction in mean absolute error (negative = worse than persistence).</li>
        ) : <li>The model has not been evaluated on this dataset, so no improvement over persistence is claimed.</li>}
        <li>A difference smaller than the typical error is not meaningful.</li>
      </ul>
    </section>
  );
}

function SensitivityMaps({ s }: { s: NonNullable<ForecastExplanation["sensitivity"]> }) {
  const [h, setH] = useState(6);
  const grid = s.spatial.delta_c[h];
  const max = Math.max(0.05, ...grid.flat().map((v) => Math.abs(v ?? 0)));
  const colour = (v: number | null) => (v == null ? "#e2e8f0" : v >= 0 ? `rgba(220,38,38,${Math.min(1, Math.abs(v) / max) * 0.85 + 0.05})` : `rgba(37,99,235,${Math.min(1, Math.abs(v) / max) * 0.85 + 0.05})`);
  const days = s.temporal.days;
  const per = s.temporal.delta_c.map((r) => r[h]);
  const tmax = Math.max(0.05, ...per.map(Math.abs));
  const latEdges = s.spatial.lat_edges, lonEdges = s.spatial.lon_edges;
  return (
    <div className="space-y-3">
      <label className="flex items-center gap-2 text-xs text-slate-700">Forecast day
        <select aria-label="Sensitivity forecast day" value={h} onChange={(e) => setH(Number(e.target.value))} className="rounded border border-slate-300 bg-white px-1.5 py-0.5">
          {s.temporal.delta_c[0].map((_, k) => <option key={k} value={k}>+{k + 1}</option>)}
        </select>
      </label>
      <div>
        <p className="text-xs font-semibold text-slate-900">Which input day the forecast responds to (°C that this day&apos;s observed anomaly contributes to the +{h + 1} day forecast; positive = pushes it warmer)</p>
        <ul className="mt-1 space-y-0.5">
          {days.map((d, k) => (
            <li key={d} className="flex items-center gap-2 text-xs">
              <span className="w-20 shrink-0 tabular-nums text-slate-600">{d.slice(5)}{k === days.length - 1 ? " (latest)" : ""}</span>
              <span className="relative h-3 flex-1 rounded bg-slate-100"><span className={`absolute top-0 h-3 rounded ${per[k] >= 0 ? "left-1/2 bg-red-500" : "right-1/2 bg-blue-500"}`} style={{ width: `${(Math.abs(per[k]) / tmax) * 50}%` }} /></span>
              <span className="w-14 shrink-0 text-right tabular-nums font-semibold">{signed(per[k])}</span>
            </li>
          ))}
        </ul>
      </div>
      <div>
        <p className="text-xs font-semibold text-slate-900">Which surrounding area it responds to ({s.block_deg}°×{s.block_deg}° blocks, all 7 input days; the outlined block contains the place)</p>
        <div className="mt-1 inline-grid gap-0.5 text-[10px]" style={{ gridTemplateColumns: `2.5rem repeat(${grid[0].length}, 3rem)` }} role="table" aria-label="Spatial sensitivity">
          {[...grid].map((_, ai) => grid.length - 1 - ai).map((a) => (
            <div key={a} className="contents" role="row">
              <span className="self-center text-right text-slate-500">{latEdges[a].toFixed(0)}°</span>
              {grid[a].map((v, b) => (
                <span key={b} role="cell" title={v == null ? "no ocean in this block" : `${signed(v)} °C`} className={`flex h-9 items-center justify-center rounded text-slate-900 ${s.spatial.own_block && s.spatial.own_block[0] === a && s.spatial.own_block[1] === b ? "ring-2 ring-slate-900" : ""}`} style={{ background: colour(v) }}>
                  {v == null ? "–" : signed(v, 1)}
                </span>
              ))}
            </div>
          ))}
          <span />
          {lonEdges.slice(0, -1).map((l) => <span key={l} className="text-center text-slate-500">{(((l + 180) % 360) - 180).toFixed(0)}°</span>)}
        </div>
      </div>
      <p className="text-xs text-slate-600">Neighbourhood analysed: ±{s.neighbourhood_deg}°. The observed anomaly in that neighbourhood (all input days) contributes {signed(s.local_all_days_c[h])} °C to the +{h + 1} day forecast; the anomaly everywhere contributes {signed(s.everywhere_all_days_c[h])} °C.</p>
    </div>
  );
}

const WORD: Record<string, string> = { warmer: "Warming", cooler: "Cooling", "about the same": "Stable", warming: "Warming", cooling: "Cooling", stable: "Stable" };

/** The recent observed anomaly followed by the forecast anomaly, as one small inline SVG (no chart library). */
function AnomalySpark({ observed, forecast }: { observed: number[]; forecast: number[] }) {
  const all = [...observed, ...forecast];
  const W = 300, H = 70, pad = 6;
  const lo = Math.min(0, ...all), hi = Math.max(0, ...all), span = hi - lo || 1;
  const x = (i: number) => pad + (i * (W - 2 * pad)) / (all.length - 1);
  const y = (v: number) => pad + ((hi - v) * (H - 2 * pad)) / span;
  const pts = (arr: number[], off: number) => arr.map((v, i) => `${x(i + off).toFixed(1)},${y(v).toFixed(1)}`).join(" ");
  return (
    <svg viewBox={`0 0 ${W} ${H}`} className="h-16 w-full max-w-sm" role="img" aria-label={`Recent observed anomaly from ${signed(observed[0], 1)} to ${signed(observed[observed.length - 1], 1)} °C, forecast anomaly to ${signed(forecast[forecast.length - 1], 1)} °C`} data-testid="xai-spark">
      <line x1={pad} x2={W - pad} y1={y(0)} y2={y(0)} stroke="#94a3b8" strokeDasharray="3 3" />
      <line x1={x(observed.length - 0.5)} x2={x(observed.length - 0.5)} y1={pad} y2={H - pad} stroke="#cbd5e1" />
      <polyline points={pts(observed, 0)} fill="none" stroke="#0f766e" strokeWidth="2" />
      <polyline points={pts(forecast, observed.length)} fill="none" stroke="#ea580c" strokeWidth="2" strokeDasharray="4 2" />
      <text x={pad} y={H - 1} fontSize="8" fill="#475569">observed anomaly</text>
      <text x={W - pad} y={H - 1} fontSize="8" fill="#475569" textAnchor="end">forecast (prediction)</text>
    </svg>
  );
}

type PredRow = { date: string; sst: number; anomaly: number; direction: string };

/** What the model predicts, day by day, with the two outlooks. Used as soon as the report is open and again, from the model run itself, once it has finished. */
function Predicts({ rows, forecastOutlook, anomalyOutlook, observed, plain }: { rows: PredRow[]; forecastOutlook?: string; anomalyOutlook?: string; observed?: number[]; plain?: boolean }) {
  return (
    <section aria-label="What the model predicts" data-testid="xai-predicts">
      <h4 className="text-xs font-semibold uppercase tracking-wide text-slate-600">What the model predicts</h4>
      <div className="overflow-x-auto"><table className="w-full text-left text-xs" data-testid="xai-predict-table"><caption className="sr-only">Predicted SST and anomaly for each of the next days</caption>
        <thead className="text-slate-500"><tr><th scope="col" className="pr-2">Date</th><th scope="col" className="pr-2 text-right">Predicted SST °C</th><th scope="col" className="pr-2 text-right">Predicted anomaly °C</th><th scope="col">Direction</th></tr></thead>
        <tbody>{rows.map((r, i) => <tr key={r.date} className="border-t border-slate-100"><td className="pr-2">Day {i + 1} · {r.date}</td><td className="pr-2 text-right tabular-nums">{r.sst.toFixed(2)}</td><td className="pr-2 text-right tabular-nums">{signed(r.anomaly, 2)}</td><td>{WORD[r.direction] ?? r.direction}</td></tr>)}</tbody></table></div>
      {(forecastOutlook || anomalyOutlook) && (
        <p className="mt-1 flex flex-wrap gap-2 text-xs" data-testid="xai-outlooks">
          {forecastOutlook && <span className="rounded bg-orange-100 px-2 py-0.5 font-semibold text-orange-900">Forecast outlook: {forecastOutlook}</span>}
          {anomalyOutlook && <span className="rounded bg-sky-100 px-2 py-0.5 font-semibold text-sky-900">Anomaly outlook: {anomalyOutlook}</span>}
        </p>
      )}
      {observed && observed.length > 1 && <div className="mt-1"><AnomalySpark observed={observed} forecast={rows.map((r) => r.anomaly)} /></div>}
      {plain && <p className="mt-1 text-xs text-slate-700">Predictions are model output, not observations.</p>}
    </section>
  );
}

export type QuickForecast = { dates?: string[]; forecast_sst?: number[]; forecast_anomaly?: number[]; direction_by_day?: string[]; reading?: { label: string; anomaly_label: string } };

function SignalBars({ E }: { E: ForecastExplanation }) {
  const sig = E.signals ?? [];
  if (!sig.length) return null;
  return (
    <div data-testid="xai-signals">
      <p className="text-xs font-semibold text-slate-900">Most influential model signals (day +{E.counterfactual?.horizon ?? 7}; measured by replacing the observed anomaly with normal conditions)</p>
      <ol className="mt-1 space-y-1">
        {sig.map((g) => (
          <li key={g.id} className="text-xs" data-testid="xai-signal">
            <div className="flex items-center gap-2">
              <span className="w-4 shrink-0 text-slate-500">{g.rank}.</span>
              <span className="flex-1 text-slate-800">{g.label}</span>
              <span className="w-16 shrink-0 text-right font-semibold tabular-nums">{signed(g.contribution_c)} °C</span>
            </div>
            <div className="ml-6 flex items-center gap-2">
              <span className="relative h-2 flex-1 rounded bg-slate-100"><span className={`absolute left-0 top-0 h-2 rounded ${g.contribution_c >= 0 ? "bg-red-500" : "bg-blue-500"}`} style={{ width: `${Math.max(2, g.relative * 100)}%` }} /></span>
              <span className="w-44 shrink-0 text-[11px] text-slate-600">{g.direction}</span>
            </div>
          </li>
        ))}
      </ol>
      <p className="mt-1 text-[11px] text-slate-500">These perturbations overlap (the local area contains the newest day), so the values are separate measurements, not shares that add up. A bar is scaled to the largest value shown.</p>
    </div>
  );
}

function RiskLink({ driver, score, level }: { driver?: ReportDriver | null; score?: number | null; level?: string | null }) {
  if (!driver || !driver.available || driver.value == null) {
    return <p className="text-xs text-slate-700" data-testid="xai-risk">The forecast component of the ecological-risk score uses the predicted anomaly over the forecast period. No forecast factor could be calculated for this place and date, so the score uses the other indicators.</p>;
  }
  const w = driver.effective_weight ?? driver.weight;
  return (
    <div data-testid="xai-risk" className="space-y-1 text-xs text-slate-800">
      <p>The forecast component of the ecological-risk score uses the mean size of the predicted anomaly over the forecast period (|anomaly| ÷ {driver.saturation_at} °C, capped at 1). A larger predicted anomaly increases this factor according to the existing scoring rule; the rule is unchanged.</p>
      <p className="rounded bg-white/70 px-2 py-1">Here: mean predicted |anomaly| <strong>{driver.raw == null ? "–" : `${Math.abs(driver.raw).toFixed(2)} °C`}</strong> → factor <strong>{driver.value.toFixed(2)}</strong> × weight <strong>{w.toFixed(2)}</strong> = contribution <strong>{driver.contribution?.toFixed(2)}</strong>{score != null ? <> of the total score <strong>{score.toFixed(2)}</strong>{level ? ` (${level === "MEDIUM" ? "MODERATE" : level})` : ""}</> : null}.{driver.saturated ? " This factor is saturated at the scoring threshold." : ""}</p>
    </div>
  );
}

/** "🤖 Explainable AI: Why this forecast?" for one place. What is already known from the report (predictions, outlooks, risk link) is shown at once; the trained model is then run on perturbed copies of its own input
 *  to measure what the forecast responds to. Loaded only when opened. */
export default function ForecastExplain({ dataset, lat, lon, quick, risk }: { dataset: string; lat: number; lon: number; quick?: QuickForecast | null; risk?: { driver?: ReportDriver | null; score?: number | null; level?: string | null } }) {
  const [open, setOpen] = useState(false);
  const x = useAsync(() => (open ? getForecastExplanation(dataset, lat, lon) : Promise.resolve(null)), [open, dataset, lat, lon]);
  const E = x.data && !x.isLoading ? x.data : null;
  const quickRows: PredRow[] = quick?.dates && quick.forecast_sst && quick.forecast_anomaly ? quick.dates.map((d, i) => ({ date: d, sst: quick.forecast_sst![i], anomaly: quick.forecast_anomaly![i], direction: quick.direction_by_day?.[i] ?? "" })) : [];
  const full = !!(E && E.available && E.current && E.forecast && E.model_explanation && E.sensitivity);
  const rows: PredRow[] = full ? E!.forecast!.map((f) => ({ date: f.date, sst: f.sst_c, anomaly: f.anomaly_c, direction: f.direction })) : quickRows;
  const ev = E?.model?.evaluation;
  const worseAt = ev ? ev.mae_skill_vs_persistence.filter((v) => v <= 0).length : null;
  return (
    <details className="mt-2 rounded-md bg-violet-50/70 p-2 text-sm ring-1 ring-violet-100" onToggle={(e) => setOpen((e.currentTarget as HTMLDetailsElement).open)}>
      <summary className="cursor-pointer text-xs font-semibold text-violet-900">🤖 Explainable AI — Why this forecast?</summary>
      <div className="mt-2 space-y-3">
        <h3 className="text-xs font-bold uppercase tracking-wide text-violet-900" data-testid="xai-part-a">A. Model explanation: what does the ConvLSTM predict?</h3>
        <p className="text-xs text-slate-800" data-testid="xai-model-line"><strong>Model:</strong> ConvLSTM · <strong>Forecast input:</strong> previous {E?.model?.input?.window_days ?? 7} daily ocean fields · <strong>Forecast horizon:</strong> next {E?.model?.output?.horizons?.length ?? 7} days</p>
        {open && rows.length > 0 && <Predicts rows={rows} forecastOutlook={(full ? E!.interpretation?.forecast_outlook : quick?.reading?.label)} anomalyOutlook={(full ? E!.interpretation?.anomaly_outlook : quick?.reading?.anomaly_label)}
          observed={full ? E!.current!.window.map((w) => w.anomaly_c) : undefined} plain />}
        {open && x.isLoading && <p role="status" className="text-xs text-slate-600">Running the trained model on perturbed copies of its own input to measure what the forecast responds to (10–20 seconds). The predictions above are already final.</p>}
        {open && x.error && <p role="alert" className="text-xs text-amber-900">The sensitivity explanation could not be produced: {x.error}</p>}
        {E && !E.available && <p className="text-xs text-slate-800">{E.message}</p>}
        {full && (
          <>
            {E!.inputs && (
              <section aria-label="Model inputs summary" data-testid="xai-model-inputs">
                <h4 className="text-xs font-semibold uppercase tracking-wide text-slate-600">Model inputs</h4>
                <dl className="grid grid-cols-2 gap-1 text-xs sm:grid-cols-3">
                  {[["Latest observed SST", `${E!.inputs.latest_sst_c.toFixed(2)} °C (${E!.inputs.latest_observation})`], ["Latest anomaly", `${signed(E!.inputs.latest_anomaly_c, 2)} °C`],
                    ["Input window", `${E!.inputs.window.start} to ${E!.inputs.window.end} (${E!.inputs.window.days} days)`],
                    ["SST trend", `${signed(E!.inputs.sst_trend_7d_c_per_day, 3)} °C/day over ${E!.inputs.window.days} days; ${signed(E!.inputs.sst_trend_3d_c_per_day, 3)} °C/day over 3 days`],
                    ["Anomaly trend", `${signed(E!.inputs.anomaly_change_7d_c, 2)} °C over ${E!.inputs.window.days} days; ${signed(E!.inputs.anomaly_change_3d_c, 2)} °C over 3 days`],
                    ["Grid", E!.inputs.grid ? `${E!.inputs.grid.rows} × ${E!.inputs.grid.cols} cells${E!.inputs.grid.resolution_deg ? `, ${E!.inputs.grid.resolution_deg}° resolution` : ""}` : "–"]].map(([l, v]) => (
                    <div key={l} className="rounded bg-white/70 px-2 py-1"><dt className="text-[11px] text-slate-500">{l}</dt><dd className="font-semibold text-slate-900">{v}</dd></div>
                  ))}
                </dl>
                <p className="mt-1 text-xs text-slate-700" data-testid="xai-inputs">Channels supplied to the model on every input day: {E!.inputs.channels.map((c) => CHANNEL_WORDS[c] ?? c).join("; ")}. {E!.inputs.spatial_context}</p>
              </section>
            )}
            <section aria-label="Why warmer or cooler" data-testid="xai-why">
              <h4 className="text-xs font-semibold uppercase tracking-wide text-slate-600">Why is it {E!.interpretation?.direction === "warming" ? "warmer" : E!.interpretation?.direction === "cooling" ? "cooler" : "stable"}?</h4>
              {E!.interpretation?.plain && <p className="text-sm text-slate-900" data-testid="xai-plain">{E!.interpretation.plain}</p>}
              <div className="mt-1 grid gap-2 sm:grid-cols-2">
                <div className="rounded-md bg-white/70 p-2 ring-1 ring-violet-100"><div className="text-[11px] font-semibold uppercase text-violet-900">Model evidence</div>
                  <ul className="mt-0.5 list-disc space-y-0.5 pl-4 text-xs text-slate-800" data-testid="xai-evidence">{E!.model_evidence?.map((t) => <li key={t}>{t}</li>)}</ul></div>
                <div className="rounded-md bg-white/70 p-2 ring-1 ring-sky-100"><div className="text-[11px] font-semibold uppercase text-sky-900">Physical interpretation</div>
                  <p className="mt-0.5 text-xs text-slate-800" data-testid="xai-physical">The physical drivers of this anomaly (winds, heat exchange, currents, sea level, ENSO) are interpreted separately in section B below. Model sensitivity does not show an oceanographic cause.</p></div>
              </div>
            </section>
            <section aria-label="What the model responds to" data-testid="xai-respond">
              <h4 className="text-xs font-semibold uppercase tracking-wide text-slate-600">What does the model respond to?</h4>
              {E!.counterfactual && (
                <>
                  <div className="overflow-x-auto"><table className="w-full text-left text-xs" data-testid="xai-counterfactual"><caption className="sr-only">Input changed, forecast response and direction at day {E!.counterfactual.horizon}</caption>
                    <thead className="text-slate-500"><tr><th scope="col" className="pr-2">Input changed</th><th scope="col" className="pr-2 text-right">Predicted anomaly °C</th><th scope="col" className="pr-2 text-right">Response °C</th><th scope="col">Direction</th></tr></thead>
                    <tbody>{E!.counterfactual.rows.map((r) => <tr key={r.label} className="border-t border-slate-100"><td className="pr-2">{r.difference_c === 0 ? "None: the observed input" : r.label}</td><td className="pr-2 text-right tabular-nums">{signed(r.anomaly_c)}</td>
                      <td className="pr-2 text-right tabular-nums">{r.difference_c === 0 ? "–" : signed(r.difference_c)}</td><td>{r.difference_c === 0 ? "–" : r.difference_c < 0 ? "lower" : "higher"}</td></tr>)}</tbody></table></div>
                  <p className="mt-1 text-xs text-slate-800" data-testid="xai-counterfactual-reading">{E!.counterfactual.reading}</p>
                </>
              )}
              <div className="mt-2"><SignalBars E={E!} /></div>
              <p className="mt-1 text-[11px] font-semibold text-violet-900">{E!.counterfactual?.title ?? E!.sensitivity!.title}.</p>
            </section>
          </>
        )}
        {open && <section aria-label="How the forecast affects the risk assessment"><h4 className="text-xs font-semibold uppercase tracking-wide text-slate-600">How this forecast affects the risk assessment</h4><RiskLink driver={risk?.driver} score={risk?.score} level={risk?.level} /></section>}
        {open && (
          <section aria-label="Limits of this explanation" className="rounded-md bg-white/70 p-2 text-xs text-slate-800" data-testid="xai-limits">
            <p className="font-semibold">Model-based sensitivity explanation: not causal attribution.</p>
            <p>The explanation shows which input patterns the trained model responds to. It does not prove that those patterns physically caused the observed or forecast ocean conditions.</p>
            <p data-testid="xai-eval">{ev ? (ev.beats_persistence ? `On this dataset's held-out test period (${ev.date_range[0]} to ${ev.date_range[1]}) the ConvLSTM had a lower error than a persistence forecast at every horizon.`
              : `On this dataset's held-out test period (${ev.date_range[0]} to ${ev.date_range[1]}) the ConvLSTM did not beat a persistence forecast at ${worseAt} of ${ev.mae_skill_vs_persistence.length} horizons (skill versus persistence ${ev.mae_skill_vs_persistence.map((v) => `${(v * 100).toFixed(0)}%`).join(", ")}); persistence is currently as good or better, and this is reported as it is.`)
              : "The model's accuracy against persistence is reported in the table below once the explanation has loaded; no skill is claimed before then."}</p>
          </section>
        )}
        {full && (
          <details className="rounded-md bg-white/60 p-2" data-testid="xai-more">
            <summary className="cursor-pointer text-xs font-semibold text-violet-900">More detail: input window, ConvLSTM versus persistence, spatial sensitivity, model configuration</summary>
            <div className="mt-2 space-y-3">
              <section aria-label="Current conditions">
                <h4 className="text-xs font-semibold uppercase tracking-wide text-slate-600">Current conditions (observed)</h4>
                <p className="text-slate-900">{E!.current!.statement}</p>
                <p className="text-xs text-slate-700">{E!.current!.trend_statement}</p>
                {E!.current!.trend_3d_c_per_day != null && (
                  <p className="text-xs text-slate-700" data-testid="xai-trends">3-day trend {signed(E!.current!.trend_3d_c_per_day, 3)} °C/day; 7-day trend {signed(E!.current!.recent_trend_c_per_day, 3)} °C/day; anomaly {signed(E!.current!.anomaly_change_3d_c, 2)} °C over 3 days and {signed(E!.current!.anomaly_change_7d_c, 2)} °C over {E!.current!.window.length} days (observed).</p>
                )}
                <div className="mt-1 overflow-x-auto"><table className="w-full text-left text-xs"><caption className="sr-only">The input window the model used</caption>
                  <thead className="text-slate-500"><tr><th scope="col" className="pr-2">Input day</th><th scope="col" className="pr-2">SST °C</th><th scope="col" className="pr-2">Normal °C</th><th scope="col">Anomaly °C</th></tr></thead>
                  <tbody>{E!.current!.window.map((w) => <tr key={w.date} className="border-t border-slate-100"><td className="pr-2">{w.date}</td><td className="pr-2">{w.sst_c.toFixed(2)}</td><td className="pr-2">{w.climatology_c.toFixed(2)}</td><td>{signed(w.anomaly_c)}</td></tr>)}</tbody></table></div>
              </section>
              {E!.interpretation && (
                <section aria-label="Forecast interpretation">
                  <h4 className="text-xs font-semibold uppercase tracking-wide text-slate-600">Forecast interpretation (from the numbers)</h4>
                  <p className="text-sm text-slate-900" data-testid="xai-interpretation">{E!.interpretation.text}</p>
                  <p className="text-xs text-slate-600">Classification: SST <strong>{E!.interpretation.direction}</strong>; anomaly <strong>{E!.interpretation.anomaly_trajectory}</strong> ({signed(E!.interpretation.start_anomaly_c, 1)} °C to {signed(E!.interpretation.end_anomaly_c, 1)} °C, total change {signed(E!.interpretation.total_change_c, 1)} °C).</p>
                </section>
              )}
              <VersusPersistence E={E!} />
              <section aria-label="Why this forecast">
                <h4 className="text-xs font-semibold uppercase tracking-wide text-slate-600">Model-predicted contributing patterns</h4>
                <ul>{E!.model_explanation!.filter((g) => g.kind !== "physical_cause").map((g) => <Statement key={g.text} s={g} />)}</ul>
                <SensitivityMaps s={E!.sensitivity!} />
                <p className="mt-1 rounded bg-white/70 p-2 text-xs text-slate-700"><strong>{E!.sensitivity!.title}.</strong> {E!.sensitivity!.plain} {E!.statement}</p>
              </section>
              <section aria-label="Model inputs">
                <h4 className="text-xs font-semibold uppercase tracking-wide text-slate-600">Model configuration, training and evaluation</h4>
                <ModelInputs dataset={dataset} preloaded={E!.model} />
              </section>
            </div>
          </details>
        )}
        {open && <PhysicalPanel dataset={dataset} lat={lat} lon={lon} />}
      </div>
    </details>
  );
}
