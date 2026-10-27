import { Link } from "react-router-dom";
import { getReport, getSpeciesExposure } from "../api/environment";
import type { LocationReportData, ReportAlert, ReportDriver, ReportExplanation } from "../api/environment";
import { useActive } from "../contexts/ActiveSelection";
import { useAsync } from "../hooks/useAsync";
import SeverityBadge from "./SeverityBadge";
import { providerLabel } from "../utils/format";

const signed = (v: number | null | undefined, d = 1) => (v == null ? "–" : `${v > 0 ? "+" : ""}${v.toFixed(d)}`);
const lat = (v: number) => `${Math.abs(v).toFixed(2)}° ${v >= 0 ? "N" : "S"}`;
const lon = (v: number) => `${Math.abs(v).toFixed(2)}° ${v < 0 ? "W" : "E"}`;
const CONS_TONE: Record<string, string> = {
  CR: "bg-red-100 text-red-900", EN: "bg-orange-100 text-orange-900", VU: "bg-yellow-100 text-yellow-900", NT: "bg-lime-100 text-lime-900", LC: "bg-green-100 text-green-900",
};

function Section({ id, title, badge, children }: { id: string; title: string; badge?: React.ReactNode; children: React.ReactNode }) {
  return (
    <section aria-labelledby={`lr-${id}`} className="border-t border-slate-200 px-4 py-3">
      <div className="mb-1.5 flex items-center justify-between gap-2">
        <h3 id={`lr-${id}`} className="text-[11px] font-semibold uppercase tracking-[0.14em] text-tide">{title}</h3>
        {badge}
      </div>
      {children}
    </section>
  );
}

function Explain({ e, label }: { e: ReportExplanation; label: string }) {
  return (
    <details className="mt-2 rounded-md bg-teal-50/70 p-2 text-sm ring-1 ring-teal-100">
      <summary className="cursor-pointer text-xs font-semibold text-tide">{label}</summary>
      <p className="mt-1 font-medium text-slate-900">{e.headline}</p>
      {e.sections.map((s) => (
        <div key={s.id} className="mt-1.5">
          <div className="text-[11px] font-semibold uppercase tracking-wide text-slate-600">{s.title}</div>
          <p className="text-slate-800">{s.text}</p>
          {s.bullets.length > 0 && <ul className="list-disc pl-5 text-slate-700">{s.bullets.map((b) => <li key={b}>{b}</li>)}</ul>}
        </div>
      ))}
    </details>
  );
}

function Driver({ d }: { d: ReportDriver }) {
  const bar = d.available && d.value != null ? Math.max(3, d.value * 100) : 0;
  return (
    <li className="py-1.5">
      <div className="flex items-baseline justify-between gap-2 text-sm">
        <span className="font-medium text-slate-900">{d.label}</span>
        <span className={d.available ? "font-semibold text-slate-900" : "text-xs font-medium text-amber-800"}>
          {d.available ? `${d.level} · ${d.value?.toFixed(2)}${d.contribution != null ? ` → ${d.contribution.toFixed(2)} of score` : ""}` : "Insufficient evidence"}
        </span>
      </div>
      <div className="mt-1 h-2 rounded bg-slate-100" role="img" aria-label={`${d.label}: ${d.available ? `${Math.round((d.value ?? 0) * 100)} percent` : "insufficient evidence"}`}>
        {d.available && <div className={`h-2 rounded ${d.level === "HIGH" ? "bg-orange-600" : d.level === "MEDIUM" ? "bg-yellow-500" : "bg-green-600"}`} style={{ width: `${bar}%` }} />}
      </div>
      <p className="mt-0.5 text-xs text-slate-600">{d.explanation}</p>
    </li>
  );
}

function SpeciesExposureDetail({ aphiaId, dataset, date }: { aphiaId: number; dataset: string; date: string | null }) {
  const x = useAsync(() => getSpeciesExposure(aphiaId, dataset, date ?? undefined), [aphiaId, dataset, date]);
  if (x.error) return <p className="mt-1 text-xs text-amber-800">Exposure unavailable: {x.error}</p>;
  if (!x.data || x.isLoading) return <p className="mt-1 text-xs text-slate-500">Loading exposure…</p>;
  if (!x.data.available || !x.data.explanation) return <p className="mt-1 text-xs text-slate-700">{x.data.message}</p>;
  return <Explain e={x.data.explanation} label="Where it is recorded, what it is exposed to, why it matters" />;
}

