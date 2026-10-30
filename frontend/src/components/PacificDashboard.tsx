import { providerLabel } from "../utils/format";
import { Link } from "react-router-dom";
import { getForecast, getSpeciesLayer, getSummary } from "../api/environment";
import { getBiodiversitySummary, getRiskMap, listHeatwaves } from "../api/intelligence";
import { listAlerts } from "../api/modelOutputs";
import { useActive } from "../contexts/ActiveSelection";
import { useAsync } from "../hooks/useAsync";
import { cached } from "../hooks/useCached";
import type { Alert } from "../types";
import AlertCard from "./AlertCard";
import ContextBar from "./ContextBar";
import DashSection, { Metric } from "./DashSection";
import EmptyState from "./EmptyState";
import PageHeader from "./PageHeader";
import HistoricalSst from "./HistoricalSst";
import DataDatesNote from "./DataDatesNote";
import Status from "./Status";
import Term from "./Term";

const signed = (v: number | null, d = 1) => (v == null ? "–" : `${v > 0 ? "+" : ""}${v.toFixed(d)}`);
const km2 = (v: number) => `${Math.round(v).toLocaleString()} km²`;

/** The seven forecast days of the region mean as a small line, with the normal for each day (dashed); every point is a value the forecast service returned. */
function MiniForecast({ dates, sst, normal }: { dates: string[]; sst: (number | null)[]; normal: (number | null)[] }) {
  const pts = sst.map((v, i) => ({ v, n: normal[i] ?? null, d: dates[i] })).filter((p): p is { v: number; n: number | null; d: string } => p.v != null);
  if (pts.length < 2) return null;
  const W = 300, H = 120, L = 34, R = 8, T = 10, B = 22;
  const all = pts.flatMap((p) => (p.n != null ? [p.v, p.n] : [p.v]));
  let lo = Math.min(...all), hi = Math.max(...all);
  const pad = (hi - lo || 0.2) * 0.2; lo -= pad; hi += pad;
  const x = (i: number) => L + (i / (pts.length - 1)) * (W - L - R);
  const y = (v: number) => T + ((hi - v) / (hi - lo)) * (H - T - B);
  const line = pts.map((p, i) => `${i ? "L" : "M"} ${x(i).toFixed(1)} ${y(p.v).toFixed(1)}`).join(" ");
  const norm = pts.every((p) => p.n != null) ? pts.map((p, i) => `${i ? "L" : "M"} ${x(i).toFixed(1)} ${y(p.n as number).toFixed(1)}`).join(" ") : null;
  return (
    <div data-testid="mini-forecast">
      <svg viewBox={`0 0 ${W} ${H}`} className="h-auto w-full" role="img" aria-label={`Forecast region-mean SST, ${pts[0].d} to ${pts[pts.length - 1].d}: ${pts[0].v.toFixed(1)} to ${pts[pts.length - 1].v.toFixed(1)} °C`}>
        {[lo + pad, hi - pad].map((t) => (<g key={t}><line x1={L} x2={W - R} y1={y(t)} y2={y(t)} stroke="#d6e4ea" strokeDasharray="3 3" /><text x={L - 4} y={y(t) + 4} textAnchor="end" fontSize="11" fill="#334155">{t.toFixed(1)}</text></g>))}
        {norm && <path d={norm} fill="none" stroke="#64748b" strokeWidth="1.8" strokeDasharray="5 3" />}
        <path d={line} fill="none" stroke="#2563eb" strokeWidth="2.5" strokeLinejoin="round" />
        {pts.map((p, i) => (<circle key={p.d} cx={x(i)} cy={y(p.v)} r={3.2} fill="#2563eb"><title>{`${p.d}: ${p.v.toFixed(2)} °C`}</title></circle>))}
        <text x={L} y={H - 6} fontSize="11" fill="#334155">{pts[0].d.slice(5)}</text>
        <text x={W - R} y={H - 6} fontSize="11" fill="#334155" textAnchor="end">{pts[pts.length - 1].d.slice(5)}</text>
      </svg>
      <div className="flex gap-4 text-xs text-slate-600" aria-hidden><span className="inline-flex items-center gap-1"><span className="inline-block h-0.5 w-4 bg-blue-600" />forecast</span>{norm && <span className="inline-flex items-center gap-1"><span className="inline-block w-4 border-t-2 border-dashed border-slate-500" />normal</span>}</div>
    </div>
  );
}
const FLOW: { extra: Record<string, string>; label: string; sub: string }[] = [
  { extra: { layer: "sst" }, label: "Conditions", sub: "SST on the map" },
  { extra: { layer: "anomaly" }, label: "Anomaly", sub: "difference from normal" },
  { extra: { layer: "heatwave" }, label: "Marine heatwave", sub: "persistent anomaly" },
  { extra: { layer: "anomaly", species: "1" }, label: "Biodiversity", sub: "records overlapping" },
  { extra: { layer: "risk" }, label: "Ecological risk", sub: "factors and explanation" },
  { extra: { layer: "risk", alerts: "1" }, label: "Alert", sub: "evidence trail" },
];

