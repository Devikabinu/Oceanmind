import { useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { CartesianGrid, ComposedChart, Legend, Line, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { getAnomalyAnalysis, getMap, getRegions } from "../api/environment";
import type { AnomalyCell, PersistentAnomaly } from "../api/environment";
import { useActive } from "../contexts/ActiveSelection";
import { useAsync } from "../hooks/useAsync";
import { cached } from "../hooks/useCached";
import { axisOrigin, extentToBounds, toMapLayer } from "../utils/mapCoords";
import ContextBar from "./ContextBar";
import KpiCard from "./KpiCard";
import LocationReport from "./LocationReport";
import PageHeader from "./PageHeader";
import SstMap from "./SstMap";
import Status from "./Status";

const signed = (v: number | null | undefined, d = 1) => (v == null ? "–" : `${v > 0 ? "+" : ""}${v.toFixed(d)}`);
const place = (lat: number, lon180: number) => `${Math.abs(lat).toFixed(1)}°${lat >= 0 ? "N" : "S"}, ${Math.abs(lon180).toFixed(1)}°${lon180 < 0 ? "W" : "E"}`;
const pct = (v: number | null | undefined) => (v == null ? "–" : `${(v * 100).toFixed(1)}%`);

/** Percentile in plain words for an anomaly of either sign. */
function unusual(c: AnomalyCell): string {
  if (c.historical_percentile == null) return "Insufficient history to rank";
  const tail = c.anomaly_c >= 0 ? 100 - c.historical_percentile : c.historical_percentile;
  const side = c.anomaly_c >= 0 ? "warmer" : "colder";
  return `${side} than ${(100 - tail).toFixed(0)}% of ${c.historical_samples.toLocaleString()} comparable days`;
}

/** The Pacific anomalies product: the anomaly map and, around it, what is strongest, what has lasted, how the region has moved and how regions compare. Clicking the map
 *  opens the same location report as the Ocean Map (what it is, how unusual, how long, what goes with it, what it may mean for ecosystems). */
export default function PacificAnomalies() {
  const act = useActive();
  const [point, setPoint] = useState<{ lat: number; lon: number } | null>(null);
  const analysis = useAsync(() => getAnomalyAnalysis(act.dataset, act.region, act.date ?? undefined), [act.dataset, act.region, act.date]);
  const A = analysis.data && !analysis.isLoading && analysis.data.dataset.id === act.dataset && analysis.data.region.id === act.region ? analysis.data : null;
  const map = useAsync(() => getMap({ dataset: act.dataset, layer: "anomaly", date: act.date ?? "latest", region: "pacific" }), [act.dataset, act.date]);
  const M = map.data && !map.isLoading && map.data.dataset.id === act.dataset && map.data.layer === "anomaly" ? map.data : null;
  const regions = useAsync(() => cached("env-regions", getRegions), []);
  const regionInfo = regions.data?.regions.find((r) => r.id === act.region);
  const fitTo = useMemo(() => (regionInfo?.map_extent ? extentToBounds(regionInfo.map_extent) : null), [regionInfo]);
  const layer = M ? toMapLayer(M) : null;
  const timeline = useMemo(() => (A ? A.timeline.dates.map((d, i) => ({ date: d, mean: A.timeline.mean_anomaly_c[i], warm: +(A.timeline.share_warm[i] * 100).toFixed(1), cold: +(A.timeline.share_cold[i] * 100).toFixed(1) })) : []), [A]);

  const mapLink = (lat: number, lon: number, layerId = "anomaly") => `/ocean-map${act.toQuery({ layer: layerId, lat, lon })}`;

  return (
    <div>
      <PageHeader title="SST anomalies">
        How far sea surface temperature is from the expected value for the time of year. Select a region and date, read what is strongest and what has lasted, and click the map for the
        full report on any place.
      </PageHeader>
      <div className="mt-3"><ContextBar showDate note="Region and date are shared with the Ocean Map, Marine Heatwaves and Ecological Risk." /></div>

      <Status isLoading={analysis.isLoading} error={analysis.error} hasData={!!A}>
        {A && (
          <>
            <div className="mt-4 grid grid-cols-1 gap-4 sm:grid-cols-2 xl:grid-cols-4">
              <KpiCard label="Mean anomaly" value={`${signed(A.summary.mean_anomaly_c, 2)} °C`} hint={`${A.region.name}, ${A.date}`} tag="derived" />
              <KpiCard label="Unusually warm" value={pct(A.summary.share_warm)} hint={`share of cells at least ${A.threshold_c.toFixed(0)} °C above normal`} tag="derived" />
              <KpiCard label="Unusually cold" value={pct(A.summary.share_cold)} hint={`share of cells at least ${A.threshold_c.toFixed(0)} °C below normal`} tag="derived" />
              <KpiCard label="Persistent anomalies" value={A.summary.persistent_cells.toLocaleString()} hint={`cells beyond ${A.threshold_c.toFixed(0)} °C for ${A.persistence_min_days}+ days (${pct(A.summary.persistent_share)})`} tag="derived" />
            </div>

            <div className="mt-6 grid grid-cols-1 gap-4 xl:grid-cols-[minmax(0,1fr)_25rem]">
              <div>
                <SstMap layer={layer} selected={point} onPick={(la, lo) => setPoint({ lat: la, lon: lo })} fitTo={fitTo} lonOrigin={layer ? axisOrigin(layer.lon) : null} showOutline={false}
                  edgeFade={3} initialView="world" unavailable={!!map.error} badge={layer ? `${A.region.name} · ${layer.date}` : undefined} heightClass="h-[28rem]" ariaLabel="Pacific SST anomaly map" />
                <p className="mt-1 text-xs text-slate-600">Colour = anomaly in °C from the baseline{A.baseline ? ` (${A.baseline[0].slice(0, 4)} to ${A.baseline[1].slice(0, 4)})` : ""}. Grey cells have no data. Click any ocean cell.</p>
              </div>
              <LocationReport point={point} dataset={act.dataset} date={act.date} onClose={() => setPoint(null)} onFocus={(la, lo) => setPoint({ lat: la, lon: lo > 180 ? lo - 360 : lo })} />
            </div>

            <div className="mt-6 grid grid-cols-1 gap-4 lg:grid-cols-2">
              {([["Strongest warm anomalies", A.strongest_warm], ["Strongest cold anomalies", A.strongest_cold]] as [string, AnomalyCell[]][]).map(([title, cells]) => (
                <section key={title} className="rounded-lg border border-slate-200 bg-white p-4" aria-label={title}>
                  <h2 className="text-sm font-semibold text-slate-900">{title}</h2>
                  {cells.length === 0 ? <p className="mt-1 text-sm text-slate-600">No cells beyond normal on this side on {A.date}.</p> : (
                    <ol className="mt-2 divide-y divide-slate-100 text-sm">
                      {cells.map((c) => (
                        <li key={`${c.lat}-${c.lon}`} className="py-1.5">
                          <div className="flex items-center justify-between gap-2">
                            <button type="button" className="text-left font-semibold text-tide hover:underline" onClick={() => setPoint({ lat: c.lat, lon: c.lon_180 })}>{signed(c.anomaly_c)} °C · {place(c.lat, c.lon_180)}</button>
                            <span className="text-xs text-slate-600">{c.region.name}</span>
                          </div>
                          <div className="text-xs text-slate-600">{unusual(c)}</div>
                        </li>
                      ))}
                    </ol>
                  )}
                </section>
              ))}
            </div>

            <section className="mt-4 rounded-lg border border-slate-200 bg-white p-4" aria-label="Persistent anomalies">
              <h2 className="text-sm font-semibold text-slate-900">Anomalies that have lasted</h2>
              {A.persistent.length === 0 ? <p className="mt-1 text-sm text-slate-600">No cell has stayed beyond {A.threshold_c.toFixed(0)} °C for {A.persistence_min_days} or more days up to {A.date}.</p> : (
                <ul className="mt-2 divide-y divide-slate-100 text-sm">
                  {A.persistent.map((p: PersistentAnomaly) => (
                    <li key={`${p.lat}-${p.lon}`} className="flex flex-wrap items-center justify-between gap-2 py-1.5">
                      <button type="button" className="text-left font-semibold text-tide hover:underline" onClick={() => setPoint({ lat: p.lat, lon: p.lon_180 })}>{p.direction === "warm" ? "Warm" : "Cold"} {signed(p.anomaly_c)} °C · {place(p.lat, p.lon_180)}</button>
                      <span className="text-xs text-slate-600">{p.capped ? `at least ${p.days}` : p.days} consecutive days · {p.region.name}</span>
                      <Link className="text-xs font-semibold text-tide hover:underline" to={mapLink(p.lat, p.lon_180)}>Ocean Map →</Link>
                    </li>
                  ))}
                </ul>
              )}
            </section>

            <section className="mt-4 rounded-lg border border-slate-200 bg-white p-4" aria-label="Anomaly timeline">
              <h2 className="text-sm font-semibold text-slate-900">Anomaly timeline: {A.region.name}</h2>
              <ResponsiveContainer width="100%" height={240}>
                <ComposedChart data={timeline} margin={{ top: 8, right: 16, bottom: 18, left: 4 }} aria-label="Regional anomaly timeline">
                  <CartesianGrid strokeDasharray="3 3" stroke="#e2e8f0" />
                  <XAxis dataKey="date" tick={{ fontSize: 11 }} minTickGap={40} />
                  <YAxis yAxisId="a" tick={{ fontSize: 11 }} width={44} label={{ value: "Mean anomaly (°C)", angle: -90, position: "insideLeft", fontSize: 11 }} />
                  <YAxis yAxisId="b" orientation="right" tick={{ fontSize: 11 }} width={44} label={{ value: "Share of cells (%)", angle: 90, position: "insideRight", fontSize: 11 }} />
                  <Tooltip />
                  <Legend verticalAlign="top" wrapperStyle={{ fontSize: 11, paddingBottom: 8 }} />
                  <Line yAxisId="a" type="monotone" dataKey="mean" name="Mean anomaly (°C)" stroke="#0f766e" strokeWidth={2} dot={false} />
                  <Line yAxisId="b" type="monotone" dataKey="warm" name={`≥ +${A.threshold_c.toFixed(0)} °C (% of cells)`} stroke="#c2410c" dot={false} />
                  <Line yAxisId="b" type="monotone" dataKey="cold" name={`≤ −${A.threshold_c.toFixed(0)} °C (% of cells)`} stroke="#1d4ed8" dot={false} />
                </ComposedChart>
              </ResponsiveContainer>
            </section>

            <section className="mt-4 rounded-lg border border-slate-200 bg-white p-4" aria-label="Regional comparison">
              <h2 className="text-sm font-semibold text-slate-900">Regional comparison on {A.date}</h2>
              <div className="mt-2 overflow-x-auto">
                <table className="w-full min-w-[28rem] text-left text-sm">
                  <thead><tr className="text-xs text-slate-600"><th scope="col" className="py-1 pr-3">Region</th><th scope="col" className="pr-3">Mean anomaly</th><th scope="col" className="pr-3">Unusually warm</th><th scope="col" className="pr-3">Unusually cold</th><th scope="col">Cells</th></tr></thead>
                  <tbody>
                    {A.regions.map((r) => (
                      <tr key={r.id} className={`border-t border-slate-100 ${r.id === A.region.id ? "bg-teal-50" : ""}`}>
                        <td className="py-1 pr-3"><button type="button" className="font-medium text-tide hover:underline" onClick={() => act.setRegion(r.id)}>{r.name}</button></td>
                        <td className="pr-3">{signed(r.mean_anomaly_c, 2)} °C</td><td className="pr-3">{pct(r.share_warm)}</td><td className="pr-3">{pct(r.share_cold)}</td><td>{r.valid_cells.toLocaleString()}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </section>

            <div className="mt-4 rounded-md border border-slate-200 bg-slate-50 p-3 text-xs text-slate-700">
              <p><strong>Method.</strong> {A.method}</p>
              {A.limits.map((l) => <p key={l} className="mt-1">{l}</p>)}
              <p className="mt-1">Data source: <Link className="underline" to="/ocean-data">{A.dataset.name}</Link> · latest date {A.latest_available_date}.</p>
            </div>
          </>
        )}
      </Status>
    </div>
  );
}
