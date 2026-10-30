import { useEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";
import { getReport, getSpeciesExposure } from "../api/environment";
import ForecastExplain, { ModelInputs, Statement } from "./ForecastExplain";
import { ContextPanel, ExposurePanel, ObisPanel, SourcesTable } from "./BiodiversityPanel";
import type { LocationReportData, ReportAlert, ReportDriver, ReportExplanation } from "../api/environment";
import { BarMeter, CategoryScale, Card, MetricTile, ScaleTrack, Segmented, TabPanel, Tabs, TrendChart } from "./LocationVisuals";
import type { TabDef, TrendPoint } from "./LocationVisuals";
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

const NOT_ESTABLISHED = /^not established|cannot be established|cannot be inferred/i;

function Explain({ e, label }: { e: ReportExplanation; label: string }) {
  const sections = e.sections.filter((s) => !NOT_ESTABLISHED.test(s.title) && !NOT_ESTABLISHED.test(s.text)).map((s) => ({ ...s, bullets: s.bullets.filter((b) => !NOT_ESTABLISHED.test(b)) }));
  return (
    <details className="mt-2 rounded-md bg-teal-50/70 p-2 text-sm ring-1 ring-teal-100">
      <summary className="cursor-pointer text-xs font-semibold text-tide">{label}</summary>
      <p className="mt-1 font-medium text-slate-900">{e.headline}</p>
      {sections.map((s) => (
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

const SEVERITY_TONE = (c: number | null | undefined): "warm" | "cold" | "neutral" => ((c ?? 0) > 0.5 ? "warm" : (c ?? 0) < -0.5 ? "cold" : "neutral");
const km2 = (v: number) => (v >= 1e6 ? `${(v / 1e6).toFixed(1)} million km²` : `${Math.round(v).toLocaleString()} km²`);

type UnusualMode = "normal" | "history" | "region";

/** The ONE report for a clicked place: conditions, anomaly, marine heatwave, forecast, ecology, risk and alerts for the same cell, dataset and date, in tabs. */
export default function LocationReport({ point, dataset, date, onFocus, onClose }: {
  point: { lat: number; lon: number } | null;
  dataset: string;
  date: string | null;
  onFocus?: (lat: number, lon: number) => void;
  onClose?: () => void;
}) {
  const act = useActive();
  const rep = useAsync(() => (point ? getReport(dataset, point.lat, point.lon, date ?? undefined) : Promise.resolve(null)), [point?.lat, point?.lon, dataset, date]);
  const [tab, setTab] = useState("overview");
  const [expanded, setExpanded] = useState(false);
  const [unusual, setUnusual] = useState<UnusualMode>("normal");
  const [overviewDay, setOverviewDay] = useState<number | null>(null);
  const [forecastDay, setForecastDay] = useState<number | null>(null);
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
  useEffect(() => {
    if (!expanded) return;
    const onKey = (e: KeyboardEvent) => { if (e.key === "Escape") setExpanded(false); };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [expanded]);
  if (!point) {
    return (
      <aside aria-label="Location report" className="flex items-center gap-3 rounded-xl bg-white px-4 py-3 shadow-sm ring-1 ring-slate-200">
        <span aria-hidden className="grid h-9 w-9 shrink-0 place-items-center rounded-full bg-teal-50 text-lg text-tide ring-1 ring-teal-200">◎</span>
        <div>
          <h2 className="text-sm font-semibold text-slate-900">Location report</h2>
          <p className="text-sm text-slate-700">Click anywhere on the ocean, a species marker or an alert to see the conditions, anomaly, marine-heatwave status, ecological risk, species, forecast and alerts for that place on the selected date.</p>
        </div>
      </aside>
    );
  }
  const title = `${lat(point.lat)} · ${lon(point.lon)}`;
  const shell = (body: React.ReactNode, tabsNode?: React.ReactNode, sub?: React.ReactNode) => {
    const card = (
      <aside aria-label="Location report" className={`flex flex-col overflow-hidden rounded-xl bg-white shadow-sm ring-1 ring-slate-200 ${expanded ? "mx-auto h-full w-full max-w-7xl shadow-2xl" : "max-h-[78vh] xl:h-[calc(100vh-15rem)] xl:max-h-none xl:min-h-[28rem]"}`}>
        <div className="on-deep flex shrink-0 items-start justify-between gap-3 bg-gradient-to-r from-deep to-tide px-4 py-3 text-white">
          <div className="min-w-0">
            <div className="text-xs font-semibold uppercase tracking-[0.14em] text-cyan-100/90">Location report</div>
            <div className="text-xl font-semibold tabular-nums">{title}</div>
            {sub && <div className="mt-0.5 text-sm text-cyan-50/90">{sub}</div>}
          </div>
          <div className="flex shrink-0 gap-2">
            <button type="button" onClick={() => setExpanded((e) => !e)} aria-pressed={expanded} className="rounded-md border border-white/40 px-2.5 py-1 text-sm font-medium hover:bg-white/10">{expanded ? "Collapse" : "Expand"}</button>
            {onClose && <button type="button" onClick={() => { setExpanded(false); onClose(); }} className="rounded-md border border-white/40 px-2.5 py-1 text-sm font-medium hover:bg-white/10" aria-label="Close the location report">Close</button>}
          </div>
        </div>
        {tabsNode}
        <div className="@container min-h-0 flex-1 overflow-y-auto bg-slate-50">{body}</div>
      </aside>
    );
    return expanded ? <div className="fixed inset-0 z-[1300] bg-slate-950/60 p-2 sm:p-5">{card}</div> : card;
  };
  if (rep.error) return shell(<p role="alert" className="px-4 py-3 text-sm text-amber-900">Location report unavailable: {rep.error}</p>);
  const raw = fresh && fresh.key === key ? fresh.data : rep.data && !rep.isLoading ? rep.data : null;
  const r: LocationReportData | null = raw && raw.query.lat === point.lat && raw.query.lon === point.lon && raw.dataset === dataset ? raw : null;
  if (!r) return shell(<div role="status" className="space-y-3 p-5"><div className="h-6 w-1/3 animate-pulse rounded bg-slate-200" /><div className="grid grid-cols-2 gap-3 lg:grid-cols-4">{[0, 1, 2, 3].map((i) => <div key={i} className="h-24 animate-pulse rounded-xl bg-slate-200" />)}</div><p className="text-sm text-slate-600">Loading the report for this location…</p></div>);

  const cell = r.cell;
  const sub = [r.region?.name, cell ? `grid cell ${lat(cell.lat)}, ${lon(cell.lon_180)}` : null, `${r.date}${r.date !== r.latest_available_date ? ` (latest ${r.latest_available_date})` : " (latest available)"}`].filter(Boolean).join(" · ");
  const loc = (
    <Card title="Location">
      <dl className="grid grid-cols-2 gap-x-4 gap-y-1 text-sm @xl:grid-cols-4">
        <div><dt className="text-slate-500">Latitude / longitude</dt><dd className="font-medium">{lat(point.lat)}, {lon(point.lon)}</dd></div>
        {cell && <div><dt className="text-slate-500">Grid cell</dt><dd className="font-medium">{lat(cell.lat)}, {lon(cell.lon_180)}</dd></div>}
        {r.region && <div><dt className="text-slate-500">Region</dt><dd className="font-medium">{r.region.name}</dd></div>}
        <div><dt className="text-slate-500">Date</dt><dd className="font-medium">{r.date}{r.date !== r.latest_available_date ? ` (latest ${r.latest_available_date})` : " (latest available)"}</dd></div>
      </dl>
    </Card>
  );
  if (r.status !== "valid") {
    return shell(
      <div className="space-y-3 p-4">
        {loc}
        <Card title={r.status === "land" ? "Land" : r.status === "missing" ? "No data for this cell" : "Outside the dataset"}>
          <p className="text-sm text-slate-800">{r.message}</p>
        </Card>
      </div>,
      undefined,
      sub,
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
  const tone = SEVERITY_TONE(c.anomaly);
  const histPct = a.historical_percentile ?? null;
  const regPct = a.region_percentile ?? null;

  // ---- recent observations and the forecast, for the two charts
  const recent = (r.analysis?.recent_anomaly ?? []).slice(-7);
  const fdates = f?.available ? f.dates ?? [] : [];
  const err = f?.available ? f.typical_error_c ?? null : null;
  const anomObserved: TrendPoint[] = recent.map((p) => ({ date: p.date, value: p.anomaly_c }));
  const anomForecast: TrendPoint[] = fdates.map((d, i) => ({ date: d, value: f?.forecast_anomaly?.[i] ?? null, lo: err && f?.forecast_anomaly ? f.forecast_anomaly[i] - err[i] : null, hi: err && f?.forecast_anomaly ? f.forecast_anomaly[i] + err[i] : null }));
  const sstObserved: TrendPoint[] = recent.filter((p) => p.sst_c != null).map((p) => ({ date: p.date, value: p.sst_c as number }));
  const sstForecast: TrendPoint[] = fdates.map((d, i) => ({ date: d, value: f?.forecast_sst?.[i] ?? null, lo: err && f?.forecast_sst ? f.forecast_sst[i] - err[i] : null, hi: err && f?.forecast_sst ? f.forecast_sst[i] + err[i] : null }));
  const normalLine = [...recent.filter((p) => p.sst_c != null).map((p) => p.sst_c! - p.anomaly_c), ...fdates.map((_, i) => f?.climatology?.[i] ?? null)];

  const tabs: TabDef[] = [
    { id: "overview", label: "Overview" },
    { id: "heatwave", label: "Marine heatwave", hint: hw.inside === true ? <span className="rounded bg-red-100 px-1.5 py-0.5 text-[11px] font-bold text-red-900">YES</span> : undefined },
    { id: "forecast", label: "Forecast", hint: f?.available && f.direction ? <span className="rounded bg-blue-100 px-1.5 py-0.5 text-[11px] font-semibold text-blue-900">{f.direction}</span> : undefined },
    { id: "ecology", label: "Biodiversity" },
    { id: "risk", label: "Risk", hint: k?.level ? <SeverityBadge level={k.level} /> : undefined },
    { id: "alerts", label: "Alerts", hint: <span className="rounded bg-slate-200 px-1.5 py-0.5 text-[11px] font-semibold text-slate-800">{r.alerts?.length ?? 0}</span> },
    { id: "data", label: "Data" },
  ];

  const speciesList = (testId: string) => (
    <>
      <p className="text-sm font-medium text-slate-800" data-testid={testId}>{sp?.counted?.label ?? "No stored biodiversity observations for this location and time period (a sampling gap, not absence)."}</p>
      <p className="text-sm text-slate-600">{sp?.summary}</p>
      <ul className="mt-2 grid gap-2 @3xl:grid-cols-2">
        {sp?.items.map((s) => (
          <li key={`${s.aphia_id}-${s.scientific_name}`} className="rounded-lg bg-slate-50 p-3 text-sm ring-1 ring-slate-200">
            <div className="flex flex-wrap items-center gap-2">
              <span className="font-semibold text-slate-900">{s.common_name ?? s.scientific_name}</span>
              <span className={`rounded px-1.5 py-0.5 text-xs font-semibold ${CONS_TONE[s.conservation_status] ?? "bg-slate-200 text-slate-800"}`}>{s.conservation_status}</span>
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
  );

  const overview = (
    <TabPanel id="overview" active={tab}>
      <div className="grid grid-cols-2 gap-3 lg:grid-cols-4" aria-label="Key measurements">
        <MetricTile testId="tile-sst" label="Sea surface temperature" value={c.sst?.toFixed(1) ?? "–"} unit="°C" sub={`observed ${r.date}`} />
        <MetricTile testId="tile-normal" label="Normal for this day" value={c.normal_sst == null ? "–" : c.normal_sst.toFixed(1)} unit="°C" sub="long-term climatology" />
        <MetricTile testId="tile-anomaly" label="Anomaly" tone={tone} value={signed(c.anomaly)} unit="°C" sub={<><span className="font-semibold">{a.class ?? "n/a"}</span> · {warm ? "warmer than normal" : cold ? "colder than normal" : "near normal"}</>} />
        <MetricTile testId="tile-heatwave" label="Marine heatwave" tone={hw.inside === true ? "alert" : "neutral"} value={hw.inside === true ? "YES" : hw.inside === false ? "NO" : "–"}
          sub={hw.inside === true ? `${hw.run_days ?? "?"} days at this cell${hw.event?.category_name ? ` · ${hw.event.category_name}` : ""}` : hw.inside === false ? "not active here" : "not computed"} />
      </div>
      <div className="grid gap-4 @3xl:grid-cols-2">
        <Card title="How unusual is this?" aside={<Segmented label="Compare the anomaly with" value={unusual} onChange={setUnusual}
          options={[{ id: "normal", label: "Normal" }, { id: "history", label: "This cell's history" }, { id: "region", label: "Region today" }]} />}>
          {unusual === "normal" && <ScaleTrack label={`Anomaly ${signed(c.anomaly)} °C on a scale from -4 to +4 °C`} pos={((c.anomaly ?? 0) + 4) / 8} ticks={[{ at: 0, text: "−4 °C" }, { at: 0.25, text: "−2" }, { at: 0.5, text: "normal" }, { at: 0.75, text: "+2" }, { at: 1, text: "+4 °C" }]} />}
          {unusual === "history" && (histPct != null
            ? <ScaleTrack label={`Percentile ${histPct.toFixed(0)} of this cell's own history`} pos={histPct / 100} ticks={[{ at: 0, text: "coldest" }, { at: 0.5, text: "typical" }, { at: 1, text: "warmest" }]} />
            : <p className="text-sm text-slate-600">No historical distribution is available for this cell.</p>)}
          {unusual === "region" && (regPct != null
            ? <ScaleTrack label={`Percentile ${regPct.toFixed(0)} among the ocean cells of the region`} pos={regPct / 100} ticks={[{ at: 0, text: "coldest cell" }, { at: 0.5, text: "median cell" }, { at: 1, text: "warmest cell" }]} />
            : <p className="text-sm text-slate-600">No regional comparison is available for this cell.</p>)}
          <p className="mt-3 text-sm text-slate-800">current {c.sst?.toFixed(1)} − normal {c.normal_sst?.toFixed(1)} = {signed(c.anomaly)} °C{regPct != null ? ` · ${warm || !cold ? "warmer" : "colder"} than ${warm || !cold ? regPct.toFixed(0) : (100 - regPct).toFixed(0)}% of ocean cells in the ${r.region?.name}` : ""}</p>
          {a.historical_percentile != null && (
            <p className="mt-1 text-sm text-slate-700">Historical context: {c.anomaly != null && c.anomaly >= 0 ? "warmer" : "colder"} than {(c.anomaly != null && c.anomaly >= 0 ? a.historical_percentile : 100 - a.historical_percentile).toFixed(0)}% of {a.historical_samples?.toLocaleString()} same-season anomalies at this cell.</p>
          )}
          <Explain e={a.explanation} label="What is this anomaly, how unusual is it, and why?" />
        </Card>
        <Card title="Recent anomaly and the next seven days" aside={<span className="text-xs text-slate-500">°C relative to normal</span>}>
          {anomObserved.length + anomForecast.length >= 2
            ? <TrendChart observed={anomObserved} forecast={anomForecast} unit="°C" signedValues active={overviewDay} onActive={setOverviewDay} label="Observed anomaly of the last days and the forecast anomaly of the next days" />
            : <p className="text-sm text-slate-600">Not enough recent observations to draw a trend.</p>}
          {r.analysis?.trends && <p className="mt-2 text-sm text-slate-700" data-testid="recent-trends">Recent trend (observed, {r.analysis.trends.from} to {r.analysis.trends.to}): SST {signed(r.analysis.trends.sst_3d_c_per_day, 2)} °C/day over 3 days and {signed(r.analysis.trends.sst_7d_c_per_day, 2)} °C/day over {r.analysis.trends.days} days; anomaly {signed(r.analysis.trends.anomaly_3d_change_c, 2)} °C over 3 days and {signed(r.analysis.trends.anomaly_7d_change_c, 2)} °C over {r.analysis.trends.days} days.</p>}
          {r.analysis?.spatial_pattern && <p className="mt-1 text-sm text-slate-700">{r.analysis.spatial_pattern.text}</p>}
        </Card>
      </div>
      {loc}
    </TabPanel>
  );

  const ev = hw.event;
  const heatwave = (
    <TabPanel id="heatwave" active={tab}>
      <Card title="Marine heatwave analysis" aside={hw.inside === true ? <span className="rounded bg-red-100 px-2 py-0.5 text-xs font-bold text-red-900">YES</span> : hw.inside === false ? <span className="rounded bg-slate-100 px-2 py-0.5 text-xs font-semibold text-slate-800">NO</span> : undefined}>
        <p className="text-base font-medium text-slate-900">{hw.message}</p>
        {hw.analysis?.status && <p className="mt-1 text-sm font-semibold text-slate-700" data-testid="heatwave-status">Forecast classification: <span className="rounded bg-red-50 px-1.5 py-0.5 text-red-900 ring-1 ring-red-100">{hw.analysis.status}</span></p>}
      </Card>
      {hw.inside && ev && (
        <div className="grid gap-4 @3xl:grid-cols-2">
          <Card title="Severity and intensity">
            <CategoryScale category={ev.category_name} />
            <div className="mt-4 space-y-3">
              <BarMeter label="Maximum anomaly of the event" value={Math.max(0, ev.max_anomaly_c)} max={Math.max(5, ev.max_anomaly_c)} display={`${signed(ev.max_anomaly_c)} °C`} tone="bg-red-500" />
              <BarMeter label="Event mean anomaly (whole event today)" value={Math.max(0, ev.current_anomaly_c ?? 0)} max={Math.max(5, ev.max_anomaly_c)} display={`${signed(ev.current_anomaly_c)} °C`} tone="bg-orange-400" />
              <BarMeter label="Anomaly at this location" value={Math.max(0, c.anomaly ?? 0)} max={Math.max(5, ev.max_anomaly_c)} display={`${signed(c.anomaly)} °C`} tone="bg-amber-500" />
            </div>
          </Card>
          <Card title="Duration and extent">
            <div className="grid grid-cols-2 gap-3">
              <MetricTile label="Event duration" value={ev.duration_days} unit="days" sub={`since ${ev.start_date}`} tone="alert" />
              <MetricTile label="Affected area" value={km2(ev.area_km2)} sub={`${Math.round(ev.area_km2).toLocaleString()} km²`} tone="neutral" />
            </div>
            <div className="mt-4 space-y-3">
              <BarMeter label="Days in heatwave state at this cell" value={hw.run_days ?? 0} max={Math.max(30, hw.run_days ?? 0, ev.duration_days)} display={`${hw.run_days ?? "–"} days`} tone="bg-red-500" mark={{ at: 5, text: "5-day minimum that defines a heatwave" }} />
              {ev.cumulative_intensity_c_days != null && <p className="text-sm text-slate-700">Cumulative intensity <strong className="tabular-nums">{ev.cumulative_intensity_c_days.toFixed(0)} °C·days</strong> (anomaly summed over the event's days).</p>}
            </div>
          </Card>
        </div>
      )}
      {hw.analysis && hw.analysis.lines.length > 0 && (
        <Card title="What the data say">
          <ul className="list-disc space-y-1 pl-5 text-sm text-slate-800" data-testid="heatwave-analysis">{hw.analysis.lines.map((t) => <li key={t}>{t}</li>)}</ul>
        </Card>
      )}
      {hw.inside && ev && (
        <Card title="Event details">
          <p className="text-sm text-slate-600">Event {ev.id} · {hw.event_region}</p>
          <dl className="mt-2 grid grid-cols-2 gap-2 text-sm @xl:grid-cols-4">
            {[["Start date", ev.start_date], ["Duration", `${ev.duration_days} days`], ["Category", ev.category_name], ["Cell run", `${hw.run_days} days`],
              ["Event mean anomaly (whole event today)", `${signed(ev.current_anomaly_c)} °C`], ["Event maximum anomaly", `${signed(ev.max_anomaly_c)} °C`],
              ["Cumulative intensity", ev.cumulative_intensity_c_days != null ? `${ev.cumulative_intensity_c_days.toFixed(0)} °C·days` : "–"], ["Affected area", `${Math.round(ev.area_km2).toLocaleString()} km²`]].map(([l, v]) => (
              <div key={l} className="rounded-lg bg-slate-50 px-2.5 py-1.5 ring-1 ring-slate-200"><dt className="text-xs text-slate-500">{l}</dt><dd className="font-semibold text-slate-900">{v}</dd></div>
            ))}
          </dl>
          {ev.ecological_relationship && <p className="mt-3 text-sm text-slate-800"><strong>Ecological relationship:</strong> {ev.ecological_relationship}</p>}
          {ev.affected_species && ev.affected_species.length > 0 && (
            <p className="mt-2 text-sm text-slate-800"><strong>Species with records in the event area:</strong> {ev.affected_species.map((s) => `${s.common_name ?? s.scientific_name} (${s.conservation_status}, ${s.n_records} record${s.n_records === 1 ? "" : "s"})`).join(", ")}.</p>
          )}
          <p className="mt-2 text-sm text-slate-700"><strong>Why it matters:</strong> {hw.why_it_matters}</p>
          <Link to={`/heatwaves${act.toQuery({ event: ev.id, lat: undefined })}`} className="mt-2 inline-block text-sm font-semibold text-tide hover:underline">Event details and footprint →</Link>
        </Card>
      )}
    </TabPanel>
  );

  const forecast = (
    <TabPanel id="forecast" active={tab}>
      {!f?.available ? (
        <Card title="7-day forecast"><p className="text-sm text-slate-700">{f?.message ?? "No forecast for this location."}</p></Card>
      ) : (
        <>
          <Card title="Sea surface temperature: last week and the next seven days" aside={f.direction ? <span className="rounded bg-blue-100 px-2 py-0.5 text-xs font-semibold text-blue-900">{f.direction}</span> : undefined}>
            <p className="mb-2 text-base font-medium text-slate-900" data-testid="forecast-reading">{f.reading?.text ?? f.summary}</p>
            <TrendChart observed={sstObserved} forecast={sstForecast} normal={normalLine} unit="°C" active={forecastDay} onActive={setForecastDay} label="Observed sea surface temperature of the last days and the forecast of the next days" />
            <ol className="mt-3 grid grid-cols-2 gap-2 @xl:grid-cols-4 @3xl:grid-cols-7" aria-label="Forecast days">
              {f.dates?.map((d, i) => {
                const delta = f.change_vs_latest_c?.[i];
                return (
                  <li key={d}>
                    <button type="button" onClick={() => setForecastDay(sstObserved.length + i)} onMouseEnter={() => setForecastDay(sstObserved.length + i)}
                      className={`w-full rounded-lg px-2 py-2 text-left ring-1 ${forecastDay === sstObserved.length + i ? "bg-blue-50 ring-blue-400" : "bg-white ring-slate-200 hover:bg-slate-50"}`}>
                      <div className="text-xs font-medium text-slate-500">{d.slice(5)}</div>
                      <div className="text-lg font-semibold tabular-nums text-slate-900">{f.forecast_sst?.[i].toFixed(1)}<span className="text-xs font-normal text-slate-500"> °C</span></div>
                      <div className="text-xs tabular-nums text-slate-700">{signed(f.forecast_anomaly?.[i])} °C anomaly</div>
                      <div className="text-xs tabular-nums text-slate-500">{delta == null ? "" : `${signed(delta, 2)} vs latest`}</div>
                    </button>
                  </li>
                );
              })}
            </ol>
          </Card>
          <div className="grid gap-4 @3xl:grid-cols-2">
            <Card title="Reading the forecast">
              {f.reading && <p className="text-sm text-slate-700">Maximum predicted |anomaly| {f.reading.max_abs_anomaly_c.toFixed(1)} °C · mean {signed(f.reading.mean_anomaly_c)} °C · anomaly {f.reading.anomaly_label} · SST change over the forecast {signed(f.reading.sst_change_c, 2)} °C. Model prediction, not an observation.</p>}
              {f.interpretation && <ul className="mt-2 list-disc space-y-1 pl-5 text-sm text-slate-700">{f.interpretation.map((t) => <li key={t}>{t}</li>)}</ul>}
              <p className="mt-2 text-xs text-slate-500">{f.model}, issued from {f.issued_from}{f.trained_on ? `; weights trained on ${f.trained_on}` : ""}.</p>
            </Card>
            {r.analysis?.why_forecast && (
              <div data-testid="why-forecast">
                <Card title={r.analysis.why_forecast.headline} className="h-full bg-sky-50/60"><ul>{r.analysis.why_forecast.bullets.map((b) => <Statement key={b.text} s={b} />)}</ul></Card>
              </div>
            )}
          </div>
          <Card title="Forecast values">
            <details>
              <summary className="cursor-pointer text-sm font-semibold text-tide">Table of the seven forecast days</summary>
              <div className="mt-2 overflow-x-auto">
                <table className="w-full text-left text-sm">
                  <caption className="sr-only">Forecast at this location</caption>
                  <thead className="text-slate-500"><tr><th scope="col" className="pr-3">Date</th><th scope="col" className="pr-3">Predicted SST °C</th><th scope="col" className="pr-3">Predicted anomaly °C</th><th scope="col" className="pr-3">Change from latest °C</th><th scope="col" className="pr-3">Direction</th><th scope="col">Typical error</th></tr></thead>
                  <tbody>
                    {f.dates?.map((d, i) => (
                      <tr key={d} className="border-t border-slate-100"><td className="pr-3">{d.slice(5)}</td><td className="pr-3">{f.forecast_sst?.[i].toFixed(1)}</td><td className="pr-3">{signed(f.forecast_anomaly?.[i])}</td><td className="pr-3">{signed(f.change_vs_latest_c?.[i], 2)}</td><td className="pr-3">{f.direction_by_day?.[i] ?? "–"}</td><td>{f.typical_error_c ? `±${f.typical_error_c[i].toFixed(2)}` : "n/a"}</td></tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </details>
          </Card>
          <Card title="Explainable AI: why this forecast">
            <ForecastExplain dataset={dataset} lat={r.cell?.lat ?? point.lat} lon={r.cell?.lon_180 ?? point.lon} quick={f?.available ? (f as never) : null} risk={{ driver: k?.drivers?.find((d) => d.factor === "forecast"), score: k?.score, level: k?.level }} />
          </Card>
        </>
      )}
    </TabPanel>
  );

  const ecology = (
    <TabPanel id="ecology" active={tab}>
      <Card title="Biodiversity & ecosystem context" aside={r.obis?.available && r.obis.counts ? <span className="text-sm text-slate-600">{`${r.obis.counts.distinct_species.toLocaleString()} species · ${r.obis.counts.observations.toLocaleString()} observations`}</span> : sp ? <span className="text-sm text-slate-600">{sp.counted && sp.counted.observations > 0 ? `${sp.counted.distinct_species} species · ${sp.counted.observations.toLocaleString()} observations` : "limited coverage"}</span> : undefined}>
        {r.obis?.available ? (
          <>
            <ObisPanel o={r.obis} />
            <details className="mt-3 rounded-lg bg-slate-50 p-3 ring-1 ring-slate-200" data-testid="stored-records">
              <summary className="cursor-pointer text-sm font-semibold text-slate-700">Stored project records (the selection the risk score uses)</summary>
              <div className="mt-2">{speciesList("stored-species-counted")}</div>
            </details>
          </>
        ) : (
          <>
            {r.obis?.status === "refreshing" && <p role="status" className="mb-1 text-sm text-slate-600">Retrieving the latest OBIS records for this area; the stored project records are shown meanwhile.</p>}
            {speciesList("species-counted")}
          </>
        )}
      </Card>
      <div className="grid gap-4 @3xl:grid-cols-2">
        <Card title="Ecological and physical context" aside={r.context?.status === "refreshing" ? <span className="text-xs text-slate-500">retrieving…</span> : undefined}>
          <ContextPanel ctx={r.context} />
        </Card>
        <div className="space-y-4">
          <Card title="Potential exposure">
            {r.obis?.available ? <ExposurePanel o={r.obis} /> : (
              <p className="text-sm text-slate-700" data-testid="exposure-fallback">
                {sp && sp.items.some((s) => (s.records_in_heatwave ?? 0) > 0)
                  ? `${sp.items.filter((s) => (s.records_in_heatwave ?? 0) > 0).length} species with stored OBIS records near this place have records inside the current marine-heatwave footprint. These records indicate potential exposure to the observed thermal conditions, not biological damage.`
                  : "The recorded places of nearby species are compared with the marine-heatwave footprint and the predicted anomaly area as soon as OBIS records are available for this area."}
              </p>
            )}
          </Card>
          <Card title="Potential environmental implications">
            <details open className="rounded-lg bg-lime-50/70 p-3 text-sm ring-1 ring-lime-100">
              <summary className="cursor-pointer text-sm font-semibold text-lime-900">What these conditions may mean for marine ecosystems</summary>
              {r.implications?.available ? (
                <>
                  <ul className="mt-1">{r.implications.items.map((s) => <Statement key={s.text} s={s} />)}</ul>
                  <p className="mt-1 text-xs text-slate-700">{r.implications.caveat}</p>
                </>
              ) : <p className="mt-1 text-sm text-slate-700">{r.implications?.message ?? "No implications are drawn without an SST anomaly."}</p>}
            </details>
          </Card>
        </div>
      </div>
    </TabPanel>
  );

  const risk = (
    <TabPanel id="risk" active={tab}>
      <Card title="Risk assessment" aside={k?.level ? <SeverityBadge level={k.level} /> : undefined}>
        {!k || k.score == null ? (
          <p className="text-sm text-slate-800">{k?.message ?? "A risk level could not be calculated here because the SST anomaly it needs is not available for this cell and date. This is not low risk."}</p>
        ) : (
          <>
            <div className="grid gap-4 @xl:grid-cols-[14rem_1fr]">
              <div>
                <div className="text-4xl font-semibold tabular-nums text-slate-900">{k.score.toFixed(2)}<span className="text-lg font-medium text-slate-500"> / 1</span></div>
                <div className="text-sm text-slate-600">evidence completeness {k.evidence_completeness != null ? `${Math.round(k.evidence_completeness * 100)}%` : "n/a"}</div>
              </div>
              <ScaleTrack label={`Risk score ${k.score.toFixed(2)} of 1`} pos={k.score} gradient="linear-gradient(90deg,#bbf7d0 0%,#fde68a 35%,#fdba74 65%,#fca5a5 100%)" ticks={[{ at: 0, text: "0" }, { at: 0.25, text: "0.25 moderate" }, { at: 0.5, text: "0.5 high" }, { at: 0.75, text: "0.75 critical" }, { at: 1, text: "1" }]} />
            </div>
            <p className="mt-3 text-sm text-slate-700" data-testid="indicators-used">Risk based on {k.drivers?.filter((d) => d.available).length ?? 0} available indicator{k.drivers?.filter((d) => d.available).length === 1 ? "" : "s"}: {k.drivers?.filter((d) => d.available).map((d) => d.label).join(", ")}.</p>
            <details className="mt-3 rounded-lg bg-slate-50 p-3 ring-1 ring-slate-200" open>
              <summary className="cursor-pointer text-sm font-semibold text-slate-800">Why this risk? Drivers and their contributions</summary>
              <ul className="mt-1 divide-y divide-slate-200">{k.drivers?.filter((d) => d.available).map((d) => <Driver key={d.factor} d={d} />)}</ul>
              {k.score_breakdown?.text && (
                <p className="mt-2 rounded bg-white px-3 py-2 text-sm text-slate-800" data-testid="score-sum">
                  Final score: <strong>{k.score_breakdown.text}</strong> → {k.level === "MEDIUM" ? "MODERATE" : k.level}. {k.drivers?.some((d) => d.saturated) ? "A factor “saturated at the scoring threshold” has reached the top of its 0–1 scale because the measured value is at or beyond the level where the factor stops increasing; it is a measurement, not a default, and not a statement that the physical value is 100%. " : ""}
                  Bands: below 0.25 LOW, 0.25–0.5 MODERATE, 0.5–0.75 HIGH, 0.75 and above CRITICAL.
                </p>
              )}
            </details>
          </>
        )}
      </Card>
      {k && k.score != null && (
        <Card title="Why this risk level">
          <p className="text-sm text-slate-800" data-testid="risk-why">
            {k.level === "MEDIUM" ? "MODERATE" : k.level} ({k.score.toFixed(2)}): {[...(k.drivers ?? [])].filter((d) => d.available && d.contribution != null).sort((x, y) => (y.contribution ?? 0) - (x.contribution ?? 0)).map((d) => `${d.label} ${d.raw == null ? "" : `${d.factor === "persistence" || d.factor === "overlap" ? d.raw : signed(d.raw)} ${d.raw_unit}`} adds ${d.contribution?.toFixed(2)}`).join("; ")}.
          </p>
          {k.drivers?.some((d) => !d.available) && (
            <details className="mt-2 rounded-lg bg-slate-50 p-3 ring-1 ring-slate-200" data-testid="data-details">
              <summary className="cursor-pointer text-sm font-semibold text-slate-700">Data details: {k.drivers.filter((d) => !d.available).length} indicator{k.drivers.filter((d) => !d.available).length === 1 ? "" : "s"} excluded from the score</summary>
              <p className="mt-1 text-sm text-slate-600">No stored data were found for this indicator even after widening the search. The score is renormalised over the available indicators (never counted as zero or as one); biodiversity coverage affects confidence, not whether the environmental risk can be calculated.</p>
              <ul className="divide-y divide-slate-200">{k.drivers.filter((d) => !d.available).map((d) => <Driver key={d.factor} d={d} />)}</ul>
            </details>
          )}
          {r.analysis?.risk_dominance && <p className="mt-2 text-sm text-slate-800" data-testid="risk-dominance">{r.analysis.risk_dominance}</p>}
          {k.explanation && <Explain e={k.explanation} label="Explain this risk in plain language" />}
        </Card>
      )}
    </TabPanel>
  );

  const alerts = (
    <TabPanel id="alerts" active={tab}>
      <Card title="Alerts" aside={<span className="text-sm text-slate-500">{r.alerts?.length ?? 0}</span>}>
        {r.alerts && r.alerts.length > 0 ? (
          <ul className="grid gap-2 @3xl:grid-cols-2">{r.alerts.map((al) => <AlertRow key={al.id} a={al} onOpen={onFocus ? () => onFocus(al.latitude, al.longitude) : undefined} />)}</ul>
        ) : (
          <p className="text-sm text-slate-700">No alert is active at or near this location.</p>
        )}
      </Card>
    </TabPanel>
  );

  const data = (
    <TabPanel id="data" active={tab}>
      <Card title="Data & methodology" aside={r.data_dates ? <span className={`rounded px-2 py-0.5 text-xs font-semibold ${r.data_dates.aligned ? "bg-emerald-100 text-emerald-900" : "bg-amber-100 text-amber-900"}`}>{r.data_dates.aligned ? "same day" : "dates differ"}</span> : undefined}>
        {r.sources && r.sources.length > 0 && <div className="mb-3 rounded-lg bg-slate-50 p-3 ring-1 ring-slate-200"><div className="mb-1 text-sm font-semibold text-slate-800">Data sources</div><SourcesTable rows={r.sources} /></div>}
        <details className="rounded-lg bg-slate-50 p-3 text-sm ring-1 ring-slate-200" open={r.data_dates ? !r.data_dates.aligned : false}>
          <summary className="cursor-pointer text-sm font-semibold text-slate-800">Which day each product refers to</summary>
          {r.data_dates && (
            <>
              <p className="mt-1 text-sm text-slate-800">{r.data_dates.message}</p>
              <dl className="mt-2 grid grid-cols-2 gap-x-4 gap-y-1 text-sm">
                <dt className="text-slate-500">Latest observed SST</dt><dd className="font-semibold">{r.data_dates.sst_observation.latest_available}{r.data_dates.sst_observation.date !== r.data_dates.sst_observation.latest_available ? ` (report date ${r.data_dates.sst_observation.date})` : ""}</dd>
                <dt className="text-slate-500">Anomaly</dt><dd className="font-semibold">{r.data_dates.anomaly.date}</dd>
                <dt className="text-slate-500">Marine heatwave</dt><dd className="font-semibold">{r.data_dates.marine_heatwave.date ?? "not computed"}</dd>
                <dt className="text-slate-500">Forecast initialised from</dt><dd className="font-semibold">{r.data_dates.forecast.initialised_from ?? "no forecast"}</dd>
                <dt className="text-slate-500">Forecast valid dates</dt><dd className="font-semibold">{r.data_dates.forecast.valid_dates ? `${r.data_dates.forecast.valid_dates[0]} to ${r.data_dates.forecast.valid_dates[r.data_dates.forecast.valid_dates.length - 1]}` : "–"}</dd>
                <dt className="text-slate-500">Newest species record</dt><dd className="font-semibold">{r.data_dates.species_records.latest_record ?? "none"} (records of the last {Math.round(r.data_dates.species_records.window_days / 365)} years are used)</dd>
              </dl>
              {r.risk?.drivers?.some((d) => d.status === "unavailable") && (
                <ul className="mt-2 list-disc pl-5 text-sm text-slate-700">{r.risk.drivers.filter((d) => d.status === "unavailable").map((d) => <li key={d.factor}><strong>{d.label}:</strong> no stored data for {d.missing_input}</li>)}</ul>
              )}
            </>
          )}
        </details>
        <details className="mt-3 rounded-lg bg-slate-50 p-3 text-sm ring-1 ring-slate-200">
          <summary className="cursor-pointer text-sm font-semibold text-slate-800">Model inputs</summary>
          <div className="mt-1"><ModelInputs dataset={dataset} /></div>
        </details>
        <details className="mt-3 rounded-lg bg-slate-50 p-3 text-sm ring-1 ring-slate-200">
          <summary className="cursor-pointer text-sm font-semibold text-slate-800">Method notes</summary>
          <p className="mt-1 text-sm text-slate-700">Observed values come from NOAA OISST; anomalies are departures from the daily climatology; the marine-heatwave status follows the project definition (Hobday et al., 2016, simplified); forecasts are ConvLSTM model output. The physical-driver evidence in the forecast tab describes indicators that are consistent with an anomaly; it does not identify a single cause.</p>
        </details>
      </Card>
      <p className="px-1 text-xs text-slate-500">
        <span className="font-semibold text-slate-600">Data source</span> · {providerLabel(r.provider)}{r.provider.is_observational ? " (observations)" : " (modelled dataset)"} · {r.dataset} · {r.date} ·{" "}
        <Link to="/ocean-data" className="underline">details</Link>
      </p>
    </TabPanel>
  );

  return shell(
    <>{overview}{heatwave}{forecast}{ecology}{risk}{alerts}{data}</>,
    <Tabs tabs={tabs} active={tab} onChange={setTab} label="Location report sections" />,
    sub,
  );
}
