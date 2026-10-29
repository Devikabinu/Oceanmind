import { useEffect, useMemo, useState } from "react";
import type { ReactNode } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { Area, Bar, BarChart, CartesianGrid, ComposedChart, Legend, Line, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { getDatasets, getRegions as getEnvRegions } from "../api/environment";
import { getHeatwave, getHeatwaveMap, listHeatwaves } from "../api/intelligence";
import type { HeatwaveFootprint } from "../api/intelligence";
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
import { useActive } from "../contexts/ActiveSelection";
import ExplanationPanel from "../components/ExplanationPanel";
import HeatwaveHistory from "../components/HeatwaveHistory";
import RelatedLinks from "../components/RelatedLinks";
import { cached } from "../hooks/useCached";
import { providerLabel } from "../utils/format";
import LocationReport from "../components/LocationReport";
import { axisOrigin, extentToBounds, footprintToLayer } from "../utils/mapCoords";

const LEVEL_OF: Record<number, Level> = { 1: "MEDIUM", 2: "HIGH", 3: "CRITICAL", 4: "CRITICAL" };
const km2 = (v: number) => `${Math.round(v).toLocaleString()} km²`;
const LEGACY_DATASET = "ne_pacific";
/** Event ids carry their dataset: NE Pacific ids are mhw-<date>-<n>, other datasets mhw-<dataset>-<date>-<n>. Old links (alerts, dashboard) keep working. */
const datasetOfEvent = (id: string | null) => (id && id.startsWith("mhw-pacific-") ? "pacific" : id ? LEGACY_DATASET : null);
const place = (lat: number, lon180: number) => `${Math.abs(lat).toFixed(1)}°${lat >= 0 ? "N" : "S"}, ${Math.abs(lon180).toFixed(1)}°${lon180 < 0 ? "W" : "E"}`;
/** Longitude in -180..180 for display: Pacific datasets send lon_180; the NE export is already in -180..180. */
const centre = (e: HeatwaveEvent) => place(e.centroid.lat, e.centroid.lon_180 ?? e.centroid.lon);

function Stat({ label, value }: { label: ReactNode; value: ReactNode }) {
  return (
    <div className="rounded-md bg-slate-50 p-3">
      <div className="text-xs text-slate-600">{label}</div>
      <div className="mt-0.5 text-base font-semibold text-slate-900">{value}</div>
    </div>
  );
}

function Detail({ id, dataset, onFootprint }: { id: string; dataset: string; onFootprint?: (fp: HeatwaveFootprint | null) => void }) {
  const d = useAsync(() => getHeatwave(id, dataset), [id, dataset]);
  useEffect(() => {
    onFootprint?.(d.data && d.data.event.id === id ? d.data.footprint ?? null : null);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [d.data, id]);
  const generated = d.data?.provenance ? !d.data.provenance.is_observational : false;
  return (
    <Status isLoading={d.isLoading} error={d.error} hasData={!!d.data}>
      {d.data && (
        <div className="space-y-4 rounded-lg border border-slate-300 bg-white p-4">
          <div className="flex flex-wrap items-center gap-2">
            <h3 className="text-base font-semibold text-slate-900">Marine heatwave: {d.data.event.category_name}</h3>
            <SeverityBadge level={LEVEL_OF[d.data.event.category]} />
            <SourceTag kind="derived" />
            {generated && <SourceTag kind="generated" />}
          </div>
          <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
            <Stat label="Status" value={d.data.event.status} />
            <Stat label="Start date" value={d.data.event.start_date} />
            <Stat label="Duration" value={`${d.data.event.duration_days} days`} />
            <Stat label="Affected area" value={km2(d.data.event.area_km2)} />
            <Stat label="Current anomaly" value={`${d.data.event.current_anomaly_c > 0 ? "+" : ""}${d.data.event.current_anomaly_c.toFixed(1)} °C`} />
            <Stat label="Maximum anomaly" value={`${d.data.event.max_anomaly_c > 0 ? "+" : ""}${d.data.event.max_anomaly_c.toFixed(1)} °C`} />
            <Stat label="Cumulative intensity" value={d.data.event.cumulative_intensity_c_days != null ? `${d.data.event.cumulative_intensity_c_days.toFixed(0)} °C·days` : "n/a"} />
            <Stat label="Location (centre)" value={centre(d.data.event)} />
            <Stat label={<Term k="percentile">Historical percentile</Term>} value={`${d.data.event.historical_percentile.toFixed(0)}th`} />
            <Stat
              label="Forecast: still above threshold on day 7"
              value={d.data.event.forecast_still_above_p90_day7 == null ? "n/a" : `${(d.data.event.forecast_still_above_p90_day7 * 100).toFixed(0)}% of area`}
            />
          </div>
          {d.data.narrative && <ExplanationPanel explanation={d.data.narrative} title="Plain-language explanation of this event" />}
          <RelatedLinks point={{ lat: d.data.event.centroid.lat, lon: d.data.event.centroid.lon_180 ?? d.data.event.centroid.lon }} eventId={d.data.event.id} to={["map", "risk", "alerts"]} />
          <WhyPanel title="What does this mean?" reasons={d.data.explanation} classification={d.data.summary.method} sources={generated ? [`${d.data.provenance?.data_source} (modelled dataset)`] : ["NOAA OISST v2.1 (observed)", "ConvLSTM forecast (model output)"]} />
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
              <p className="text-xs text-slate-600">Area counts the cells of today&apos;s event that were in a heatwave state on each date; the anomaly is their average. Source: {generated ? "modelled dataset" : "NOAA OISST v2.1"} (derived).</p>
            </div>
          )}
          <div>
            <h4 className="text-sm font-semibold text-slate-900">Species with records in this area</h4>
            {d.data.species_in_area.length === 0 ? (
              <p className="mt-1 text-sm text-slate-600">Stored OBIS records are sparse in this area (last 2 years): a sampling gap, not evidence that no animals are present.</p>
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
            <p className="text-xs text-slate-600">The latest year covers observations to {d.data.summary.latest_date} only. Source: {generated ? "modelled dataset" : "NOAA OISST v2.1"}, project-level heatwave definition.</p>
          </div>
        </div>
      )}
    </Status>
  );
}

export default function Heatwaves() {
  const [params, setParams] = useSearchParams();
  const act = useActive();
  // an old link to an NE Pacific event switches the shared selection to the NE Pacific dataset
  const eventDataset = datasetOfEvent(params.get("event"));
  const datasetId = act.dataset;
  const setDatasetId = act.setDataset;
  const region = act.region;
  const setRegion = act.setRegion;
  useEffect(() => {
    if (eventDataset && eventDataset !== act.dataset && !new URLSearchParams(window.location.search).get("dataset")) act.setDataset(eventDataset);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [eventDataset]);
  const pacific = datasetId !== LEGACY_DATASET;
  const datasets = useAsync(() => cached("env-datasets", getDatasets), []);
  const regions = useAsync(() => cached("env-regions", getEnvRegions), []);
  const list = useAsync(() => listHeatwaves({ dataset: datasetId, region: pacific && region !== "pacific" ? region : undefined }), [datasetId, region, pacific]);
  const [minCat, setMinCat] = useState(1);
  const legacyMap = useAsync(() => (pacific ? Promise.resolve(null) : getMapLayer("heatwave", 1)), [pacific]);
  const pacMap = useAsync(() => (pacific ? getHeatwaveMap(datasetId, region, act.date ?? undefined) : Promise.resolve(null)), [pacific, datasetId, region, act.date]);
  const [point, setPoint] = useState<{ lat: number; lon: number } | null>(null);
  const [footprint, setFootprint] = useState<HeatwaveFootprint | null>(null);
  const selected = params.get("event");
  // results of another dataset or region must not be shown while the new ones load
  const freshList = list.data && !list.isLoading && (list.data.dataset ?? LEGACY_DATASET) === datasetId ? list.data : null;
  const freshMap = pacMap.data && !pacMap.isLoading && pacMap.data.dataset === datasetId && pacMap.data.region.id === region ? pacMap.data : null;
  const events: HeatwaveEvent[] = (freshList?.items ?? []).filter((e) => e.category >= minCat);
  const s = freshList?.summary;
  const generated = s ? s.is_observational === false : false;
  const regionInfo = regions.data?.regions.find((r) => r.id === region);
  const fitTo = useMemo(() => (pacific && regionInfo?.map_extent ? extentToBounds(regionInfo.map_extent) : null), [pacific, regionInfo]);
  const layer = pacific ? freshMap : legacyMap.data;

  function pick(id: string) {
    setParams({ event: id });
  }
  const field = "flex min-w-0 max-w-full flex-col gap-1 text-[11px] font-semibold uppercase tracking-[0.12em] text-cyan-100/90";
  const sel = "w-full min-w-0 max-w-full rounded-md border border-white/30 bg-white px-2 py-1.5 text-sm font-normal normal-case tracking-normal text-slate-900";

  return (
    <div>
      <PageHeader title="Marine heatwaves">
        Periods when sea surface temperature stays unusually high for days. This page lists the heatwave areas active on the latest date of the selected dataset, how long
        they have lasted, how strong they are and which species have records nearby, followed by the history of past events: when each began and ended, how it grew and where it lay.
      </PageHeader>
      <div className="on-deep mt-3 flex flex-wrap items-end gap-x-4 gap-y-3 rounded-xl bg-gradient-to-r from-deep via-abyss to-tide px-4 py-3 text-white">
        <label className={field}>
          Dataset
          <select
            className={sel}
            value={datasetId}
            onChange={(e) => {
              setDatasetId(e.target.value);
              setPoint(null);
              setParams({});
            }}
          >
            {datasets.data?.datasets.map((d) => (
              <option key={d.id} value={d.id} disabled={!d.available}>
                {d.name}
                {d.available ? "" : " (not available)"}
              </option>
            ))}
            {!datasets.data && <option value={datasetId}>{datasetId}</option>}
          </select>
        </label>
        {pacific && (
          <label className={field}>
            Region
            <select className={sel} value={region} onChange={(e) => setRegion(e.target.value)}>
              {!regionInfo && <option value={region}>{region}</option>}
              {regions.data?.regions.map((r) => (
                <option key={r.id} value={r.id}>
                  {r.parent && r.parent !== "pacific" ? "\u00a0\u00a0" : ""}
                  {r.name}
                </option>
              ))}
            </select>
          </label>
        )}
        {s && (
          <p className="flex flex-wrap items-center gap-x-3 gap-y-1 pb-1 text-xs text-cyan-50" data-testid="hw-meta">
            <span><span className="text-cyan-200/80">Latest date</span> <strong className="text-white">{s.latest_date}</strong></span>
            <span><span className="text-cyan-200/80">Baseline</span> <strong className="text-white">{s.baseline[0].slice(0, 4)}–{s.baseline[1].slice(0, 4)}</strong></span>
            <span className="text-cyan-200/80">{generated ? "Derived from the dataset SST" : "Derived from observations"}</span>
            {s.source && <span className="text-cyan-200/80">Source {providerLabel(s.source)}</span>}
          </p>
        )}
      </div>
      {s && act.date && act.date !== s.latest_date && (
        <div role="note" className="mt-3 rounded-md border border-slate-300 bg-slate-50 px-3 py-2 text-sm text-slate-800">
          {pacific
            ? <>The map shows heatwave cells on {act.date}. The list of current events below is for the latest date ({s.latest_date}); events in progress on {act.date} are listed in the history section.</>
            : <>Heatwave events are computed for the dataset&apos;s latest date ({s.latest_date}); the selected date ({act.date}) does not apply on this page.</>}
        </div>
      )}
      <div className="mt-3 rounded-md border border-amber-200 bg-amber-50 px-3 py-2 text-sm text-amber-900" role="note">
        <strong>Project-level indicator.</strong> <Term k="heatwave">Definition used here</Term>: SST above the seasonal 90th percentile for at least {s?.min_duration_days ?? 5} days, a simplified
        Hobday et al. (2016) method with a {s ? `${s.baseline[0].slice(0, 4)}–${s.baseline[1].slice(0, 4)}` : "12-year (2012–2023)"} baseline instead of 30 years. It is not an official marine-heatwave
        classification.
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

      <Status isLoading={list.isLoading} error={list.error} hasData={!!freshList} emptyMessage="No heatwave results were found for this dataset.">
        {s && (
          <>
            <div className="mt-4 grid grid-cols-1 gap-4 sm:grid-cols-2 xl:grid-cols-4">
              <KpiCard label="Active heatwave area" value={km2(s.active_area_km2)} hint={`${(s.active_share * 100).toFixed(1)}% of the ocean area, ${s.latest_date}`} tag="derived" />
              <KpiCard label="Separate areas" value={String(s.n_events)} hint={`at least ${s.min_event_cells} connected grid cells each`} tag="derived" />
              <KpiCard label="Compared with history" value={`${s.historical_rank_pct.toFixed(0)}th pct`} hint="share of earlier days in the record with a smaller heatwave area" tag="derived" />
              <KpiCard
                label={generated ? "Data through" : "Observed through"}
                value={s.latest_date}
                hint={generated ? `${s.source ? providerLabel(s.source) : "dataset"}` : "NOAA OISST v2.1"}
                tag={generated ? "generated" : "observed"}
              />
            </div>

            <div className="mt-6 grid grid-cols-1 gap-4 xl:grid-cols-3">
              <div className="xl:col-span-2">
                <SstMap
                  layer={layer}
                  events={pacific ? undefined : events}
                  overlay={pacific && footprint && selected ? footprintToLayer({ ...footprint, anomaly_c: footprint.lat.map(() => 1) }, selected) : null}
                  onEventClick={pick}
                  selected={point}
                  onPick={(lat, lon) => setPoint({ lat, lon })}
                  fitTo={fitTo}
                  lonOrigin={pacific && layer ? axisOrigin(layer.lon) : null}
                  showOutline={!pacific}
                  unavailable={pacific ? !!pacMap.error : !!legacyMap.error}
                  badge={pacific && freshMap ? `${freshMap.region.name} · ${freshMap.date}`: undefined}
                  initialView={pacific ? "world" : "study"}
                  ariaLabel="Marine heatwave map"
                />
                <p className="mt-1 text-xs text-slate-500">
                  Colour = anomaly (°C) inside heatwave areas. {pacific ? "Select an event in the list to outline its footprint (the cells it covers) on the map; click the map for the full report on a place." : "Dotted orange boxes outline each event; click one for details."}
                </p>
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
                            {e.current_anomaly_c > 0 ? "+" : ""}{e.current_anomaly_c.toFixed(1)} °C now (peak {e.max_anomaly_c.toFixed(1)}) near {centre(e)}
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
                <h3 className="mb-2 text-sm font-semibold text-slate-900">{pacific ? "Report for the clicked location" : "Environmental evidence at the clicked location"}</h3>
                {pacific ? (
                  <LocationReport point={point} dataset={datasetId} date={act.date} onClose={() => setPoint(null)} />
                ) : (
                  <LocationPanel point={point} />
                )}
              </div>
            )}

            <div className="mt-6">
              {selected && datasetOfEvent(selected) === datasetId ? <Detail id={selected} dataset={datasetId} onFootprint={setFootprint} /> : <p className="text-sm text-slate-600">Select a heatwave to see its explanation, species overlap and historical comparison.</p>}
            </div>
          </>
        )}
      </Status>

      {pacific && <HeatwaveHistory dataset={datasetId} region={region} onEvent={() => undefined} />}

      <div className="mt-8">
        <TrendCharts dataset={datasetId} />
      </div>
    </div>
  );
}
