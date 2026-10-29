import type { PhysicalInterpretation, PhysicalInterpretationMechanism } from "../api/environment";

const SUPPORT: Record<string, { label: string; tone: string; hint: string }> = {
  local_measurements: { label: "Local measurements", tone: "bg-emerald-100 text-emerald-900", hint: "Measured at or near this place and consistent with the anomaly" },
  local_estimate: { label: "Estimate from local data", tone: "bg-teal-100 text-teal-900", hint: "A derived estimate that has not been validated against measured fluxes" },
  climate_context: { label: "Climate context", tone: "bg-sky-100 text-sky-900", hint: "A basin-scale climate index, not a local measurement" },
  climatology: { label: "Normal seasonal cycle", tone: "bg-slate-200 text-slate-800", hint: "From the long-term average for this date" },
  general_context: { label: "General scientific context", tone: "bg-amber-100 text-amber-900", hint: "General knowledge; not detected or measured here" },
};
const LEVEL: Record<string, { label: string; tone: string }> = {
  moderate: { label: "Moderate", tone: "bg-emerald-100 text-emerald-900" }, low: { label: "Low", tone: "bg-amber-100 text-amber-900" },
  mixed: { label: "Mixed", tone: "bg-orange-100 text-orange-900" }, "not applicable": { label: "Not applicable", tone: "bg-slate-200 text-slate-800" },
};
const signedLabel = /anomaly|departure|trend|tendency|change|\(\+ =/i;
const fmt = (label: string, v: number | string) => {
  if (typeof v !== "number") return v;
  const dec = Math.abs(v) < 1 ? 2 : Math.abs(v) < 100 ? 1 : 0;
  return signedLabel.test(label) ? `${v > 0 ? "+" : ""}${v.toFixed(dec)}` : v.toFixed(dec);
};

function Driver({ m, rank }: { m: PhysicalInterpretationMechanism; rank: number }) {
  const s = SUPPORT[m.support] ?? SUPPORT.general_context;
  return (
    <li className="rounded-md bg-white/80 p-2 ring-1 ring-slate-200" data-testid="interp-mechanism" data-mechanism={m.id} data-support={m.support}>
      <div className="flex flex-wrap items-center gap-2">
        <span className="text-sm font-semibold text-slate-900">{rank}. {m.name}</span>
        <span className={`rounded px-1.5 py-0.5 text-[11px] font-semibold ${s.tone}`} title={s.hint} data-testid="interp-support">{s.label}</span>
      </div>
      <p className="mt-1 text-sm text-slate-800">{m.explanation}</p>
      {m.evidence.length > 0 && <ul className="mt-1 list-disc space-y-0.5 pl-5 text-xs text-slate-800" data-testid="interp-evidence">{m.evidence.map((t) => <li key={t}>{t}</li>)}</ul>}
      {m.complications.length > 0 && (
        <details className="mt-1"><summary className="cursor-pointer text-xs font-semibold text-slate-700">What complicates or limits this ({m.complications.length})</summary>
          <ul className="mt-1 list-disc space-y-0.5 pl-5 text-xs text-slate-700" data-testid="interp-complications">{m.complications.map((t) => <li key={t}>{t}</li>)}</ul></details>
      )}
    </li>
  );
}

/** The answer first: why this place is warmer or cooler than normal, the leading mechanisms with their measurements, what may happen next, and how sure the evidence allows us to be. */
export default function PhysicalInterpretationView({ I }: { I: PhysicalInterpretation }) {
  const lv = LEVEL[I.confidence.level] ?? LEVEL.low;
  const ai = I.provider.ai_generated;
  return (
    <div className="space-y-3" data-testid="interp">
      <div className="flex flex-wrap items-center gap-2">
        <span className={`rounded px-2 py-0.5 text-[11px] font-semibold ${ai ? "bg-violet-100 text-violet-900" : "bg-slate-100 text-slate-700"}`} title={I.provider.note} data-testid="interp-provider">
          {ai ? `AI-assisted wording (${I.provider.name})` : "Evidence-based summary"}
        </span>
        {I.provider.status === "generating" && <span role="status" className="text-[11px] text-slate-500">An AI model is writing the wording; this summary updates when it is ready.</span>}
      </div>
      <section aria-label="Why is this area warming or cooling" data-testid="interp-why">
        <h4 className="text-xs font-semibold uppercase tracking-wide text-slate-600">Why is this area warming or cooling?</h4>
        <p className="text-sm font-semibold text-slate-900" data-testid="interp-headline">{I.headline}</p>
        <p className="mt-0.5 text-sm text-slate-800" data-testid="interp-summary">{I.summary}</p>
      </section>
      <section aria-label="Likely physical drivers" data-testid="interp-drivers">
        <h4 className="text-xs font-semibold uppercase tracking-wide text-slate-600">Likely physical drivers</h4>
        {I.mechanisms.length ? <ul className="mt-1 space-y-2">{I.mechanisms.map((m, k) => <Driver key={m.id} m={m} rank={k + 1} />)}</ul>
          : <p className="text-sm text-slate-800">The measurements do not single out a leading process at this place.</p>}
      </section>
      <section aria-label="What the environmental data show" data-testid="interp-data">
        <h4 className="text-xs font-semibold uppercase tracking-wide text-slate-600">What the environmental data show</h4>
        <dl className="mt-1 grid grid-cols-2 gap-1 text-xs sm:grid-cols-3">
          {I.key_measurements.map((d) => (
            <div key={d.label} className="min-w-0 rounded bg-white/80 px-2 py-1 ring-1 ring-slate-100" data-testid="interp-measurement">
              <dt className="text-[11px] text-slate-500">{d.label}</dt>
              <dd className="font-semibold tabular-nums text-slate-900">{fmt(d.label, d.value)} <span className="font-normal text-slate-600">{d.unit}</span></dd>
              <dd className="truncate text-[10px] text-slate-500" title={`${d.period}; ${d.kind}`}>{d.period}</dd>
            </div>
          ))}
        </dl>
      </section>
      <section aria-label="What may happen next" data-testid="interp-next">
        <h4 className="text-xs font-semibold uppercase tracking-wide text-slate-600">What may happen next</h4>
        <p className="text-sm text-slate-800">{I.near_term.text}</p>
      </section>
      <section aria-label="Potential marine implications" data-testid="interp-implications">
        <h4 className="text-xs font-semibold uppercase tracking-wide text-slate-600">Potential marine implications</h4>
        {I.implications.measured.length > 0 && (<><div className="mt-1 text-[11px] font-semibold uppercase text-emerald-900">Measured here</div>
          <ul className="list-disc space-y-0.5 pl-5 text-xs text-slate-800" data-testid="interp-measured">{I.implications.measured.map((t) => <li key={t}>{t}</li>)}</ul></>)}
        {I.implications.general.length > 0 && (<><div className="mt-1 text-[11px] font-semibold uppercase text-amber-900">General scientific context: not observed here</div>
          <ul className="list-disc space-y-0.5 pl-5 text-xs text-slate-800" data-testid="interp-general">{I.implications.general.map((t) => <li key={t}>{t}</li>)}</ul></>)}
      </section>
      <section aria-label="Confidence" className="rounded-md bg-white/80 p-2 ring-1 ring-slate-200" data-testid="interp-confidence">
        <h4 className="text-xs font-semibold uppercase tracking-wide text-slate-600">Confidence in the physical interpretation</h4>
        <p className="mt-0.5 text-sm text-slate-900"><span className={`mr-1 rounded px-1.5 py-0.5 text-[11px] font-semibold ${lv.tone}`} data-testid="interp-level">{lv.label}</span>{I.confidence.justification}</p>
        <ul className="mt-1 space-y-0.5 text-xs text-slate-700" data-testid="interp-criteria">
          {I.confidence.criteria.map((c) => <li key={c.text}><span aria-hidden="true" className="mr-1 font-bold">{c.met ? "✓" : "–"}</span><span className="sr-only">{c.met ? "Met: " : "Not met: "}</span>{c.text}</li>)}
        </ul>
        <p className="mt-1 text-[11px] text-slate-500">Confidence describes how well independent measurements agree with the anomaly. It is not a probability, and it is not a causal attribution.</p>
      </section>
    </div>
  );
}
