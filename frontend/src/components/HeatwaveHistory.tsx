import { useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { Area, CartesianGrid, ComposedChart, Legend, Line, ReferenceLine, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { getHeatwaveHistoryEvent, getHeatwaveMap, listHeatwaveHistory } from "../api/intelligence";
import type { HistoricalEvent } from "../api/intelligence";
import { useAsync } from "../hooks/useAsync";
import { axisOrigin, footprintToLayer } from "../utils/mapCoords";
import SeverityBadge from "./SeverityBadge";
import SourceTag from "./SourceTag";
import SstMap from "./SstMap";
import Status from "./Status";
import type { Level } from "../api/monitor";

const LEVEL_OF: Record<number, Level> = { 1: "MEDIUM", 2: "HIGH", 3: "CRITICAL", 4: "CRITICAL" };
const km2 = (v: number) => `${Math.round(v).toLocaleString()} km²`;
const place = (lat: number, lon180: number) => `${Math.abs(lat).toFixed(1)}°${lat >= 0 ? "N" : "S"}, ${Math.abs(lon180).toFixed(1)}°${lon180 < 0 ? "W" : "E"}`;
const field = "flex flex-col gap-1 text-[11px] font-semibold uppercase tracking-[0.12em] text-slate-600";
const sel = "rounded-md border border-slate-300 bg-white px-2 py-1.5 text-sm font-normal normal-case tracking-normal text-slate-900";

/** Past and current marine-heatwave events of the whole record: filter, open one, scrub through its evolution and see its footprint on the map for any day. */
export default function HeatwaveHistory({ dataset, region, onEvent }: { dataset: string; region: string; onEvent?: (id: string) => void }) {
  const [year, setYear] = useState<string>("");
  const [minCat, setMinCat] = useState(1);
  const [status, setStatus] = useState("");
  const [sort, setSort] = useState("start");
  const [openId, setOpenId] = useState<string | null>(null);
  const [day, setDay] = useState<string | null>(null);

  const list = useAsync(
    () => listHeatwaveHistory({ dataset, region: region !== "pacific" ? region : undefined, year: year || undefined, min_category: minCat, status: status || undefined, sort, limit: 200 }),
    [dataset, region, year, minCat, status, sort],
  );
  const fresh = list.data && !list.isLoading && list.data.dataset === dataset ? list.data : null;
  const detail = useAsync(() => (openId ? getHeatwaveHistoryEvent(openId, dataset, day ?? undefined) : Promise.resolve(null)), [openId, dataset, day]);
  const d = detail.data && !detail.isLoading && detail.data.event.id === openId ? detail.data : null;
  const dayShown = d?.footprint.date ?? null;
  const base = useAsync(() => (dayShown ? getHeatwaveMap(dataset, "pacific", dayShown) : Promise.resolve(null)), [dataset, dayShown]);
  const baseFresh = base.data && !base.isLoading && base.data.date === dayShown ? base.data : null;
  const overlay = useMemo(() => (d ? footprintToLayer(d.footprint, d.event.id) : null), [d]);
  const cov = baseFresh?.coverage;
  // the whole dataset extent, so the map opens on the data (they sit on the continuous east-longitude axis) and does not move when the footprint day changes
  const fitTo = useMemo<[[number, number], [number, number]] | null>(() => (cov ? [[cov.lat_min, cov.lon_min], [cov.lat_max, cov.lon_max]] : null), [cov?.lat_min, cov?.lat_max, cov?.lon_min, cov?.lon_max]);
  const chart = useMemo(() => (d ? d.evolution.dates.map((t, i) => ({ date: t, area: d.evolution.area_km2[i], anomaly: d.evolution.mean_anomaly_c[i] })) : []), [d]);

  function open(e: HistoricalEvent) {
    setOpenId(e.id);
    setDay(null);
    onEvent?.(e.id);
  }

  return (
    <section className="mt-8" aria-labelledby="hw-history-title">
      <h2 id="hw-history-title" className="text-lg font-semibold text-slate-900">Heatwave history</h2>
      <p className="mt-1 text-sm text-slate-700">
        Every marine-heatwave event in the record, current and past. An event is a group of heatwave cells that touch each other from one day to the next; an event that crosses the
        180° meridian is one event. Select one to see how it grew and faded and where it lay on any of its days.
      </p>
      <div className="mt-3 flex flex-wrap items-end gap-3 rounded-md border border-slate-200 bg-white p-3">
        <label className={field}>Year
          <select className={sel} value={year} onChange={(e) => setYear(e.target.value)} aria-label="Year">
            <option value="">All years</option>
            {fresh && Object.entries(fresh.by_start_year).map(([y, n]) => <option key={y} value={y}>{y} ({n} start{n === 1 ? "s" : ""})</option>)}
          </select>
        </label>
        <label className={field}>Minimum category
          <select className={sel} value={minCat} onChange={(e) => setMinCat(Number(e.target.value))} aria-label="Minimum category">
            <option value={1}>I (Moderate) and above</option><option value={2}>II (Strong) and above</option><option value={3}>III (Severe) and above</option><option value={4}>IV (Extreme)</option>
          </select>
        </label>
        <label className={field}>Status
          <select className={sel} value={status} onChange={(e) => setStatus(e.target.value)} aria-label="Status">
            <option value="">Current and past</option><option value="ACTIVE">Current only</option><option value="ENDED">Past only</option>
          </select>
        </label>
        <label className={field}>Sort by
          <select className={sel} value={sort} onChange={(e) => setSort(e.target.value)} aria-label="Sort by">
            <option value="start">Most recent first</option><option value="duration">Longest</option><option value="area">Largest area</option><option value="intensity">Strongest anomaly</option>
          </select>
        </label>
        {fresh && <p className="pb-1 text-xs text-slate-600">{fresh.total} event{fresh.total === 1 ? "" : "s"} · record {fresh.first_date} to {fresh.last_date}</p>}
      </div>

      <Status isLoading={list.isLoading} error={list.error} hasData={!!fresh} emptyMessage="Historical events are not available for this dataset.">
        {fresh && (
          <div className="mt-3 grid grid-cols-1 gap-4 xl:grid-cols-[minmax(0,22rem)_minmax(0,1fr)]">
            <div>
              {fresh.items.length === 0 ? (
                <p className="rounded-md border border-slate-200 bg-white p-3 text-sm text-slate-700">No event matches these filters.</p>
              ) : (
                <ul className="max-h-[34rem] space-y-2 overflow-y-auto pr-1" aria-label="Historical heatwave events">
                  {fresh.items.map((e) => (
                    <li key={e.id}>
                      <button type="button" onClick={() => open(e)} aria-pressed={openId === e.id}
                        className={`w-full rounded-lg border p-3 text-left hover:border-slate-500 ${openId === e.id ? "border-slate-900 bg-slate-50" : "border-slate-200 bg-white"}`}>
                        <div className="flex items-center justify-between gap-2">
                          <span className="text-sm font-semibold text-slate-900">{e.category_name}</span>
                          <span className="flex items-center gap-1.5">
                            {e.status === "ACTIVE" && <span className="rounded bg-orange-100 px-1.5 py-0.5 text-[11px] font-semibold text-orange-900">Current</span>}
                            <SeverityBadge level={LEVEL_OF[e.category]} />
                          </span>
                        </div>
                        <div className="mt-1 text-xs text-slate-600">
                          {e.start_date} to {e.end_date} · {e.duration_days} days · peak {km2(e.peak_area_km2)} on {e.peak_date}
                          <br />
                          {e.max_anomaly_c > 0 ? "+" : ""}{e.max_anomaly_c.toFixed(1)} °C at its strongest · near {place(e.centroid.lat, e.centroid.lon_180)}
                        </div>
                      </button>
                    </li>
                  ))}
                </ul>
              )}
              <p className="mt-2 text-xs text-slate-600">{fresh.note}</p>
            </div>

            <div>
              {!openId && <p className="rounded-md border border-slate-200 bg-white p-3 text-sm text-slate-700">Select an event to see its evolution and footprint.</p>}
              {openId && (
                <Status isLoading={detail.isLoading} error={detail.error} hasData={!!d}>
                  {d && (
                    <div className="space-y-3 rounded-lg border border-slate-300 bg-white p-4" aria-label="Historical event detail">
                      <div className="flex flex-wrap items-center gap-2">
                        <h3 className="text-base font-semibold text-slate-900">{d.event.category_name} · {d.event.start_date} to {d.event.end_date}</h3>
                        <SourceTag kind="derived" />
                        {d.event.status === "ACTIVE" && <span className="rounded bg-orange-100 px-1.5 py-0.5 text-xs font-semibold text-orange-900">Current event</span>}
                      </div>
                      <dl className="grid grid-cols-2 gap-2 text-sm md:grid-cols-4">
                        {[["Duration", `${d.event.duration_days} days`], ["Peak date", d.event.peak_date], ["Largest area", km2(d.event.peak_area_km2)],
                          ["Strongest anomaly", `${d.event.max_anomaly_c > 0 ? "+" : ""}${d.event.max_anomaly_c.toFixed(1)} °C`], ["Mean anomaly", `${d.event.mean_anomaly_c > 0 ? "+" : ""}${d.event.mean_anomaly_c.toFixed(1)} °C`],
                          ["Cumulative intensity", `${d.event.cumulative_intensity_c_days.toFixed(0)} °C·days per cell`], ["Centre", place(d.event.centroid.lat, d.event.centroid.lon_180)], ["Category", d.event.category_name]].map(([k, v]) => (
                          <div key={k} className="rounded-md bg-slate-50 p-2"><dt className="text-xs text-slate-600">{k}</dt><dd className="font-semibold text-slate-900">{v}</dd></div>
                        ))}
                      </dl>
                      <ul className="list-disc space-y-1 pl-5 text-sm text-slate-700">{d.explanation.map((t) => <li key={t}>{t}</li>)}</ul>
                      <div>
                        <h4 className="text-sm font-semibold text-slate-900">How it evolved</h4>
                        <ResponsiveContainer width="100%" height={200}>
                          <ComposedChart data={chart} margin={{ top: 8, right: 16, bottom: 18, left: 4 }} aria-label="Event evolution">
                            <CartesianGrid strokeDasharray="3 3" stroke="#e2e8f0" />
                            <XAxis dataKey="date" tick={{ fontSize: 11 }} minTickGap={32} />
                            <YAxis yAxisId="a" tick={{ fontSize: 11 }} width={56} label={{ value: "Area (km²)", angle: -90, position: "insideLeft", fontSize: 11 }} />
                            <YAxis yAxisId="b" orientation="right" tick={{ fontSize: 11 }} width={44} label={{ value: "Anomaly (°C)", angle: 90, position: "insideRight", fontSize: 11 }} />
                            <Tooltip />
                            <Legend verticalAlign="top" wrapperStyle={{ fontSize: 11, paddingBottom: 8 }} />
                            <Area yAxisId="a" type="monotone" dataKey="area" name="Area in heatwave (km²)" stroke="#c2410c" fill="#fdba74" />
                            <Line yAxisId="b" type="monotone" dataKey="anomaly" name="Mean anomaly (°C)" stroke="#7c2d12" strokeWidth={2} dot={false} />
                            {dayShown && <ReferenceLine yAxisId="a" x={dayShown} stroke="#0f172a" strokeDasharray="4 3" />}
                          </ComposedChart>
                        </ResponsiveContainer>
                        <label className="mt-1 flex items-center gap-2 text-xs text-slate-700">
                          Footprint on
                          <input type="range" aria-label="Footprint date" min={0} max={d.evolution.dates.length - 1} value={Math.max(0, d.evolution.dates.indexOf(dayShown ?? ""))}
                            onChange={(e) => setDay(d.evolution.dates[Number(e.target.value)])} className="min-w-0 flex-1" />
                          <strong>{dayShown}</strong>
                        </label>
                      </div>
                      <div>
                        <SstMap layer={baseFresh ? { ...baseFresh, layer: "heatwave", kind: "derived" } : null} overlay={overlay} lonOrigin={baseFresh ? axisOrigin(baseFresh.lon) : null}
                          showOutline={false} edgeFade={3} initialView="world" fitTo={fitTo} badge={dayShown ? `Footprint · ${dayShown}` : undefined} heightClass="h-[22rem]" ariaLabel="Historical heatwave footprint map" />
                        <p className="mt-1 text-xs text-slate-600">Dark-rimmed cells: this event on {dayShown} ({d.footprint.cells.toLocaleString()} cells). Other heatwave cells on that day are shown in colour.</p>
                      </div>
                      <div className="flex flex-wrap gap-3 text-sm">
                        <Link className="font-semibold text-tide hover:underline" to={`/ocean-map?dataset=${dataset}&date=${dayShown}&layer=heatwave&lat=${d.event.centroid.lat}&lon=${d.event.centroid.lon_180}`}>Show on the Ocean Map →</Link>
                        <Link className="font-semibold text-tide hover:underline" to={`/ecological-risk?dataset=${dataset}&date=${d.event.status === "ACTIVE" ? "" : dayShown}`}>Ecological risk →</Link>
                        {d.current_event_ids?.map((id) => <Link key={id} className="font-semibold text-tide hover:underline" to={`/heatwaves?dataset=${dataset}&event=${id}`}>Current event detail and forecast →</Link>)}
                      </div>
                      <div>
                        <h4 className="text-sm font-semibold text-slate-900">Species with records in this area</h4>
                        {d.species_in_area.length === 0 ? (
                          <p className="text-sm text-slate-600">No records were available in this dataset in the cells this event covered on {dayShown}. That is insufficient biodiversity coverage, not evidence that no animals were present.</p>
                        ) : (
                          <ul className="mt-1 divide-y divide-slate-100 text-sm">
                            {d.species_in_area.slice(0, 8).map((s) => (
                              <li key={`${s.aphia_id}-${s.scientific_name}`} className="flex justify-between py-1">
                                <span>{s.aphia_id ? <Link to={`/species/${s.aphia_id}`} className="underline">{s.common_name ?? s.scientific_name}</Link> : s.scientific_name}{s.iucn_category && <span className="ml-2 text-xs text-slate-500">{s.iucn_category}</span>}</span>
                                <span className="text-xs text-slate-600">{s.n_records} records</span>
                              </li>
                            ))}
                          </ul>
                        )}
                        <p className="mt-1 text-xs text-slate-600">{d.species_note ?? "Record locations are potential exposure only; records show where animals were observed, not their range."}</p>
                      </div>
                    </div>
                  )}
                </Status>
              )}
            </div>
          </div>
        )}
      </Status>
    </section>
  );
}
