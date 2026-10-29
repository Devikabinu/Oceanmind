import { useEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";
import { getReport, getSpeciesExposure } from "../api/environment";
import ForecastExplain, { ModelInputs, Statement } from "./ForecastExplain";
import { ContextPanel, ExposurePanel, ObisPanel, SourcesTable } from "./BiodiversityPanel";
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

const STATUS_STYLE: Record<ReportDriver["status"], string> = {
  contributing: "bg-emerald-100 text-emerald-900", below_threshold: "bg-sky-100 text-sky-900", incomplete: "bg-amber-100 text-amber-900", unavailable: "bg-slate-200 text-slate-800",
};
const STATUS_LABEL: Record<ReportDriver["status"], string> = { contributing: "Active", below_threshold: "Active, low", incomplete: "Active, incomplete", unavailable: "Excluded from score" };

/** One risk driver with the whole calculation visible: the measured quantity, the 0-1 factor, its weight and what it adds to the score, and, when it is left out, which input is missing. */
function Driver({ d }: { d: ReportDriver }) {
  const bar = d.available && d.value != null ? Math.max(3, d.value * 100) : 0;
  return (
    <li className="py-1.5" data-driver={d.factor}>
      <div className="flex flex-wrap items-baseline justify-between gap-2 text-sm">
        <span className="font-medium text-slate-900">{d.label}{d.classification ? <span className="ml-2 rounded bg-slate-100 px-1.5 py-0.5 text-[11px] font-semibold text-slate-700" data-testid="classification">{d.classification}</span> : null}</span>
        <span className={`rounded px-1.5 py-0.5 text-[11px] font-semibold ${STATUS_STYLE[d.status]}`} title={d.status_text}>{STATUS_LABEL[d.status]}</span>
      </div>
      {d.available ? (
        <>
          <dl className="mt-0.5 grid grid-cols-2 gap-x-3 text-xs sm:grid-cols-4">
            <div><dt className="text-slate-500">Measured</dt><dd className="font-semibold text-slate-900">{d.raw == null ? "–" : `${d.factor === "persistence" || d.factor === "overlap" ? d.raw : signed(d.raw)} ${d.raw_unit}`}</dd></div>
            <div><dt className="text-slate-500">Factor (0–1)</dt><dd className="font-semibold text-slate-900">{d.value?.toFixed(2)}</dd></div>
            <div><dt className="text-slate-500">Weight</dt><dd className="font-semibold text-slate-900">{d.effective_weight != null ? d.effective_weight.toFixed(2) : d.weight.toFixed(2)}{d.effective_weight != null && Math.abs(d.effective_weight - d.weight) > 0.005 ? ` (nominal ${d.weight.toFixed(2)})` : ""}</dd></div>
            <div><dt className="text-slate-500">Contribution</dt><dd className="font-semibold text-slate-900">{d.contribution?.toFixed(2)}</dd></div>
          </dl>
          {d.normalization && <p className="mt-0.5 text-[11px] text-slate-500">Normalisation: {d.normalization}</p>}
          {d.saturated && <p className="mt-0.5 text-[11px] font-medium text-orange-800">Saturated because {({ anomaly: "the observed anomaly", persistence: "the heatwave duration", forecast: "the forecast anomaly", overlap: "the number of species" } as Record<string, string>)[d.factor] ?? "the measured value"} exceeds the scoring threshold ({d.saturation_at} {d.raw_unit}); the measured value is {d.raw} {d.raw_unit}.</p>}
          <div className="mt-1 h-2 rounded bg-slate-100" role="img" aria-label={`${d.label}: factor ${d.value?.toFixed(2)}`}>
            <div className={`h-2 rounded ${d.level === "HIGH" ? "bg-orange-600" : d.level === "MEDIUM" ? "bg-yellow-500" : "bg-green-600"}`} style={{ width: `${bar}%` }} />
          </div>
        </>
      ) : (
        <p className="mt-0.5 text-xs font-medium text-slate-700">No stored data were found for this indicator ({d.missing_input}) within the search range.</p>
      )}
      <p className="mt-0.5 text-xs text-slate-600">{d.explanation}</p>
      {d.detail_lines && d.detail_lines.length > 0 && (
        <details className="mt-0.5"><summary className="cursor-pointer text-[11px] font-semibold text-tide">What this means</summary>
          <ul className="mt-0.5 list-disc space-y-0.5 pl-5 text-xs text-slate-700">{d.detail_lines.map((t) => <li key={t}>{t}</li>)}</ul></details>
      )}
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
  // OBIS and NOAA context are fetched in the background on a cache miss: the report says so (refresh_hint_s) and is asked again, quietly, without replacing what is on screen.
  const key = `${dataset}|${point?.lat}|${point?.lon}|${date}`;
  const [fresh, setFresh] = useState<{ key: string; data: LocationReportData } | null>(null);
  const tries = useRef({ key: "", n: 0 });
  useEffect(() => {
    if (tries.current.key !== key) tries.current = { key, n: 0 };
    const cur = fresh && fresh.key === key ? fresh.data : rep.data && !rep.isLoading ? rep.data : null;
    const hint = cur?.refresh_hint_s;
    if (!point || !hint || tries.current.n >= 6) return;
    const t = setTimeout(async () => {
      tries.current.n += 1;
      try {
        setFresh({ key, data: await getReport(dataset, point.lat, point.lon, date ?? undefined) });
      } catch {
        /* the report on screen stays as it is */
      }
    }, hint * 1000);
    return () => clearTimeout(t);
  }, [rep.data, rep.isLoading, fresh, key]); // eslint-disable-line react-hooks/exhaustive-deps
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
  const raw = fresh && fresh.key === key ? fresh.data : rep.data && !rep.isLoading ? rep.data : null;
  const r: LocationReportData | null = raw && raw.query.lat === point.lat && raw.query.lon === point.lon && raw.dataset === dataset ? raw : null;
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
      <Section id="cond" title="Current conditions">
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
      <Section id="hw" title="Marine heatwave analysis" badge={hw.inside === true ? <span className="rounded bg-red-100 px-1.5 py-0.5 text-xs font-bold text-red-900">YES</span> : hw.inside === false ? <span className="rounded bg-slate-100 px-1.5 py-0.5 text-xs font-semibold text-slate-800">NO</span> : undefined}>
        <p className="text-sm font-medium text-slate-900">{hw.message}</p>
        {hw.analysis?.status && <p className="mt-0.5 text-xs font-semibold text-slate-700" data-testid="heatwave-status">Forecast classification: <span className="rounded bg-red-50 px-1.5 py-0.5 text-red-900 ring-1 ring-red-100">{hw.analysis.status}</span></p>}
        {hw.analysis && hw.analysis.lines.length > 0 && (
          <ul className="mt-1 list-disc space-y-0.5 pl-5 text-sm text-slate-800" data-testid="heatwave-analysis">{hw.analysis.lines.map((t) => <li key={t}>{t}</li>)}</ul>
        )}
        {hw.inside && hw.event && (
          <>
            <p className="mt-1 text-xs text-slate-600">Event {hw.event.id} · {hw.event_region}</p>
            <dl className="mt-1 grid grid-cols-2 gap-1 text-sm">
              {[["Start date", hw.event.start_date], ["Duration", `${hw.event.duration_days} days`], ["Category", hw.event.category_name], ["Cell run", `${hw.run_days} days`],
                ["Event mean anomaly (whole event today)", `${signed(hw.event.current_anomaly_c)} °C`], ["Event maximum anomaly", `${signed(hw.event.max_anomaly_c)} °C`],
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
      <Section id="species" title="Biodiversity & ecosystem context" badge={r.obis?.available && r.obis.counts ? <span className="text-xs text-slate-500">{`${r.obis.counts.distinct_species.toLocaleString()} species · ${r.obis.counts.observations.toLocaleString()} observations`}</span> : sp ? <span className="text-xs text-slate-500">{sp.counted && sp.counted.observations > 0 ? `${sp.counted.distinct_species} species · ${sp.counted.observations.toLocaleString()} observations` : "limited coverage"}</span> : undefined}>
        {r.obis?.available ? (
          <>
            <ObisPanel o={r.obis} />
            <details className="mt-2 rounded-md bg-slate-50 p-2" data-testid="stored-records">
              <summary className="cursor-pointer text-xs font-semibold text-slate-700">Stored project records (the selection the risk score uses)</summary>
        <p className="text-xs font-medium text-slate-800" data-testid="stored-species-counted">{sp?.counted?.label ?? "No stored biodiversity observations for this location and time period (a sampling gap, not absence)."}</p>
        <p className="text-xs text-slate-600">{sp?.summary}</p>
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
            </details>
          </>
        ) : (
          <>
            {r.obis?.status === "refreshing" && <p role="status" className="mb-1 text-xs text-slate-600">Retrieving the latest OBIS records for this area; the stored project records are shown meanwhile.</p>}
        <p className="text-xs font-medium text-slate-800" data-testid="species-counted">{sp?.counted?.label ?? "No stored biodiversity observations for this location and time period (a sampling gap, not absence)."}</p>
        <p className="text-xs text-slate-600">{sp?.summary}</p>
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
          </>
        )}
      </Section>
      <Section id="context" title="Ecological and physical context" badge={r.context?.status === "refreshing" ? <span className="text-xs text-slate-500">retrieving…</span> : undefined}>
        <ContextPanel ctx={r.context} />
      </Section>
      <Section id="forecast" title="7-day forecast" badge={f?.available && f.direction ? <span className="rounded bg-blue-100 px-1.5 py-0.5 text-xs font-semibold text-blue-900">{f.direction}</span> : undefined}>
        {!f?.available ? (
          <p className="text-sm text-slate-700">{f?.message ?? "No forecast for this location."}</p>
        ) : (
          <>
            <p className="text-sm font-medium text-slate-900" data-testid="forecast-reading">{f.reading?.text ?? f.summary}</p>
            {r.analysis?.trends && <p className="text-xs text-slate-600" data-testid="recent-trends">Recent trend (observed, {r.analysis.trends.from} to {r.analysis.trends.to}): SST {signed(r.analysis.trends.sst_3d_c_per_day, 2)} °C/day over 3 days and {signed(r.analysis.trends.sst_7d_c_per_day, 2)} °C/day over {r.analysis.trends.days} days; anomaly {signed(r.analysis.trends.anomaly_3d_change_c, 2)} °C over 3 days and {signed(r.analysis.trends.anomaly_7d_change_c, 2)} °C over {r.analysis.trends.days} days.</p>}
            {f.reading && <p className="text-xs text-slate-600">Maximum predicted |anomaly| {f.reading.max_abs_anomaly_c.toFixed(1)} °C · mean {signed(f.reading.mean_anomaly_c)} °C · anomaly {f.reading.anomaly_label} · SST change over the forecast {signed(f.reading.sst_change_c, 2)} °C. Model prediction, not an observation.</p>}
            {f.interpretation && <ul className="mt-1 list-disc space-y-0.5 pl-5 text-xs text-slate-700">{f.interpretation.map((t) => <li key={t}>{t}</li>)}</ul>}
            <div className="mt-1 overflow-x-auto">
              <table className="w-full text-left text-xs">
                <caption className="sr-only">Forecast at this location</caption>
                <thead className="text-slate-500"><tr><th scope="col" className="pr-2">Date</th><th scope="col" className="pr-2">Predicted SST °C</th><th scope="col" className="pr-2">Predicted anomaly °C</th><th scope="col" className="pr-2">Change from latest °C</th><th scope="col" className="pr-2">Direction</th><th scope="col" className="pr-2">Persistence °C</th><th scope="col" className="pr-2">Difference °C</th><th scope="col">Typical error</th></tr></thead>
                <tbody>
                  {f.dates?.map((d, i) => (
                    <tr key={d} className="border-t border-slate-100"><td className="pr-2">{d.slice(5)}</td><td className="pr-2">{f.forecast_sst?.[i].toFixed(1)}</td><td className="pr-2">{signed(f.forecast_anomaly?.[i])}</td><td className="pr-2">{signed(f.change_vs_latest_c?.[i], 2)}</td><td className="pr-2">{f.direction_by_day?.[i] ?? "–"}</td><td className="pr-2 text-slate-500">{f.persistence_sst?.[i]?.toFixed(1) ?? "–"}</td><td className="pr-2">{f.persistence_sst?.[i] != null && f.forecast_sst ? signed(f.forecast_sst[i] - f.persistence_sst[i]) : "–"}</td><td>{f.typical_error_c ? `±${f.typical_error_c[i].toFixed(2)}` : "n/a"}</td></tr>
                  ))}
                </tbody>
              </table>
            </div>
            {r.analysis?.why_forecast && (
              <details className="mt-2 rounded-md bg-sky-50/70 p-2 text-sm ring-1 ring-sky-100" open data-testid="why-forecast">
                <summary className="cursor-pointer text-xs font-semibold text-sky-900">{r.analysis.why_forecast.headline}</summary>
                <ul className="mt-1">{r.analysis.why_forecast.bullets.map((b) => <Statement key={b.text} s={b} />)}</ul>
              </details>
            )}
            <p className="mt-1 text-xs text-slate-500">{f.model}, issued from {f.issued_from}{f.trained_on ? `; weights trained on ${f.trained_on}` : ""}{f.beats_persistence === false ? "; did not beat persistence at every horizon on this dataset" : ""}.</p>
          </>
        )}
      </Section>
      {f?.available && (
        <Section id="xai" title="Explainable AI: why this forecast">
          <p className="mb-1 rounded bg-violet-50 px-2 py-1 text-xs font-semibold text-violet-900">Model-based sensitivity explanation: not causal attribution.</p>
          <ForecastExplain dataset={dataset} lat={r.cell?.lat ?? point.lat} lon={r.cell?.lon_180 ?? point.lon} quick={f?.available ? (f as never) : null} risk={{ driver: k?.drivers?.find((d) => d.factor === "forecast"), score: k?.score, level: k?.level }} />
        </Section>
      )}
      <Section id="exposure" title="Potential exposure">
        {r.obis?.available ? <ExposurePanel o={r.obis} /> : (
          <p className="text-sm text-slate-700" data-testid="exposure-fallback">
            {sp && sp.items.some((s) => (s.records_in_heatwave ?? 0) > 0)
              ? `${sp.items.filter((s) => (s.records_in_heatwave ?? 0) > 0).length} species with stored OBIS records near this place have records inside the current marine-heatwave footprint. These records indicate potential exposure to the observed thermal conditions, not biological damage.`
              : "The recorded places of nearby species are compared with the marine-heatwave footprint and the predicted anomaly area as soon as OBIS records are available for this area."}
          </p>
        )}
      </Section>
      <Section id="implications" title="Potential environmental implications">
        <details open className="rounded-md bg-lime-50/70 p-2 text-sm ring-1 ring-lime-100">
          <summary className="cursor-pointer text-xs font-semibold text-lime-900">What these conditions may mean for marine ecosystems</summary>
          {r.implications?.available ? (
            <>
              <ul className="mt-1">{r.implications.items.map((s) => <Statement key={s.text} s={s} />)}</ul>
              <p className="mt-1 text-xs text-slate-700">{r.implications.caveat}</p>
            </>
          ) : <p className="mt-1 text-xs text-slate-700">{r.implications?.message ?? "No implications are drawn without an SST anomaly."}</p>}
        </details>
      </Section>
      <Section id="risk" title="Risk assessment" badge={k?.level ? <SeverityBadge level={k.level} /> : undefined}>
        {!k || k.score == null ? (
          <p className="text-sm text-slate-800">{k?.message ?? "A risk level could not be calculated here because the SST anomaly it needs is not available for this cell and date. This is not low risk."}</p>
        ) : (
          <>
            <div className="flex items-baseline gap-3"><span className="text-2xl font-semibold text-slate-900">{k.score.toFixed(2)}</span><span className="text-xs text-slate-500">of 1 · evidence completeness {k.evidence_completeness != null ? `${Math.round(k.evidence_completeness * 100)}%` : "n/a"}</span></div>
            <p className="mt-1 text-xs text-slate-700" data-testid="indicators-used">Risk based on {k.drivers?.filter((d) => d.available).length ?? 0} available indicator{k.drivers?.filter((d) => d.available).length === 1 ? "" : "s"}: {k.drivers?.filter((d) => d.available).map((d) => d.label).join(", ")}.</p>
            <details className="mt-1 rounded-md bg-slate-50 p-2" open>
              <summary className="cursor-pointer text-xs font-semibold uppercase tracking-wide text-slate-700">Why this risk? Drivers and their contributions</summary>
              <ul className="divide-y divide-slate-100">{k.drivers?.filter((d) => d.available).map((d) => <Driver key={d.factor} d={d} />)}</ul>
              {k.score_breakdown?.text && (
                <p className="mt-1 rounded bg-white px-2 py-1 text-xs text-slate-800" data-testid="score-sum">
                  Final score: <strong>{k.score_breakdown.text}</strong> → {k.level === "MEDIUM" ? "MODERATE" : k.level}. {k.drivers?.some((d) => d.saturated) ? "A factor “saturated at the scoring threshold” has reached the top of its 0–1 scale because the measured value is at or beyond the level where the factor stops increasing; it is a measurement, not a default, and not a statement that the physical value is 100%. " : ""}
                  Bands: below 0.25 LOW, 0.25–0.5 MODERATE, 0.5–0.75 HIGH, 0.75 and above CRITICAL.
                </p>
              )}
            </details>
          </>
        )}
      </Section>
      {k && k.score != null && (
        <Section id="why" title="Why this risk level">
          <p className="text-sm text-slate-800" data-testid="risk-why">
            {k.level === "MEDIUM" ? "MODERATE" : k.level} ({k.score.toFixed(2)}): {[...(k.drivers ?? [])].filter((d) => d.available && d.contribution != null).sort((x, y) => (y.contribution ?? 0) - (x.contribution ?? 0)).map((d) => `${d.label} ${d.raw == null ? "" : `${d.factor === "persistence" || d.factor === "overlap" ? d.raw : signed(d.raw)} ${d.raw_unit}`} adds ${d.contribution?.toFixed(2)}`).join("; ")}.
          </p>
            {k.drivers?.some((d) => !d.available) && (
              <details className="mt-1 rounded-md bg-slate-50 p-2" data-testid="data-details">
                <summary className="cursor-pointer text-xs font-semibold text-slate-700">Data details: {k.drivers.filter((d) => !d.available).length} indicator{k.drivers.filter((d) => !d.available).length === 1 ? "" : "s"} excluded from the score</summary>
                <p className="mt-1 text-xs text-slate-600">No stored data were found for this indicator even after widening the search. The score is renormalised over the available indicators (never counted as zero or as one); biodiversity coverage affects confidence, not whether the environmental risk can be calculated.</p>
                <ul className="divide-y divide-slate-100">{k.drivers.filter((d) => !d.available).map((d) => <Driver key={d.factor} d={d} />)}</ul>
              </details>
            )}
            {r.analysis?.risk_dominance && <p className="mt-1 text-sm text-slate-800" data-testid="risk-dominance">{r.analysis.risk_dominance}</p>}
          {k.explanation && <Explain e={k.explanation} label="Explain this risk in plain language" />}
        </Section>
      )}
      <Section id="alerts" title="Alerts" badge={<span className="text-xs text-slate-500">{r.alerts?.length ?? 0}</span>}>
        {r.alerts && r.alerts.length > 0 ? (
          <ul className="space-y-1.5">{r.alerts.map((a) => <AlertRow key={a.id} a={a} onOpen={onFocus ? () => onFocus(a.latitude, a.longitude) : undefined} />)}</ul>
        ) : (
          <p className="text-sm text-slate-700">No alert is active at or near this location.</p>
        )}
      </Section>
      <Section id="dates" title="Data & methodology" badge={r.data_dates ? <span className={`rounded px-1.5 py-0.5 text-xs font-semibold ${r.data_dates.aligned ? "bg-emerald-100 text-emerald-900" : "bg-amber-100 text-amber-900"}`}>{r.data_dates.aligned ? "same day" : "dates differ"}</span> : undefined}>
        {r.sources && r.sources.length > 0 && <div className="mb-2 rounded-md bg-slate-50 p-2 ring-1 ring-slate-200"><div className="mb-1 text-xs font-semibold text-slate-800">Data sources</div><SourcesTable rows={r.sources} /></div>}
        <details className="rounded-md bg-slate-50 p-2 text-sm ring-1 ring-slate-200" open={r.data_dates ? !r.data_dates.aligned : false}>
          <summary className="cursor-pointer text-xs font-semibold text-slate-800">Which day each product refers to</summary>
          {r.data_dates && (
            <>
              <p className="mt-1 text-xs text-slate-800">{r.data_dates.message}</p>
              <dl className="mt-1 grid grid-cols-2 gap-x-3 gap-y-0.5 text-xs">
                <dt className="text-slate-500">Latest observed SST</dt><dd className="font-semibold">{r.data_dates.sst_observation.latest_available}{r.data_dates.sst_observation.date !== r.data_dates.sst_observation.latest_available ? ` (report date ${r.data_dates.sst_observation.date})` : ""}</dd>
                <dt className="text-slate-500">Anomaly</dt><dd className="font-semibold">{r.data_dates.anomaly.date}</dd>
                <dt className="text-slate-500">Marine heatwave</dt><dd className="font-semibold">{r.data_dates.marine_heatwave.date ?? "not computed"}</dd>
                <dt className="text-slate-500">Forecast initialised from</dt><dd className="font-semibold">{r.data_dates.forecast.initialised_from ?? "no forecast"}</dd>
                <dt className="text-slate-500">Forecast valid dates</dt><dd className="font-semibold">{r.data_dates.forecast.valid_dates ? `${r.data_dates.forecast.valid_dates[0]} to ${r.data_dates.forecast.valid_dates[r.data_dates.forecast.valid_dates.length - 1]}` : "–"}</dd>
                <dt className="text-slate-500">Newest species record</dt><dd className="font-semibold">{r.data_dates.species_records.latest_record ?? "none"} (records of the last {Math.round(r.data_dates.species_records.window_days / 365)} years are used)</dd>
              </dl>
              {r.risk?.drivers?.some((d) => d.status === "unavailable") && (
                <ul className="mt-1 list-disc pl-5 text-xs text-slate-700">{r.risk.drivers.filter((d) => d.status === "unavailable").map((d) => <li key={d.factor}><strong>{d.label}:</strong> no stored data for {d.missing_input}</li>)}</ul>
              )}
            </>
          )}
        </details>
        <details className="mt-2 rounded-md bg-slate-50 p-2 text-sm ring-1 ring-slate-200">
          <summary className="cursor-pointer text-xs font-semibold text-slate-800">Model inputs</summary>
          <div className="mt-1"><ModelInputs dataset={dataset} /></div>
        </details>
      </Section>
      <div className="border-t border-slate-200 bg-slate-50 px-4 py-2 text-[11px] text-slate-500">
        <span className="font-semibold text-slate-600">Data source</span> · {providerLabel(r.provider)}{r.provider.is_observational ? " (observations)" : " (modelled dataset)"} · {r.dataset} · {r.date} ·{" "}
        <Link to="/ocean-data" className="underline">details</Link>
      </div>
    </div>,
  );
}