function AlertRow({ a, onOpen }: { a: ReportAlert; onOpen?: () => void }) {
  return (
    <li className="rounded-md bg-white p-2 ring-1 ring-slate-200">
      <div className="flex flex-wrap items-center gap-2">
        <SeverityBadge level={a.severity} />
        <span className="text-xs font-semibold text-slate-900">{a.alert_type.replace(/_/g, " ").toLowerCase()}</span>
        <span className="ml-auto text-xs text-slate-500">{a.timestamp.slice(0, 10)}</span>
      </div>
      <p className="mt-1 text-sm text-slate-800">{a.message}</p>
      <p className="text-xs text-slate-500">{a.same_event ? "Raised for the marine heatwave at this location." : `${a.distance_km.toLocaleString()} km away`}{a.region ? ` · ${a.region}` : ""}</p>
      <details className="mt-1 text-xs">
        <summary className="cursor-pointer font-semibold text-tide">Evidence</summary>
        <dl className="mt-1 grid grid-cols-2 gap-1">
          {a.evidence_summary.map((e) => (
            <div key={e.label} className="rounded bg-slate-50 px-2 py-1"><dt className="text-slate-500">{e.label}</dt><dd className="font-semibold text-slate-900">{e.value}</dd></div>
          ))}
        </dl>
        <ul className="mt-1 list-disc pl-4 text-slate-700">{a.reasons.map((r) => <li key={r}>{r}</li>)}</ul>
        <div className="mt-1 flex gap-3">
          <Link className="font-semibold text-tide hover:underline" to={`/alerts?open=${a.id}`}>Open alert page →</Link>
          {onOpen && <button type="button" className="font-semibold text-tide hover:underline" onClick={onOpen}>Show on map</button>}
        </div>
      </details>
    </li>
  );
}

