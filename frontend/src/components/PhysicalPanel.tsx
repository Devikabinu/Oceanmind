import { useEffect, useRef, useState } from "react";
import { getPhysicalDrivers } from "../api/environment";
import type { PhysicalMechanism, PhysicalReport } from "../api/environment";
import { useAsync } from "../hooks/useAsync";
import PhysicalInterpretationView from "./PhysicalInterpretation";

const VERDICT_TONE: Record<string, string> = {
  consistent: "bg-emerald-100 text-emerald-900", "not consistent": "bg-rose-100 text-rose-900", inconclusive: "bg-slate-200 text-slate-800", "not assessable": "bg-amber-100 text-amber-900",
};
/** A signed number for departures, trends and tendencies, a plain one for levels (wind speed, stress, sea level, fluxes). */
const fmtValue = (d: { label: string; value: number | string }) => {
  if (typeof d.value !== "number") return d.value;
  const dec = Math.abs(d.value) < 1 ? 3 : Math.abs(d.value) < 100 ? 2 : 0;
  return /anomaly|departure|trend|tendency|change|toward|offshore|\(\+ =/i.test(d.label) ? `${d.value > 0 ? "+" : ""}${d.value.toFixed(dec)}` : d.value.toFixed(dec);
};
const KIND_LABEL: Record<string, string> = { measurement: "Measurement", derived: "Derived indicator", climatology: "Climatology", context: "Climate context", hypothesis: "Hypothesis" };

/** One variable over the last days. A missing day is a gap in the line, never a zero or an interpolated value. */
function MiniSeries({ title, unit, dates, values, tone }: { title: string; unit: string; dates: string[]; values: (number | null)[]; tone: string }) {
  const have = values.filter((v): v is number => v != null);
  if (have.length < 3) return null;
  const W = 220, H = 56, pad = 5;
  const lo = Math.min(...have), hi = Math.max(...have), span = hi - lo || 1;
  const x = (i: number) => pad + (i * (W - 2 * pad)) / (dates.length - 1);
  const y = (v: number) => pad + ((hi - v) * (H - 2 * pad)) / span;
  const segs: string[] = [];
  let cur: string[] = [];
  values.forEach((v, i) => {
    if (v == null) { if (cur.length) segs.push(cur.join(" ")); cur = []; } else cur.push(`${x(i).toFixed(1)},${y(v).toFixed(1)}`);
  });
  if (cur.length) segs.push(cur.join(" "));
  return (
    <figure className="min-w-0" data-testid="phys-series">
      <figcaption className="text-[11px] font-semibold text-slate-700">{title} <span className="font-normal text-slate-500">({unit})</span></figcaption>
      <svg viewBox={`0 0 ${W} ${H}`} className="h-14 w-full" role="img" aria-label={`${title}, ${dates[0]} to ${dates[dates.length - 1]}: from ${have[0]} to ${have[have.length - 1]} ${unit}`}>
        {segs.map((p, k) => <polyline key={k} points={p} fill="none" stroke={tone} strokeWidth="2" />)}
      </svg>
      <div className="flex justify-between text-[10px] text-slate-500"><span>{dates[0].slice(5)}</span><span>{lo.toFixed(2)} to {hi.toFixed(2)}</span><span>{dates[dates.length - 1].slice(5)}</span></div>
    </figure>
  );
}

function Mechanism({ m }: { m: PhysicalMechanism }) {
  return (
    <li className="rounded-md bg-white/70 p-2 ring-1 ring-slate-200" data-testid="phys-mechanism" data-mechanism={m.id}>
      <div className="flex flex-wrap items-center gap-2">
        <span className="text-sm font-semibold text-slate-900">{m.name}</span>
        <span className={`rounded px-1.5 py-0.5 text-[11px] font-semibold ${VERDICT_TONE[m.verdict] ?? "bg-slate-100"}`} data-testid="phys-verdict">{m.verdict}</span>
        <span className="rounded bg-white px-1.5 py-0.5 text-[10px] font-medium text-slate-600 ring-1 ring-slate-200">{KIND_LABEL[m.kind] ?? m.kind}</span>
        {m.favours && <span className="text-[11px] text-slate-600">tends toward {m.favours}</span>}
      </div>
      {m.evidence_for.length > 0 && <div className="mt-1"><div className="text-[11px] font-semibold uppercase text-emerald-900">Evidence consistent with this mechanism</div><ul className="list-disc pl-5 text-xs text-slate-800">{m.evidence_for.map((t) => <li key={t}>{t}</li>)}</ul></div>}
      {m.evidence_against.length > 0 && <div className="mt-1"><div className="text-[11px] font-semibold uppercase text-rose-900">{m.verdict === "not consistent" ? "Evidence against this mechanism" : m.verdict === "inconclusive" ? "Why this is inconclusive" : "Evidence complicating it"}</div><ul className="list-disc pl-5 text-xs text-slate-800">{m.evidence_against.map((t) => <li key={t}>{t}</li>)}</ul></div>}
      <p className="mt-1 text-[11px] text-slate-600"><strong>Limits:</strong> {m.caveat} <span className="text-slate-500">(evidence quality: {m.evidence_quality})</span></p>
    </li>
  );
}

/** B. Physical explanation: measured environmental indicators matched to the SST anomaly and the forecast, with what each can and cannot show. Never an attribution. */
export default function PhysicalPanel({ dataset, lat, lon }: { dataset: string; lat: number; lon: number }) {
  const first = useAsync(() => getPhysicalDrivers(dataset, lat, lon), [dataset, lat, lon]);
  const key = `${dataset}|${lat}|${lon}`;
  const [fresh, setFresh] = useState<{ key: string; data: PhysicalReport } | null>(null);
  const tries = useRef({ key: "", n: 0 });
  const cur = fresh && fresh.key === key ? fresh.data : first.data && !first.isLoading ? first.data : null;
  useEffect(() => {
    if (tries.current.key !== key) tries.current = { key, n: 0 };
    const hint = cur?.refresh_hint_s;
    if (!hint || tries.current.n >= 6) return;
    const t = setTimeout(async () => {
      tries.current.n += 1;
      try { setFresh({ key, data: await getPhysicalDrivers(dataset, lat, lon) }); } catch { /* the content on screen stays */ }
    }, hint * 1000);
    return () => clearTimeout(t);
  }, [cur, key]); // eslint-disable-line react-hooks/exhaustive-deps
  const R = cur;
  return (
    <section aria-label="Physical explanation" className="space-y-3 rounded-md bg-sky-50/60 p-2 ring-1 ring-sky-100" data-testid="phys-panel">
      <h3 className="text-xs font-bold uppercase tracking-wide text-sky-900">B. Physical explanation: what environmental processes may explain these conditions?</h3>
      {first.isLoading && !R && <p role="status" className="text-xs text-slate-600">Retrieving measured winds, sea level, currents and climate indices for this place…</p>}
      {first.error && !R && <p role="alert" className="text-xs text-amber-900">The physical context could not be retrieved: {first.error}. The model explanation above is unaffected.</p>}
      {R && !R.available && <p className="text-xs text-slate-800" data-testid="phys-unavailable">{R.message}</p>}
      {R && R.available && R.interpretation && <PhysicalInterpretationView I={R.interpretation} />}
      {R && R.available && R.observed && R.mechanisms && R.forecast_relationship && R.confidence && (
        <details className="rounded-md bg-white/60 p-2" data-testid="phys-details">
          <summary className="cursor-pointer text-xs font-semibold text-sky-900">Evidence and limitations: data, dates, sources ({R.sources?.filter((s) => s.status === "ok").length ?? 0} of {R.sources?.length ?? 0} sources reporting), how each mechanism was assessed, uncertainty</summary>
          <div className="mt-2 space-y-3">
          <p className="text-[11px] text-slate-600" data-testid="phys-definitions">An <strong>observed anomaly</strong> is a measured departure from normal. A <strong>plausible mechanism</strong> is a process whose measured indicator moves the way that would produce it. A <strong>verified causal attribution</strong> would need a closed heat budget or an experiment; this panel does not provide one.</p>
          <div data-testid="phys-observed">
            <h4 className="text-xs font-semibold uppercase tracking-wide text-slate-600">1. Observed ocean conditions</h4>
            <p className="text-sm text-slate-900">{R.observed.text}</p>
          </div>
          <div data-testid="phys-dates">
            <h4 className="text-xs font-semibold uppercase tracking-wide text-slate-600">Dates: observations and forecast are kept apart</h4>
            <dl className="grid grid-cols-2 gap-1 text-xs sm:grid-cols-3">
              <div className="rounded bg-white/70 px-2 py-1"><dt className="text-[11px] text-slate-500">Latest observed SST</dt><dd className="font-semibold">{R.forecast_relationship.dates.sst_observation}</dd></div>
              <div className="rounded bg-white/70 px-2 py-1"><dt className="text-[11px] text-slate-500">Forecast issued from</dt><dd className="font-semibold">{R.forecast_relationship.dates.forecast_issued_from ?? "–"}</dd></div>
              <div className="rounded bg-white/70 px-2 py-1"><dt className="text-[11px] text-slate-500">Forecast valid</dt><dd className="font-semibold">{R.forecast_relationship.dates.forecast_valid ? `${R.forecast_relationship.dates.forecast_valid[0]} to ${R.forecast_relationship.dates.forecast_valid[1]}` : "–"}</dd></div>
              {Object.entries(R.forecast_relationship.dates.drivers).map(([k, v]) => (
                <div key={k} className="rounded bg-white/70 px-2 py-1"><dt className="text-[11px] text-slate-500">{v.label}</dt><dd className="font-semibold">{v.observation_date ?? "not available"}{v.lag_days_behind_sst != null ? ` (${v.lag_days_behind_sst === 0 ? "same day as SST" : `${v.lag_days_behind_sst} d before SST`})` : ""}</dd></div>
              ))}
            </dl>
          </div>
          <div data-testid="phys-evidence">
            <h4 className="text-xs font-semibold uppercase tracking-wide text-slate-600">2. Physical environmental evidence</h4>
            <div className="overflow-x-auto"><table className="w-full text-left text-xs"><caption className="sr-only">Measured and derived environmental indicators with units and dates</caption>
              <thead className="text-slate-500"><tr><th scope="col" className="pr-2">Indicator</th><th scope="col" className="pr-2 text-right">Value</th><th scope="col" className="pr-2">Unit</th><th scope="col" className="pr-2">Period</th><th scope="col">Type</th></tr></thead>
              <tbody>{R.mechanisms.flatMap((m) => m.data.map((d) => (
                <tr key={`${m.id}-${d.label}`} className="border-t border-slate-100"><td className="pr-2">{d.label}</td><td className="pr-2 text-right tabular-nums font-semibold">{fmtValue(d)}</td><td className="pr-2">{d.unit}</td><td className="pr-2">{d.period}</td><td>{d.kind}</td></tr>
              )))}</tbody></table></div>
          </div>
          {R.series && (
            <div data-testid="phys-charts">
              <h4 className="text-xs font-semibold uppercase tracking-wide text-slate-600">Recent SST anomaly alongside the measured indicators (gaps are missing days, not zeros)</h4>
              <div className="grid grid-cols-1 gap-2 sm:grid-cols-3">
                <MiniSeries title="SST anomaly" unit="°C" dates={R.series.dates} values={R.series.sst_anomaly_c} tone="#0f766e" />
                <MiniSeries title="Wind speed" unit="m/s" dates={R.series.dates} values={R.series.wind_speed_ms} tone="#2563eb" />
                <MiniSeries title="Sea level anomaly" unit="m" dates={R.series.dates} values={R.series.sea_level_anomaly_m} tone="#7c3aed" />
              </div>
            </div>
          )}
          <div data-testid="phys-mechanisms">
            <h4 className="text-xs font-semibold uppercase tracking-wide text-slate-600">3–4. Possible mechanisms, with evidence for and against</h4>
            <ul className="space-y-2">{R.mechanisms.filter((m) => !(m.id === "advection" && m.verdict === "not assessable")).map((m) => <Mechanism key={m.id} m={m} />)}</ul>
          </div>
          <div data-testid="phys-forecast">
            <h4 className="text-xs font-semibold uppercase tracking-wide text-slate-600">5. How the physical context compares with the ConvLSTM forecast</h4>
            {R.forecast_relationship.agreement && <p className="text-xs"><span className="rounded bg-sky-100 px-2 py-0.5 font-semibold text-sky-900">Directional agreement: {R.forecast_relationship.agreement}</span></p>}
            <ul className="mt-1 list-disc space-y-0.5 pl-5 text-xs text-slate-800">{R.forecast_relationship.statements.map((t) => <li key={t}>{t}</li>)}</ul>
          </div>
          <div data-testid="phys-confidence" className="rounded-md bg-white/70 p-2 ring-1 ring-slate-200">
            <h4 className="text-xs font-semibold uppercase tracking-wide text-slate-600">Confidence and limitations</h4>
            <p className="text-sm text-slate-900"><strong>Evidence: {R.confidence.level}.</strong> {R.confidence.text} <strong>{R.confidence.attribution}</strong></p>
            <ul className="mt-1 list-disc pl-5 text-xs text-slate-700">{R.limitations?.map((t) => <li key={t}>{t}</li>)}</ul>
          </div>
          <div data-testid="phys-sources">
            <h4 className="text-xs font-semibold uppercase tracking-wide text-slate-600">6. Data sources, timestamps and limitations</h4>
            <div className="overflow-x-auto"><table className="w-full text-left text-xs"><caption className="sr-only">Sources of the physical indicators</caption>
              <thead className="text-slate-500"><tr><th scope="col" className="pr-2">Indicator</th><th scope="col" className="pr-2">Source and dataset</th><th scope="col" className="pr-2">Resolution</th><th scope="col" className="pr-2">Latest day used</th><th scope="col">Status</th></tr></thead>
              <tbody>{R.sources?.map((s) => (
                <tr key={s.id} className="border-t border-slate-100 align-top" data-source={s.id}><td className="pr-2 font-medium">{s.label}</td><td className="pr-2">{s.source ?? "–"}{s.dataset ? <div className="text-[10px] text-slate-500">{s.dataset}</div> : null}{s.kind ? <div className="text-[10px] text-slate-500">{s.kind}</div> : null}</td>
                  <td className="pr-2">{[s.spatial_resolution, s.temporal_resolution].filter(Boolean).join(" · ") || "–"}</td><td className="pr-2">{s.used_through ?? s.dataset_end ?? "–"}{s.used_through && s.dataset_end && s.used_through !== s.dataset_end ? <div className="text-[10px] text-slate-500">source runs to {s.dataset_end}</div> : null}{s.lag_days_behind_sst != null ? <div className="text-[10px] text-slate-500">{s.lag_days_behind_sst} d before the SST date</div> : null}</td>
                  <td><span className={`rounded px-1.5 py-0.5 text-[11px] font-semibold ${s.status === "ok" ? "bg-emerald-100 text-emerald-900" : s.status === "stale" ? "bg-amber-100 text-amber-900" : "bg-slate-200 text-slate-800"}`}>{s.status === "no_data" ? "no data here" : s.status}</span>{s.message ? <div className="text-[10px] text-slate-500">{s.message}</div> : null}</td></tr>
              ))}</tbody></table></div>
            <details className="mt-1 rounded bg-white/60 p-2"><summary className="cursor-pointer text-xs font-semibold text-tide">How each verdict is decided</summary><ul className="mt-1 list-disc pl-5 text-xs text-slate-700">{R.method?.map((t) => <li key={t}>{t}</li>)}</ul></details>
          </div>
          </div>
        </details>
      )}
    </section>
  );
}