/** The Dashboard for a dataset other than the NE Pacific: every number comes from the API for the ACTIVE dataset, region and date. */
export default function PacificDashboard() {
  const act = useActive();
  const q = act.toQuery();
  const mq = (extra: Record<string, string>) => act.toQuery(extra);
  const date = act.date ?? undefined;
  const sst = useAsync(() => getSummary(act.dataset, "sst", act.region, date), [act.dataset, act.region, date]);
  const anom = useAsync(() => getSummary(act.dataset, "anomaly", act.region, date), [act.dataset, act.region, date]);
  const fc = useAsync(() => getForecast(act.dataset, act.region), [act.dataset, act.region]);
  const hw = useAsync(() => listHeatwaves({ dataset: act.dataset, region: act.region !== "pacific" ? act.region : undefined }), [act.dataset, act.region]);
  const risk = useAsync(() => getRiskMap(act.dataset, act.region, date), [act.dataset, act.region, date]);
  const bio = useAsync(() => cached("bio-summary", getBiodiversitySummary), []);
  const exposure = useAsync(() => getSpeciesLayer(act.dataset, act.region, date), [act.dataset, act.region, date]);
  const alerts = useAsync(
    () => listAlerts({ dataset: act.dataset, region: act.region !== "pacific" ? act.region : undefined, status: "NEW", page_size: 4 }),
    [act.dataset, act.region],
  );
  // never show a result that belongs to another dataset or region
  const fresh = <T extends { dataset?: string | { id: string }; region?: { id: string } }>(r: { data: T | null; isLoading: boolean }) => {
    const d = r.data;
    if (!d || r.isLoading) return null;
    const ds = typeof d.dataset === "string" ? d.dataset : d.dataset?.id;
    return (!ds || ds === act.dataset) && (!d.region || d.region.id === act.region) ? d : null;
  };
  const S = fresh(sst);
  const A = fresh(anom);
  const F = fresh(fc);
  const R = fresh(risk);
  const H = hw.data && !hw.isLoading && (hw.data.dataset ?? "ne_pacific") === act.dataset ? hw.data : null;
  const gen = S ? S.kind === "generated" : A ? A.kind === "generated" : false;
  const src = S ? providerLabel(S.provider) : "";
  const counts = R ? (R.levels as number[][]).flat().filter((l) => l >= 0) : [];
  const share = (min: number) => (counts.length ? (100 * counts.filter((l) => l >= min).length) / counts.length : null);
  const events = H?.items ?? [];
  const largest = events.length ? events.reduce((a, b) => (b.area_km2 > a.area_km2 ? b : a)) : null;

  return (
    <div>
      <PageHeader title="Ocean Environmental Intelligence Dashboard">
        An overview of the selected dataset and region: ocean conditions, the forecast, marine heatwaves, biodiversity, ecological risk and alerts. Each panel shows its date and
        source and links to the detailed view; the dataset, region and date are shared with every page.
      </PageHeader>
      <div className="mt-3">
        <ContextBar showDate />
      </div>

      <DataDatesNote />

      <nav aria-label="From conditions to alerts" className="mt-4 overflow-x-auto">
        <ol className="flex min-w-max items-stretch gap-1 text-xs">
          {FLOW.map((f, i) => (
            <li key={f.label} className="flex items-center gap-1">
              <Link to={`/ocean-map${act.toQuery(f.extra)}`} className="block rounded-md bg-white/80 px-3 py-1.5 ring-1 ring-slate-200 hover:bg-white">
                <span className="block font-semibold text-slate-900">{f.label}</span>
                <span className="block text-slate-600">{f.sub}</span>
              </Link>
              {i < FLOW.length - 1 && <span aria-hidden className="text-slate-500">→</span>}
            </li>
          ))}
        </ol>
      </nav>

      <div className="@container mt-4"><div className="grid grid-cols-1 items-stretch gap-4 @2xl:grid-cols-2 @4xl:grid-cols-3">
        <DashSection title="Ocean conditions" to={`/ocean-map${mq({ layer: "anomaly" })}`} linkLabel="Show on the map" tag={gen ? "generated" : "observed"}>
          <Status isLoading={sst.isLoading || anom.isLoading} error={sst.error ?? anom.error} hasData={!!S}>
            {S && (
              <>
                <Metric
                  label={<Term k="sst">Sea surface temperature</Term>}
                  value={S.mean == null ? "–" : `${S.mean.toFixed(1)} °C`}
                  note={`Area-weighted mean over the ${S.region.name}; range ${S.min?.toFixed(1)} to ${S.max?.toFixed(1)} °C.`}
                  meta={`Date ${S.date} (latest ${S.latest_available_date}) · Data source ${src}`}
                />
                {A && (
                  <Metric
                    label={<Term k="anomaly">SST anomaly</Term>}
                    value={A.mean == null ? "–" : `${signed(A.mean)} °C`}
                    note={A.mean == null ? undefined : `${Math.abs(A.mean) < 0.5 ? "Close to normal" : A.mean > 0 ? "Warmer than normal" : "Colder than normal"} on average; strongest cell ${signed(A.max)} / ${signed(A.min)} °C.`}
                    meta={`Valid cells ${A.coverage.valid_cells.toLocaleString()} of ${A.coverage.ocean_cells.toLocaleString()} (${A.coverage.valid_pct_of_ocean ?? "–"}%)`}
                  />
                )}
              </>
            )}
          </Status>
        </DashSection>

        <DashSection title="Forecast" to={`/ocean-map${mq({ layer: "forecast_anomaly" })}`} linkLabel="Show the forecast on the map" tag="forecast">
          <Status isLoading={fc.isLoading} error={fc.error} hasData={!!F}>
            {F && (
              <>
                <Metric
                  label={`Forecast SST, +${F.horizons.length} days`}
                  value={F.forecast_sst[F.forecast_sst.length - 1] == null ? "–" : `${F.forecast_sst[F.forecast_sst.length - 1]!.toFixed(1)} °C`}
                  note={`${signed(F.forecast_anomaly[F.forecast_anomaly.length - 1])} °C versus the daily climatology for ${F.target_dates[F.target_dates.length - 1]}.`}
                  meta={`Issued from ${F.issued_from} · ${F.model.name}`}
                />
                <MiniForecast dates={F.target_dates} sst={F.forecast_sst} normal={F.climatology_sst} />
                <Metric label="Valid dates" value={`${F.target_dates[0].slice(5)} → ${F.target_dates[F.target_dates.length - 1].slice(5)}`} note={`${F.target_dates.length} daily steps after the ${F.issued_from} observation.`} />
              </>
            )}
          </Status>
        </DashSection>

        <DashSection title="Marine heatwaves" to={`/ocean-map${mq({ layer: "heatwave" })}`} linkLabel="Show heatwaves on the map" tag="derived">
          <Status isLoading={hw.isLoading} error={hw.error} hasData={!!H}>
            {H && (
              <>
                <Metric
                  label={<Term k="heatwave">Active events</Term>}
                  value={String(H.total)}
                  note={`${(H.summary.active_share * 100).toFixed(1)}% of the dataset's ocean area (${km2(H.summary.active_area_km2)}) is in a heatwave state.`}
                  meta={`Date ${H.summary.latest_date} · baseline ${H.summary.baseline[0].slice(0, 4)}–${H.summary.baseline[1].slice(0, 4)} · ${H.summary.is_observational === false ? "derived from the dataset's SST" : "derived from observations"}`}
                />
                <Metric label="Largest event" value={largest ? km2(largest.area_km2) : "–"} note={largest ? `${largest.category_name}, ${largest.duration_days} days, peak ${signed(largest.max_anomaly_c)} °C.` : "No active event in this region."} />
              </>
            )}
          </Status>
        </DashSection>

        <div className="@2xl:col-span-2 @4xl:col-span-3">
          <HistoricalSst />
        </div>

        <DashSection title="Biodiversity" to={`/ocean-map${mq({ species: "1" })}`} linkLabel="Show species on the map" tag="observed">
          <Status isLoading={bio.isLoading} error={bio.error} hasData={!!bio.data}>
            {bio.data && (
              <>
                {exposure.data && !exposure.isLoading && exposure.data.dataset === act.dataset ? (
                  exposure.data.summary.records > 0 ? (
                    <Metric
                      label={`Species observations in this region (last ${Math.round(exposure.data.summary.window_days / 365)} years)`}
                      value={exposure.data.summary.records.toLocaleString()}
                      note={`${exposure.data.summary.species} distinct species recorded in the ${exposure.data.region.name}, at ${exposure.data.summary.points_total.toLocaleString()} locations.`}
                      meta={`Stored OBIS observations in this region and time window (a selection of records, not a survey). Whole catalogue: ${bio.data.n_records.toLocaleString()} observations of ${bio.data.species_with_records} species.`}
                    />
                  ) : (
                    <Metric label="Species observations in this region" value="Limited coverage" note="No stored biodiversity observations fall in this region and time period. That is a sampling gap, not an absence of species."
                      meta={`Catalogue totals, all areas and dates: ${bio.data.n_records.toLocaleString()} observations of ${bio.data.species_with_records} species.`} />
                  )
                ) : (
                  <Metric label="Species observations in this region" value="…" note="Counting the stored observations in this region." meta={`Catalogue totals, all areas and dates: ${bio.data.n_records.toLocaleString()} observations of ${bio.data.species_with_records} species.`} />
                )}
                {exposure.data && !exposure.isLoading && exposure.data.dataset === act.dataset && (
                  <Metric
                    label="Species exposure"
                    value={`${exposure.data.summary.points_in_heatwave} of ${exposure.data.summary.points}`}
                    note={`species record locations inside a current marine heatwave in this region${exposure.data.summary.points >= 2500 ? " (the 2,500 locations with the most records, threatened species first)" : ""}.`}
                    meta={`${exposure.data.summary.threatened_in_heatwave} threatened or near-threatened species exposed · ${exposure.data.summary.points_high_risk} record locations in HIGH or CRITICAL risk cells · record density, not a range`}
                  />
                )}
                <Metric label="Conservation-sensitive species" value={String(bio.data.conservation_sensitive_with_records)} note="With a stored VU/EN/CR category." />
              </>
            )}
          </Status>
        </DashSection>

        <DashSection title="Ecological risk" to={`/ocean-map${mq({ layer: "risk" })}`} linkLabel="Show risk on the map" tag="derived">
          <Status isLoading={risk.isLoading} error={risk.error} hasData={!!R}>
            {R && (
              <>
                <Metric
                  label={<Term k="risk">Cells rated HIGH or CRITICAL</Term>}
                  value={share(2) == null ? "–" : `${share(2)!.toFixed(1)}%`}
                  note={`of ${counts.length.toLocaleString()} assessed cells in the ${R.region.name}. Cells without enough data are not rated.`}
                  meta={`Date ${R.date} · factors used: ${R.factors_used.join(", ")}${Object.keys(R.factors_unavailable).length ? ` · unavailable: ${Object.keys(R.factors_unavailable).join(", ")}` : ""}`}
                />
                <p className="text-xs text-slate-700">Unassessed cells: {(R.counts.insufficient_data + R.counts.unavailable).toLocaleString()} (not counted as low risk).</p>
              </>
            )}
          </Status>
        </DashSection>

        <DashSection title="Alerts" to={`/ocean-map${mq({ alerts: "1" })}`} linkLabel="Show alerts on the map" tag="derived">
          <Status isLoading={alerts.isLoading} error={alerts.error} hasData={!!alerts.data}>
            {alerts.data && (
              <>
                <Metric label="Open alerts" value={String(alerts.data.total)} note="New alerts for this dataset and region." meta={`Source ${src || "dataset alerts"}`} />
                <p className="text-xs text-slate-700">{alerts.data.items.filter((a) => a.severity === "HIGH" || a.severity === "CRITICAL").length} of the newest are HIGH or CRITICAL.</p>
              </>
            )}
          </Status>
        </DashSection>
      </div></div>

      <section className="mt-8" aria-labelledby="alerts-h">
        <div className="mb-3 flex items-baseline justify-between">
          <h2 id="alerts-h" className="border-l-4 border-orange-500 pl-3 text-lg font-semibold text-slate-900">Newest open alerts</h2>
          <Link to={`/alerts${q}`} className="text-sm font-semibold text-tide hover:underline">All alerts →</Link>
        </div>
        <Status isLoading={alerts.isLoading} error={alerts.error} hasData={!!alerts.data}>
          {alerts.data && alerts.data.items.length === 0 ? (
            <EmptyState title="No new alerts for this dataset and region">
              <p>Alerts are raised from marine-heatwave events and ecological-risk areas of the dataset. Run: python -m app.jobs publish-dataset-alerts --dataset {act.dataset}</p>
            </EmptyState>
          ) : (
            <div className="grid grid-cols-1 gap-3 lg:grid-cols-2">
              {alerts.data?.items.map((a: Alert) => (
                <Link key={a.id} to={`/alerts?open=${a.id}`} className="block rounded-lg" aria-label={`Open alert: ${a.message}`}>
                  <AlertCard alert={a} compact />
                </Link>
              ))}
            </div>
          )}
        </Status>
      </section>

    </div>
  );
}