/** The ONE panel for a clicked place: conditions, anomaly, marine heatwave, ecological risk, species, forecast and alerts, all for the same cell, dataset and date. */
export default function LocationReport({ point, dataset, date, onFocus, onClose }: {
  point: { lat: number; lon: number } | null;
  dataset: string;
  date: string | null;
  onFocus?: (lat: number, lon: number) => void;
  onClose?: () => void;
}) {
  const act = useActive();
  const rep = useAsync(() => (point ? getReport(dataset, point.lat, point.lon, date ?? undefined) : Promise.resolve(null)), [point?.lat, point?.lon, dataset, date]);
  if (!point) {
    return (
      <aside aria-label="Location report" className="rounded-xl bg-white p-4 shadow-sm ring-1 ring-slate-200">
        <h2 className="text-[11px] font-semibold uppercase tracking-[0.14em] text-slate-600">Location report</h2>
        <p className="mt-2 text-sm text-slate-700">Click anywhere on the ocean, a species marker or an alert to see the conditions, anomaly, marine-heatwave status, ecological risk, species, forecast and alerts for that place on the selected date.</p>
      </aside>
    );
  }
  const title = `${lat(point.lat)} · ${lon(point.lon)}`;
  const shell = (body: React.ReactNode) => (
    <aside aria-label="Location report" className="overflow-hidden rounded-xl bg-white shadow-sm ring-1 ring-slate-200">
      <div className="on-deep flex items-start justify-between gap-2 bg-gradient-to-r from-deep to-tide px-4 py-2.5 text-white">
        <div>
          <div className="text-[11px] font-semibold uppercase tracking-[0.14em] text-cyan-100/90">Location report</div>
          <div className="text-lg font-semibold tabular-nums">{title}</div>
        </div>
        {onClose && <button type="button" onClick={onClose} className="rounded border border-white/30 px-2 py-0.5 text-xs hover:bg-white/10" aria-label="Close the location report">Close</button>}
      </div>
      {body}
    </aside>
  );
  if (rep.error) return shell(<p role="alert" className="px-4 py-3 text-sm text-amber-900">Location report unavailable: {rep.error}</p>);
  const r: LocationReportData | null = rep.data && !rep.isLoading && rep.data.query.lat === point.lat && rep.data.query.lon === point.lon && rep.data.dataset === dataset ? rep.data : null;
  if (!r) return shell(<p role="status" className="px-4 py-3 text-sm text-slate-600">Loading the report for this location…</p>);

  const cell = r.cell;
  const loc = (
    <Section id="loc" title="Location">
      <dl className="grid grid-cols-2 gap-x-3 gap-y-0.5 text-sm">
        <dt className="text-slate-500">Latitude / longitude</dt><dd className="font-medium">{lat(point.lat)}, {lon(point.lon)}</dd>
        {cell && (<><dt className="text-slate-500">Grid cell</dt><dd className="font-medium">{lat(cell.lat)}, {lon(cell.lon_180)}</dd></>)}
        {r.region && (<><dt className="text-slate-500">Region</dt><dd className="font-medium">{r.region.name}</dd></>)}
        <dt className="text-slate-500">Date</dt><dd className="font-medium">{r.date}{r.date !== r.latest_available_date ? ` (latest ${r.latest_available_date})` : " (latest available)"}</dd>
      </dl>
    </Section>
  );
  if (r.status !== "valid") {
    return shell(
      <>
        {loc}
        <Section id="status" title={r.status === "land" ? "Land" : r.status === "missing" ? "No data for this cell" : "Outside the dataset"}>
          <p className="text-sm text-slate-800">{r.message}</p>
        </Section>
      </>,
    );
  }
  const c = r.conditions!;
  const a = r.anomaly!;
  const hw = r.heatwave!;
  const k = r.risk;
  const sp = r.species;
  const f = r.forecast;
  const warm = (c.anomaly ?? 0) > 0.5;
  const cold = (c.anomaly ?? 0) < -0.5;
  return shell(
    <div className="xl:max-h-[calc(100vh-14rem)] xl:overflow-y-auto">
      {loc}
      <Section id="cond" title="Ocean conditions">
        <div className="flex items-baseline gap-4">
          <div><div className="text-3xl font-semibold tracking-tight text-slate-900">{c.sst?.toFixed(1)} °C</div><div className="text-xs text-slate-500">sea surface temperature</div></div>
          <div><div className="text-lg font-semibold text-slate-700">{c.normal_sst == null ? "–" : `${c.normal_sst.toFixed(1)} °C`}</div><div className="text-xs text-slate-500">normal for this day</div></div>
        </div>
      </Section>
      <Section id="anom" title="Anomaly" badge={<span className={`rounded px-1.5 py-0.5 text-xs font-semibold ${warm ? "bg-orange-100 text-orange-900" : cold ? "bg-sky-100 text-sky-900" : "bg-slate-100 text-slate-800"}`}>{a.class ?? "n/a"}</span>}>
        <div className={`text-2xl font-semibold tracking-tight ${warm ? "text-orange-700" : cold ? "text-sky-800" : "text-slate-900"}`}>
          {signed(c.anomaly)} °C <span className="text-sm font-medium">{warm ? "warmer than normal" : cold ? "colder than normal" : "near normal"}</span>
        </div>
        <p className="text-xs text-slate-600">current {c.sst?.toFixed(1)} − normal {c.normal_sst?.toFixed(1)} = {signed(c.anomaly)} °C{a.region_percentile != null ? ` · ${warm || !cold ? "warmer" : "colder"} than ${warm || !cold ? a.region_percentile.toFixed(0) : (100 - a.region_percentile).toFixed(0)}% of ocean cells in the ${r.region?.name}` : ""}</p>
        {a.historical_percentile != null && (
          <p className="mt-0.5 text-xs text-slate-600">Historical context: {c.anomaly != null && c.anomaly >= 0 ? "warmer" : "colder"} than {(c.anomaly != null && c.anomaly >= 0 ? a.historical_percentile : 100 - a.historical_percentile).toFixed(0)}% of {a.historical_samples?.toLocaleString()} same-season anomalies at this cell.</p>
        )}
        <Explain e={a.explanation} label="What is this anomaly, how unusual is it, and why?" />
      </Section>
      <Section id="hw" title="Marine heatwave" badge={hw.inside === true ? <span className="rounded bg-red-100 px-1.5 py-0.5 text-xs font-bold text-red-900">YES</span> : hw.inside === false ? <span className="rounded bg-slate-100 px-1.5 py-0.5 text-xs font-semibold text-slate-800">NO</span> : undefined}>
        <p className="text-sm font-medium text-slate-900">{hw.message}</p>
        {hw.inside && hw.event && (
          <>
            <p className="mt-1 text-xs text-slate-600">Event {hw.event.id} · {hw.event_region}</p>
            <dl className="mt-1 grid grid-cols-2 gap-1 text-sm">
              {[["Start date", hw.event.start_date], ["Duration", `${hw.event.duration_days} days`], ["Category", hw.event.category_name], ["Cell run", `${hw.run_days} days`],
                ["Current anomaly", `${signed(hw.event.current_anomaly_c)} °C`], ["Maximum anomaly", `${signed(hw.event.max_anomaly_c)} °C`],
                ["Cumulative intensity", hw.event.cumulative_intensity_c_days != null ? `${hw.event.cumulative_intensity_c_days.toFixed(0)} °C·days` : "–"], ["Affected area", `${Math.round(hw.event.area_km2).toLocaleString()} km²`]].map(([l, v]) => (
                <div key={l} className="rounded bg-slate-50 px-2 py-1"><dt className="text-xs text-slate-500">{l}</dt><dd className="font-semibold text-slate-900">{v}</dd></div>
              ))}
            </dl>
            {hw.event.ecological_relationship && <p className="mt-1 text-xs text-slate-800"><strong>Ecological relationship:</strong> {hw.event.ecological_relationship}</p>}
            {hw.event.affected_species && hw.event.affected_species.length > 0 && (
              <p className="mt-1 text-xs text-slate-800"><strong>Species with records in the event area:</strong> {hw.event.affected_species.map((s) => `${s.common_name ?? s.scientific_name} (${s.conservation_status}, ${s.n_records} record${s.n_records === 1 ? "" : "s"})`).join(", ")}.</p>
            )}
            <p className="mt-1 text-xs text-slate-700"><strong>Why it matters:</strong> {hw.why_it_matters}</p>
            <Link to={`/heatwaves${act.toQuery({ event: hw.event.id, lat: undefined })}`} className="mt-1 inline-block text-xs font-semibold text-tide hover:underline">Event details and footprint →</Link>
          </>
        )}
      </Section>
      <Section id="risk" title="Ecological risk" badge={k?.level ? <SeverityBadge level={k.level} /> : undefined}>
        {!k || k.score == null ? (
          <p className="text-sm text-slate-800">{k?.message ?? "Insufficient evidence: no risk level can be given here. This is not low risk."}</p>
        ) : (
          <>
            <div className="flex items-baseline gap-3"><span className="text-2xl font-semibold text-slate-900">{k.score.toFixed(2)}</span><span className="text-xs text-slate-500">of 1 · evidence completeness {k.evidence_completeness != null ? `${Math.round(k.evidence_completeness * 100)}%` : "n/a"}</span></div>
            {k.evidence_completeness != null && k.evidence_completeness < 1 && (
              <p className="mt-1 rounded bg-slate-50 px-2 py-1 text-xs text-slate-700">Some drivers have insufficient evidence. They are left out of the score and the remaining weights are rescaled; a missing driver is never counted as zero.</p>
            )}
            <p className="mt-1 text-xs font-semibold uppercase tracking-wide text-slate-600">Why this level: risk drivers</p>
            <ul className="divide-y divide-slate-100">{k.drivers?.map((d) => <Driver key={d.factor} d={d} />)}</ul>
            {k.explanation && <Explain e={k.explanation} label="Explain this risk in plain language" />}
          </>
        )}
      </Section>
      <Section id="species" title="Species" badge={sp ? <span className="text-xs text-slate-500">{sp.items.length} nearby</span> : undefined}>
        <p className="text-xs text-slate-700">{sp?.summary}</p>
        <ul className="mt-1 space-y-1.5">
          {sp?.items.map((s) => (
            <li key={`${s.aphia_id}-${s.scientific_name}`} className="rounded-md bg-slate-50 p-2 text-sm">
              <div className="flex flex-wrap items-center gap-2">
                <span className="font-semibold text-slate-900">{s.common_name ?? s.scientific_name}</span>
                <span className={`rounded px-1.5 py-0.5 text-[11px] font-semibold ${CONS_TONE[s.conservation_status] ?? "bg-slate-200 text-slate-800"}`}>{s.conservation_status}</span>
              </div>
              <div className="text-xs italic text-slate-500">{s.scientific_name}{s.taxon_group ? ` · ${s.taxon_group}` : ""}</div>
              <div className="text-xs text-slate-700">
                {s.n_records} record{s.n_records === 1 ? "" : "s"}, nearest {s.nearest_km.toLocaleString()} km, latest {s.latest_record} · {s.source}
                {s.conservation_source ? ` · status: ${s.conservation_source}` : ""}
              </div>
              <div className="text-xs font-medium text-slate-800">
                {s.records_in_heatwave != null && s.records_in_heatwave > 0 ? `Exposed: ${s.records_in_heatwave} record(s) inside a current marine heatwave. ` : s.records_in_heatwave === 0 ? "No records inside a current marine heatwave. " : ""}
                {s.highest_risk_level ? `Records lie in cells up to ${s.highest_risk_level} ecological risk.` : ""}
              </div>
              {s.aphia_id && (
                <details className="mt-1">
                  <summary className="cursor-pointer text-xs font-semibold text-tide">Exposure of this species</summary>
                  <SpeciesExposureDetail aphiaId={s.aphia_id} dataset={dataset} date={date} />
                  <Link to={`/species/${s.aphia_id}${act.toQuery()}`} className="text-xs font-semibold text-tide hover:underline">Species page →</Link>
                </details>
              )}
            </li>
          ))}
        </ul>
      </Section>
      <Section id="forecast" title="Forecast" badge={f?.available && f.direction ? <span className="rounded bg-blue-100 px-1.5 py-0.5 text-xs font-semibold text-blue-900">{f.direction}</span> : undefined}>
        {!f?.available ? (
          <p className="text-sm text-slate-700">{f?.message ?? "No forecast for this location."}</p>
        ) : (
          <>
            <p className="text-sm text-slate-800">{f.summary}</p>
            {f.interpretation && <ul className="mt-1 list-disc space-y-0.5 pl-5 text-xs text-slate-700">{f.interpretation.map((t) => <li key={t}>{t}</li>)}</ul>}
            <div className="mt-1 overflow-x-auto">
              <table className="w-full text-left text-xs">
                <caption className="sr-only">Forecast at this location</caption>
                <thead className="text-slate-500"><tr><th scope="col" className="pr-2">Date</th><th scope="col" className="pr-2">SST °C</th><th scope="col" className="pr-2">Anomaly °C</th><th scope="col" className="pr-2">Persistence °C</th><th scope="col">Typical error</th></tr></thead>
                <tbody>
                  {f.dates?.map((d, i) => (
                    <tr key={d} className="border-t border-slate-100"><td className="pr-2">{d.slice(5)}</td><td className="pr-2">{f.forecast_sst?.[i].toFixed(1)}</td><td className="pr-2">{signed(f.forecast_anomaly?.[i])}</td><td className="pr-2 text-slate-500">{f.persistence_sst?.[i]?.toFixed(1) ?? "–"}</td><td>{f.typical_error_c ? `±${f.typical_error_c[i].toFixed(2)}` : "n/a"}</td></tr>
                  ))}
                </tbody>
              </table>
            </div>
            <p className="mt-1 text-xs text-slate-500">{f.model}, issued from {f.issued_from}{f.trained_on ? `; weights trained on ${f.trained_on}` : ""}{f.beats_persistence === false ? "; did not beat persistence at every horizon on this dataset" : ""}.</p>
          </>
        )}
      </Section>
      <Section id="alerts" title="Alerts" badge={<span className="text-xs text-slate-500">{r.alerts?.length ?? 0}</span>}>
        {r.alerts && r.alerts.length > 0 ? (
          <ul className="space-y-1.5">{r.alerts.map((a) => <AlertRow key={a.id} a={a} onOpen={onFocus ? () => onFocus(a.latitude, a.longitude) : undefined} />)}</ul>
        ) : (
          <p className="text-sm text-slate-700">No alert is active at or near this location.</p>
        )}
      </Section>
      <div className="border-t border-slate-200 bg-slate-50 px-4 py-2 text-[11px] text-slate-500">
        <span className="font-semibold text-slate-600">Data source</span> · {providerLabel(r.provider)}{r.provider.is_observational ? " (observations)" : " (modelled dataset)"} · {r.dataset} · {r.date} ·{" "}
        <Link to="/ocean-data" className="underline">details</Link>
      </div>
    </div>,
  );
}
