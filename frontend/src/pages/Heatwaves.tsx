import { useState } from "react";
import type { ReactNode } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { Area, Bar, BarChart, CartesianGrid, ComposedChart, Legend, Line, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { getHeatwave, listHeatwaves } from "../api/intelligence";
import { getMapLayer } from "../api/monitor";
import type { HeatwaveEvent, Level } from "../api/monitor";
import EmptyState from "../components/EmptyState";
import KpiCard from "../components/KpiCard";
import LocationPanel from "../components/LocationPanel";
import PageHeader from "../components/PageHeader";
import SeverityBadge from "../components/SeverityBadge";
import SourceTag from "../components/SourceTag";
import SstMap from "../components/SstMap";
import Status from "../components/Status";
import Term from "../components/Term";
import TrendCharts from "../components/TrendCharts";
import WhyPanel from "../components/WhyPanel";
import { useAsync } from "../hooks/useAsync";

const LEVEL_OF: Record<number, Level> = { 1: "MEDIUM", 2: "HIGH", 3: "CRITICAL", 4: "CRITICAL" };
const km2 = (v: number) => `${Math.round(v).toLocaleString()} km²`;

function Stat({ label, value }: { label: ReactNode; value: ReactNode }) {
  return (
    <div className="rounded-md bg-slate-50 p-3">
      <div className="text-xs text-slate-600">{label}</div>
      <div className="mt-0.5 text-base font-semibold text-slate-900">{value}</div>
    </div>
  );
}

function Detail({ id }: { id: string }) {
  const d = useAsync(() => getHeatwave(id), [id]);
  return (
    <Status isLoading={d.isLoading} error={d.error} hasData={!!d.data}>
      {d.data && (
        <div className="space-y-4 rounded-lg border border-slate-300 bg-white p-4">
          <div className="flex flex-wrap items-center gap-2">
            <h3 className="text-base font-semibold text-slate-900">Marine heatwave: {d.data.event.category_name}</h3>
            <SeverityBadge level={LEVEL_OF[d.data.event.category]} />
            <SourceTag kind="derived" />
          </div>
          <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
            <Stat label="Status" value={d.data.event.status} />
            <Stat label="Start date" value={d.data.event.start_date} />
            <Stat label="Duration" value={`${d.data.event.duration_days} days`} />
            <Stat label="Affected area" value={km2(d.data.event.area_km2)} />
            <Stat label="Current anomaly" value={`${d.data.event.current_anomaly_c > 0 ? "+" : ""}${d.data.event.current_anomaly_c.toFixed(1)} °C`} />
            <Stat label="Maximum anomaly" value={`${d.data.event.max_anomaly_c > 0 ? "+" : ""}${d.data.event.max_anomaly_c.toFixed(1)} °C`} />
            <Stat label="Cumulative intensity" value={d.data.event.cumulative_intensity_c_days != null ? `${d.data.event.cumulative_intensity_c_days.toFixed(0)} °C·days` : "n/a"} />
            <Stat label="Location (centre)" value={`${d.data.event.centroid.lat.toFixed(1)}°N, ${Math.abs(d.data.event.centroid.lon).toFixed(1)}°W`} />
            <Stat label={<Term k="percentile">Historical percentile</Term>} value={`${d.data.event.historical_percentile.toFixed(0)}th`} />
            <Stat
              label="Forecast: still above threshold on day 7"
              value={d.data.event.forecast_still_above_p90_day7 == null ? "n/a" : `${(d.data.event.forecast_still_above_p90_day7 * 100).toFixed(0)}% of area`}
            />
          </div>
          <WhyPanel title="What does this mean?" reasons={d.data.explanation} classification={d.data.summary.method} sources={["NOAA OISST v2.1 (observed)", "ConvLSTM forecast (model output)"]} />
          {d.data.event.timeline && d.data.event.timeline.length > 0 && (
            <div>
              <h4 className="text-sm font-semibold text-slate-900">Timeline: last {d.data.event.timeline.length} days of this event&apos;s area</h4>
              <ResponsiveContainer width="100%" height={220}>
                <ComposedChart data={d.data.event.timeline} margin={{ top: 8, right: 16, bottom: 18, left: 4 }} aria-label="Event timeline">
                  <CartesianGrid strokeDasharray="3 3" stroke="#e2e8f0" />
                  <XAxis dataKey="date" tick={{ fontSize: 11 }} minTickGap={32} label={{ value: "Date", position: "insideBottom", offset: -10, fontSize: 11 }} />
                  <YAxis yAxisId="a" tick={{ fontSize: 11 }} width={56} label={{ value: "In heatwave (km²)", angle: -90, position: "insideLeft", fontSize: 11 }} />
                  <YAxis yAxisId="b" orientation="right" tick={{ fontSize: 11 }} width={44} label={{ value: "Anomaly (°C)", angle: 90, position: "insideRight", fontSize: 11 }} />
                  <Tooltip />
                  <Legend verticalAlign="top" wrapperStyle={{ fontSize: 11, paddingBottom: 8 }} />
                  <Area yAxisId="a" type="monotone" dataKey="area_km2" name="Area in heatwave state (km²)" stroke="#c2410c" fill="#fdba74" />
                  <Line yAxisId="b" type="monotone" dataKey="mean_anomaly_c" name="Mean anomaly (°C)" stroke="#7c2d12" strokeWidth={2} dot={false} />
                </ComposedChart>
              </ResponsiveContainer>
              <p className="text-xs text-slate-600">Area counts the cells of today&apos;s event that were in a heatwave state on each date; the anomaly is their average. Source: NOAA OISST v2.1 (derived).</p>
            </div>
          )}
          <div>
            <h4 className="text-sm font-semibold text-slate-900">Species with records in this area</h4>
            {d.data.species_in_area.length === 0 ? (
              <p className="mt-1 text-sm text-slate-600">No stored OBIS records fall inside this area&apos;s bounding box (last 2 years). That does not mean no animals are present.</p>
            ) : (
              <ul className="mt-1 divide-y divide-slate-100 text-sm">
                {d.data.species_in_area.map((s) => (
                  <li key={`${s.aphia_id}-${s.scientific_name}`} className="flex items-center justify-between py-1.5">
                    <span>
                      {s.aphia_id ? <Link to={`/species/${s.aphia_id}`} className="underline">{s.common_name ?? s.scientific_name}</Link> : s.scientific_name}
                      <span className="ml-2 text-xs text-slate-500">{s.taxon_group}</span>
                    </span>
                    <span className="text-xs text-slate-600">{s.n_records} records</span>
                  </li>
                ))}
              </ul>
            )}
            <p className="mt-1 text-xs text-slate-600">{d.data.species_note}</p>
          </div>
          <div>
            <h4 className="text-sm font-semibold text-slate-900">Historical comparison: largest heatwave area per year</h4>
            <ResponsiveContainer width="100%" height={220}>
              <BarChart
                data={Object.entries(d.data.yearly).map(([year, v]) => ({ year, max: Math.round(v.max_area_km2 / 1000), mean: Math.round(v.mean_area_km2 / 1000) }))}
                margin={{ top: 8, right: 12, bottom: 18, left: 4 }}
                aria-label="Marine heatwave area per year"
              >
                <CartesianGrid strokeDasharray="3 3" stroke="#e2e8f0" />
                <XAxis dataKey="year" tick={{ fontSize: 11 }} label={{ value: "Year", position: "insideBottom", offset: -10, fontSize: 11 }} />
                <YAxis tick={{ fontSize: 11 }} width={52} label={{ value: "Area (1000 km²)", angle: -90, position: "insideLeft", fontSize: 11 }} />
                <Tooltip formatter={(v) => `${Number(v).toLocaleString()} thousand km²`} />
                <Legend verticalAlign="top" wrapperStyle={{ fontSize: 11, paddingBottom: 8 }} />
                <Bar dataKey="max" name="Maximum on any day" fill="#ea580c" />
                <Bar dataKey="mean" name="Average over the year" fill="#fdba74" />
              </BarChart>
            </ResponsiveContainer>
            <p className="text-xs text-slate-600">2026 covers observations to date only. Source: NOAA OISST v2.1, project-level heatwave definition.</p>
          </div>
        </div>
      )}
    </Status>
  );
}

export default function Heatwaves() {
  const [params, setParams] = useSearchParams();
  const list = useAsync(() => listHeatwaves(), []);
  const [minCat, setMinCat] = useState(1);
  const map = useAsync(() => getMapLayer("heatwave", 1), []);
  const [point, setPoint] = useState<{ lat: number; lon: number } | null>(null);
  const selected = params.get("event");
  const events: HeatwaveEvent[] = (list.data?.items ?? []).filter((e) => e.category >= minCat);
  const s = list.data?.summary;

  function pick(id: string) {
    setParams({ event: id });
  }

  return (
    <div>
      <PageHeader title="Marine heatwaves">
        Periods when sea surface temperature stays unusually high for days. This page lists the heatwave areas active on the latest observed day, how long they have
        lasted, how strong they are and which species have records nearby.
      </PageHeader>
      <div className="mt-3 rounded-md border border-amber-200 bg-amber-50 px-3 py-2 text-sm text-amber-900" role="note">
        <strong>Project-level indicator.</strong> <Term k="heatwave">Definition used here</Term>: SST above the seasonal 90th percentile for at least 5 days, a simplified
        Hobday et al. (2016) method with a 12-year (2012–2023) baseline instead of 30 years. It is not an official marine-heatwave classification.
      </div>

      {s && (
        <div className="mt-3 rounded-md border border-slate-200 bg-white p-4">
          <p className="text-sm text-slate-800"><strong>What is a marine heatwave?</strong> {s.what_is}</p>
          <details className="mt-3" open>
            <summary className="cursor-pointer text-sm font-semibold text-slate-900">How is this detected?</summary>
            <ol className="mt-2 list-decimal space-y-1 pl-5 text-sm text-slate-700">{s.how_detected.map((h) => <li key={h}>{h}</li>)}</ol>
          </details>
        </div>
      )}

      <Status isLoading={list.isLoading} error={list.error} hasData={!!list.data} emptyMessage="No heatwave export was found. Generate it with: python -m oceanmind_model export-dashboard">
        {s && (
          <>
            <div className="mt-4 grid grid-cols-1 gap-4 sm:grid-cols-2 xl:grid-cols-4">
              <KpiCard label="Active heatwave area" value={km2(s.active_area_km2)} hint={`${(s.active_share * 100).toFixed(1)}% of the ocean area, ${s.latest_date}`} tag="derived" />
              <KpiCard label="Separate areas" value={String(s.n_events)} hint={`at least ${s.min_event_cells} connected grid cells each`} tag="derived" />
              <KpiCard label="Compared with history" value={`${s.historical_rank_pct.toFixed(0)}th pct`} hint="share of earlier days (since 2012) with a smaller heatwave area" tag="derived" />
              <KpiCard label="Observed through" value={s.latest_date} hint="NOAA OISST v2.1, processed study region" tag="observed" />
            </div>

            <div className="mt-6 grid grid-cols-1 gap-4 xl:grid-cols-3">
              <div className="xl:col-span-2">
                <SstMap layer={map.data} events={events} onEventClick={pick} selected={point} onPick={(lat, lon) => setPoint({ lat, lon })} ariaLabel="Marine heatwave map" />
                <p className="mt-1 text-xs text-slate-500">Colour = anomaly (°C) inside active heatwave areas. Dotted orange boxes outline each event; click one for details.</p>
              </div>
              <div>
                <div className="mb-2 flex items-center gap-2 text-sm">
                  <label htmlFor="mincat" className="text-slate-700">Minimum category</label>
                  <select id="mincat" value={minCat} onChange={(e) => setMinCat(Number(e.target.value))} className="rounded-md border border-slate-300 bg-white px-2 py-1 text-sm">
                    <option value={1}>I (Moderate) and above</option>
                    <option value={2}>II (Strong) and above</option>
                    <option value={3}>III (Severe) and above</option>
                    <option value={4}>IV (Extreme)</option>
                  </select>
                </div>
                {events.length === 0 ? (
                  <EmptyState title="No heatwave areas match">
                    <p>No connected area of {s.min_event_cells}+ grid cells is in a heatwave state at this category on {s.latest_date}.</p>
                  </EmptyState>
                ) : (
                  <ul className="space-y-2">
                    {events.map((e) => (
                      <li key={e.id}>
                        <button
                          type="button"
                          onClick={() => pick(e.id)}
                          aria-pressed={selected === e.id}
                          className={`w-full rounded-lg border p-3 text-left hover:border-slate-500 ${selected === e.id ? "border-slate-900 bg-slate-50" : "border-slate-200 bg-white"}`}
                        >
                          <div className="flex items-center justify-between gap-2">
                            <span className="text-sm font-semibold text-slate-900">{e.category_name}</span>
                            <SeverityBadge level={LEVEL_OF[e.category]} />
                          </div>
                          <div className="mt-1 text-xs text-slate-600">
                            ACTIVE · {e.duration_days} days since {e.start_date} · {km2(e.area_km2)}
                            <br />
                            {e.current_anomaly_c > 0 ? "+" : ""}{e.current_anomaly_c.toFixed(1)} °C now (peak {e.max_anomaly_c.toFixed(1)}) near {e.centroid.lat.toFixed(1)}°N,{" "}
                            {Math.abs(e.centroid.lon).toFixed(1)}°W
                          </div>
                        </button>
                      </li>
                    ))}
                  </ul>
                )}
              </div>
            </div>

            {point && (
              <div className="mt-6">
                <h3 className="mb-2 text-sm font-semibold text-slate-900">Environmental evidence at the clicked location</h3>
                <LocationPanel point={point} />
              </div>
            )}

            <div className="mt-6">
              {selected ? <Detail id={selected} /> : <p className="text-sm text-slate-600">Select a heatwave to see its explanation, species overlap and historical comparison.</p>}
            </div>
          </>
        )}
      </Status>

      <div className="mt-8">
        <TrendCharts />
      </div>
    </div>
  );
}
