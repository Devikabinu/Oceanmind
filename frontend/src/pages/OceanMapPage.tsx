import { providerLabel } from "../utils/format";
import { useEffect, useMemo, useState } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import { getDates, getDatasets, getForecastMap, getMap, getRegions, getSpeciesLayer } from "../api/environment";
import { getHeatwaveMap, getRiskMap, getSpeciesDistribution, listHeatwaves, listSpecies } from "../api/intelligence";
import { listAlerts } from "../api/modelOutputs";
import type { MapLayer } from "../api/monitor";
import LocationReport from "../components/LocationReport";
import DataDatesNote from "../components/DataDatesNote";
import SstMap from "../components/SstMap";
import type { MapMarker } from "../components/SstMap";
import { useActive } from "../contexts/ActiveSelection";
import { useAsync } from "../hooks/useAsync";
import { cached } from "../hooks/useCached";
import { axisOrigin, extentToBounds, riskToMapLayer, toMapLayer } from "../utils/mapCoords";

type Base = "sst" | "anomaly" | "heatwave" | "risk" | "forecast_sst" | "forecast_anomaly";
const GROUPS: { title: string; ids: Base[] }[] = [
  { title: "Observed", ids: ["sst", "anomaly"] },
  { title: "Derived indicators", ids: ["heatwave", "risk"] },
  { title: "Model output", ids: ["forecast_sst", "forecast_anomaly"] },
];
const BASES: { id: Base; label: string; hint: string }[] = [
  { id: "sst", label: "SST", hint: "How warm is the ocean?" },
  { id: "anomaly", label: "Anomaly", hint: "Difference from normal" },
  { id: "heatwave", label: "Marine heatwaves", hint: "Active footprints" },
  { id: "risk", label: "Ecological risk", hint: "Risk level per cell" },
  { id: "forecast_sst", label: "Forecast SST", hint: "Predicted temperature" },
  { id: "forecast_anomaly", label: "Forecast anomaly", hint: "Predicted departure" },
];
const CONS_COLOR: Record<string, string> = { CR: "#b91c1c", EN: "#ea580c", VU: "#ca8a04", NT: "#65a30d", LC: "#16a34a" };
const SEV_COLOR: Record<string, string> = { CRITICAL: "#7f1d1d", HIGH: "#c2410c", MEDIUM: "#ca8a04", LOW: "#0369a1" };
/** Conservation-status filter of the species overlay: status codes (IUCN categories as reported by the species source) each option keeps. */
const STATUS_FILTERS: Record<string, string[]> = { THREATENED: ["CR", "EN", "VU"], CR: ["CR"], EN: ["EN"], VU: ["VU"], NT: ["NT"] };
const SEV_RANK: Record<string, number> = { LOW: 0, MEDIUM: 1, HIGH: 2, CRITICAL: 3 };
const STATE_COLORS: Record<number, [number, number, number, number]> = { 1: [236, 236, 236, 235], 2: [58, 58, 58, 235] };
const STATE_LABELS: Record<number, string> = { 1: "not assessed: no SST anomaly", 2: "unavailable: no data this day", 3: "land", 4: "outside the selected region" };
const field = "flex min-w-0 max-w-full flex-col gap-1 text-[11px] font-semibold uppercase tracking-[0.12em] text-cyan-100/90";
const sel = "w-full min-w-0 max-w-full rounded-md border border-white/30 bg-white px-2 py-1.5 text-sm font-normal normal-case tracking-normal text-slate-900";
const LEGACY = "ne_pacific";

/** The Ocean Map: ONE map for the whole Pacific with every layer (SST, anomaly, marine heatwaves, ecological risk, forecast), species and alerts on top, and ONE report panel
 *  for whatever place is clicked. Dataset, region and date are the shared selection of the application. */
export default function OceanMapPage() {
  const act = useActive();
  const navigate = useNavigate();
  const [qs] = useSearchParams();
  const initialBase = (qs.get("layer") as Base | null) ?? "sst";
  const [base, setBase] = useState<Base>(BASES.some((b) => b.id === initialBase) ? initialBase : "sst");
  const [showSpecies, setShowSpecies] = useState(qs.get("species") === "1");
  const [showAlerts, setShowAlerts] = useState(qs.get("alerts") === "1");
  const [showOutlines, setShowOutlines] = useState(qs.get("outlines") !== "0");
  const [horizon, setHorizon] = useState(7);
  const [controlsOpen, setControlsOpen] = useState(false);
  const [statusFilter, setStatusFilter] = useState<string>(qs.get("status") ?? "THREATENED");
  const [limitToRegion, setLimitToRegion] = useState(false);
  const [minSeverity, setMinSeverity] = useState<string>(qs.get("severity") ?? "ALL");
  const [densityId, setDensityId] = useState<number | null>(null);
  const selected = act.point;                                  // shared with the dashboard's historical SST graph
  const setSelected = act.setPoint;
  const dataset = act.dataset;
  const region = act.region; // the selected region only ZOOMS the map; data are always requested for the whole dataset so the map never turns into a region-shaped cut-out
  const dataRegion = "pacific";
  const dateArg = act.date ?? undefined;
  const isLegacy = dataset === LEGACY;

  const datasets = useAsync(() => cached("env-datasets", getDatasets), []);
  const regions = useAsync(() => cached("env-regions", getRegions), []);
  const dates = useAsync(() => cached(`env-dates-${dataset}`, () => getDates(dataset)), [dataset]);
  const ds = datasets.data?.datasets.find((d) => d.id === dataset);
  const dsOk = ds && ds.available ? ds : null;
  const dsError = datasets.isLoading ? null : datasets.error ? `Environmental datasets unavailable: ${datasets.error}` : !ds ? `The backend does not provide a dataset called "${dataset}".` : !ds.available ? `Dataset "${ds.name}" is not available: ${ds.message}` : null;
  const range = dates.data && dates.data.dataset === dataset ? dates.data : null;
  const regionInfo = regions.data?.regions.find((r) => r.id === region);
  const fitTo = useMemo(() => (regionInfo?.map_extent ? extentToBounds(regionInfo.map_extent) : null), [regionInfo]);
  // the layers a dataset can supply; a layer it cannot supply falls back to SST instead of silently showing another dataset
  const hasForecast = !isLegacy;
  const effBase: Base = !hasForecast && base.startsWith("forecast") ? "sst" : base;
  const ready = !!dsOk;

  const envMap = useAsync(
    () => (ready && (effBase === "sst" || effBase === "anomaly") ? getMap({ dataset, layer: effBase, date: act.date ?? "latest", region: dataRegion }) : Promise.resolve(null)),
    [ready, dataset, effBase, act.date],
  );
  const hwMap = useAsync(() => (ready && (effBase === "heatwave" || showOutlines) ? getHeatwaveMap(dataset, dataRegion, dateArg) : Promise.resolve(null)), [ready, dataset, effBase, showOutlines, dateArg]);
  const riskMap = useAsync(() => (ready && effBase === "risk" ? getRiskMap(dataset, dataRegion, dateArg) : Promise.resolve(null)), [ready, dataset, effBase, dateArg]);
  const fcMap = useAsync(
    () => (ready && hasForecast && effBase.startsWith("forecast") ? getForecastMap(dataset, horizon, dataRegion, effBase === "forecast_sst" ? "sst" : "anomaly") : Promise.resolve(null)),
    [ready, hasForecast, dataset, effBase, horizon],
  );
  const catalogue = useAsync(() => (showSpecies ? cached("species-all", () => listSpecies({ page_size: 100 })) : Promise.resolve(null)), [showSpecies]);
  const density = useAsync(() => (showSpecies && densityId ? getSpeciesDistribution(densityId) : Promise.resolve(null)), [showSpecies, densityId]);
  const events = useAsync(() => (ready ? listHeatwaves({ dataset }) : Promise.resolve(null)), [ready, dataset]);
  const species = useAsync(() => (ready && showSpecies ? getSpeciesLayer(dataset, limitToRegion ? region : dataRegion, dateArg) : Promise.resolve(null)), [ready, showSpecies, dataset, dateArg, limitToRegion, region]);
  const alerts = useAsync(() => (ready && showAlerts ? listAlerts({ dataset, status: "NEW", page_size: 100, region: limitToRegion && region !== "pacific" ? region : undefined }) : Promise.resolve(null)), [ready, showAlerts, dataset, limitToRegion, region]);

  // a result is shown only while it belongs to the current selection: never a stale layer under a new date, region, dataset or layer
  const e = envMap.data && !envMap.isLoading && envMap.data.dataset.id === dataset && envMap.data.region.id === dataRegion && envMap.data.layer === effBase ? envMap.data : null;
  const h = hwMap.data && !hwMap.isLoading && hwMap.data.dataset === dataset && hwMap.data.region.id === dataRegion ? hwMap.data : null;
  const k = riskMap.data && !riskMap.isLoading && riskMap.data.dataset === dataset && riskMap.data.region.id === dataRegion ? riskMap.data : null;
  const f = fcMap.data && !fcMap.isLoading && fcMap.data.dataset === dataset && fcMap.data.region.id === dataRegion && fcMap.data.horizon === horizon ? fcMap.data : null;
  const layer: (MapLayer & { status?: number[][] }) | null = useMemo(() => {
    if (effBase === "sst" || effBase === "anomaly") return e ? toMapLayer(e) : null;
    if (effBase === "heatwave") return h ? { ...h, layer: "heatwave", kind: "derived" } : null;
    if (effBase === "risk") return k ? riskToMapLayer(k) : null;
    return f ? { layer: "forecast", label: f.label, kind: "forecast", unit: f.unit, horizon: f.horizon, date: f.date, diverging: f.diverging, coverage: f.coverage, lat: f.lat, lon: f.lon, values: f.values, min: f.min, max: f.max } : null;
  }, [effBase, e, h, k, f]);
  const baseState = effBase === "sst" || effBase === "anomaly" ? envMap : effBase === "heatwave" ? hwMap : effBase === "risk" ? riskMap : fcMap;
  const footprint: MapLayer | null = showOutlines && effBase !== "heatwave" && h ? { ...h, layer: "heatwave", kind: "derived" } : null;
  const evList = events.data && !events.isLoading && (events.data.dataset ?? LEGACY) === dataset ? events.data.items : [];
  const wide = dsOk ? dsOk.extent.lon_max - dsOk.extent.lon_min >= 150 : false;

  // markers: species (conservation colour, ring = inside a current heatwave) and alerts (severity colour); clicking either opens the same report
  const markers = useMemo<MapMarker[]>(() => {
    const out: MapMarker[] = [];
    if (showSpecies && species.data && !species.isLoading && species.data.dataset === dataset) {
      for (const p of species.data.items) {
        if (!STATUS_FILTERS[statusFilter]?.includes(p.conservation_status) && statusFilter !== "ALL") continue;
        out.push({
          key: `s-${p.scientific_name}-${p.lat}-${p.lon_180}`, lat: p.lat, lon: p.lon_180, color: CONS_COLOR[p.conservation_status] ?? "#94a3b8", radius: Math.min(9, 4 + Math.log2(p.n_records + 1)), ring: p.in_heatwave,
          label: `${p.common_name ?? p.scientific_name} · ${p.conservation_status} · ${p.n_records} record${p.n_records === 1 ? "" : "s"}${p.in_heatwave ? " · inside a marine heatwave" : ""}${p.risk_level ? ` · ${p.risk_level === "MEDIUM" ? "MODERATE" : p.risk_level} risk` : ""}${p.alert_severity ? ` · ${p.alert_severity} species-exposure alert` : ""} · record density, not a range`,
          onClick: () => setSelected({ lat: p.lat, lon: p.lon_180 }),
        });
      }
    }
    if (showAlerts && alerts.data && !alerts.isLoading) {
      for (const a of alerts.data.items) {
        if (minSeverity !== "ALL" && SEV_RANK[a.severity] < SEV_RANK[minSeverity]) continue;
        const lo = a.longitude > 180 ? a.longitude - 360 : a.longitude;
        out.push({
          key: `a-${a.id}`, lat: a.latitude, lon: lo, color: SEV_COLOR[a.severity] ?? "#0369a1", radius: 9, ring: true,
          label: `${a.severity} alert · ${a.alert_type.replace(/_/g, " ").toLowerCase()} · ${a.timestamp.slice(0, 10)}`, onClick: () => setSelected({ lat: a.latitude, lon: lo }),
        });
      }
    }
    return out;
  }, [showSpecies, species.data, species.isLoading, showAlerts, alerts.data, alerts.isLoading, dataset, statusFilter, minSeverity]);

  useEffect(() => {
    if (qs.get("species") === "1") setShowSpecies(true);
    if (qs.get("alerts") === "1") setShowAlerts(true);
  }, [qs]);

  const mapError = dsError ?? baseState.error;
  const badge = layer ? `${regionInfo?.name ?? region} · ${layer.date}${effBase.startsWith("forecast") ? " · forecast" : ""}` : undefined;

  return (
    <div>
      <h1 className="sr-only">Pacific Ocean map</h1>
      <div className="on-deep rounded-t-xl bg-gradient-to-r from-deep via-abyss to-tide px-3 py-2.5 text-white">
        <button type="button" className="mb-1 rounded-md border border-white/30 px-3 py-1 text-sm font-medium xl:hidden" aria-expanded={controlsOpen} onClick={() => setControlsOpen((o) => !o)}>
          {controlsOpen ? "Hide layers and controls" : `Layers and controls · ${BASES.find((b) => b.id === effBase)?.label}`}
        </button>
        <div className={`${controlsOpen ? "flex" : "hidden"} flex-wrap items-end gap-x-4 gap-y-2 xl:flex`}>
          <div className="min-w-0">
            <span className="text-[11px] font-semibold uppercase tracking-[0.12em] text-cyan-100/90">Base layer</span>
            <div role="radiogroup" aria-label="Map layer" className="mt-1 flex flex-wrap gap-x-3 gap-y-1">
              {GROUPS.map((grp) => (
                <div key={grp.title} role="group" aria-label={grp.title} className="flex flex-col gap-0.5">
                  <span className="text-[11px] uppercase tracking-wider text-cyan-100/90">{grp.title}</span>
                  <div className="flex overflow-hidden rounded-md border border-white/30">
              {BASES.filter((b) => grp.ids.includes(b.id)).map((b) => {
                const off = !hasForecast && b.id.startsWith("forecast");
                const on = b.id === effBase;
                return (
                  <button key={b.id} type="button" role="radio" aria-checked={on} disabled={off} title={off ? "No forecast for this dataset" : b.hint} onClick={() => setBase(b.id)}
                    className={`px-2.5 py-1 text-sm ${on ? "bg-white font-semibold text-deep" : off ? "cursor-not-allowed text-white/40" : "text-white hover:bg-white/10"}`}>
                    {b.label}
                  </button>
                );
              })}
                  </div>
                </div>
              ))}
            </div>
          </div>
          <label className={field}>Region
            <select className={sel} value={region} onChange={(ev) => act.setRegion(ev.target.value)}>
              {!regionInfo && <option value={region}>{region}</option>}
              {regions.data?.regions.map((r) => (<option key={r.id} value={r.id}>{r.parent && r.parent !== "pacific" ? "  " : ""}{r.name}</option>))}
            </select>
          </label>
          <label className={field}>Date
            <input type="date" className={sel} disabled={!range} min={range?.first_date} max={range?.latest_date} value={act.date ?? range?.latest_date ?? ""} onChange={(ev) => act.setDate(ev.target.value || null)} />
          </label>
          <label className={field}>Dataset
            <select className={sel} value={dataset} onChange={(ev) => { act.setDataset(ev.target.value); setSelected(null); }}>
              {!ds && <option value={dataset}>{dataset}</option>}
              {datasets.data?.datasets.map((d) => (<option key={d.id} value={d.id} disabled={!d.available}>{d.name}{d.available ? "" : " (not available)"}</option>))}
            </select>
          </label>
          {effBase.startsWith("forecast") && (
            <label className={field}>Forecast day
              <select className={sel} value={horizon} onChange={(ev) => setHorizon(Number(ev.target.value))}>{[1, 2, 3, 4, 5, 6, 7].map((n) => <option key={n} value={n}>+{n} day{n > 1 ? "s" : ""}</option>)}</select>
            </label>
          )}
        </div>
        <div className={`${controlsOpen ? "flex" : "hidden"} mt-2 flex-wrap items-center gap-x-4 gap-y-1 text-sm text-cyan-50 xl:flex`}>
          <span className="text-[11px] font-semibold uppercase tracking-[0.12em] text-cyan-100/90">Overlays</span>
          <label className="flex items-center gap-1.5 text-xs" title="When on, species and alerts are limited to the selected region; the map itself is unchanged"><input type="checkbox" checked={limitToRegion} onChange={(ev) => setLimitToRegion(ev.target.checked)} />Limit markers to region</label>
          <label className="flex items-center gap-1.5"><input type="checkbox" checked={showOutlines} onChange={(ev) => setShowOutlines(ev.target.checked)} />Marine heatwave footprints{evList.length ? ` (${evList.length})` : ""}</label>
          <label className="flex items-center gap-1.5"><input type="checkbox" checked={showSpecies} onChange={(ev) => setShowSpecies(ev.target.checked)} />Species records</label>
          {showSpecies && (
            <label className="flex items-center gap-1.5 text-xs">
              <span className="text-cyan-100/90">Conservation status</span>
              <select aria-label="Conservation status" className="rounded border border-white/30 bg-white px-1 py-0.5 text-xs text-slate-900" value={statusFilter} onChange={(ev) => setStatusFilter(ev.target.value)}>
                <option value="ALL">All species</option>
                <option value="THREATENED">Threatened only (CR, EN, VU)</option>
                <option value="CR">Critically endangered (CR)</option>
                <option value="EN">Endangered (EN)</option>
                <option value="VU">Vulnerable (VU)</option>
                <option value="NT">Near threatened (NT)</option>
              </select>
            </label>
          )}
          <label className="flex items-center gap-1.5"><input type="checkbox" checked={showAlerts} onChange={(ev) => setShowAlerts(ev.target.checked)} />Alerts</label>
          {showAlerts && (
            <label className="flex items-center gap-1.5 text-xs">
              <span className="text-cyan-100/90">Severity</span>
              <select aria-label="Alert severity" className="rounded border border-white/30 bg-white px-1 py-0.5 text-xs text-slate-900" value={minSeverity} onChange={(ev) => setMinSeverity(ev.target.value)}>
                <option value="ALL">All</option>
                <option value="MEDIUM">Moderate and above</option>
                <option value="HIGH">High and above</option>
                <option value="CRITICAL">Critical only</option>
              </select>
            </label>
          )}
          {showSpecies && (
            <label className="flex items-center gap-1.5 text-xs">
              <span className="text-cyan-100/90">Record density of</span>
              <select aria-label="Species record density" className="max-w-[12rem] rounded border border-white/30 bg-white px-1 py-0.5 text-xs text-slate-900" value={densityId ?? ""} onChange={(ev) => setDensityId(ev.target.value ? Number(ev.target.value) : null)}>
                <option value="">none</option>
                {catalogue.data?.items.map((s) => <option key={s.aphia_id} value={s.aphia_id}>{s.common_name ?? s.scientific_name}</option>)}
              </select>
            </label>
          )}
          {density.error && <span className="text-xs text-amber-200">Record density unavailable: {density.error}</span>}
          {showSpecies && species.data && <span className="text-xs text-cyan-100/90">{species.data.summary.species} species, {species.data.summary.records.toLocaleString()} records, {species.data.summary.points_in_heatwave} marker(s) inside a heatwave (dark ring)</span>}
          {showAlerts && alerts.data && <span className="text-xs text-cyan-100/90">{alerts.data.items.length} active alert(s)</span>}
        </div>
      </div>
      {mapError && <div role="alert" className="bg-amber-50 px-4 py-2 text-sm text-amber-900">{dsError ?? `Map data unavailable: ${baseState.error}`}</div>}

      <DataDatesNote />
      <div className="grid grid-cols-1 gap-3 pt-3 xl:grid-cols-[minmax(0,1fr)_25rem]">
        <div>
          <SstMap
            layer={layer}
            overlay={footprint}
            markers={markers}
            status={effBase === "risk" ? (layer?.status ?? null) : null}
            statusColors={STATE_COLORS}
            statusLabels={STATE_LABELS}
            legendExtra={effBase === "risk" ? (
              <ul className="mt-1 space-y-0.5 border-t border-white/20 pt-1">
                <li className="flex items-center gap-1.5"><span aria-hidden className="inline-block h-2.5 w-2.5 rounded-sm ring-1 ring-white/70" style={{ background: "rgb(236,236,236)" }} />Insufficient data (not low risk)</li>
                <li className="flex items-center gap-1.5"><span aria-hidden className="inline-block h-2.5 w-2.5 rounded-sm ring-1 ring-white/70" style={{ background: "rgb(58,58,58)" }} />Unavailable (not low risk)</li>
                <li className="text-cyan-100/80">Low &lt; 0.25 · Moderate &lt; 0.5 · High &lt; 0.75 · Critical</li>
              </ul>
            ) : undefined}
            distribution={showSpecies && densityId ? density.data?.geojson ?? null : null}
            selected={selected}
            onPick={(la, lo) => setSelected({ lat: la, lon: lo })}
            fitTo={fitTo}
            lonOrigin={layer ? axisOrigin(layer.lon) : null}
            showOutline={false}
            edgeFade={wide ? 3 : 0}
            unavailable={!!mapError}
            badge={badge}
            initialView="world"
            heightClass="h-[calc(100vh-15rem)] min-h-[28rem]"
            ariaLabel="Pacific Ocean map"
          />
          <div className="mt-1 flex flex-wrap items-center justify-between gap-x-4 text-xs text-slate-600">
            <span>
              {layer ? `${layer.label} · ${layer.date}` : "Loading…"}
              {dsOk && (effBase.startsWith("forecast") ? ` · Model output (ConvLSTM), not an observation · issued from ${dsOk.latest_date} · observations: ${providerLabel(dsOk.provider)}` : ` · Data source: ${providerLabel(dsOk.provider)} · latest ${dsOk.latest_date}`)}
            </span>
            <span>Click the ocean, a species marker or an alert for the full report.</span>
          </div>
          {showSpecies && species.data && <p className="mt-0.5 text-xs text-slate-600">{species.data.note} Marker colour = conservation status (red CR, orange EN, yellow VU, green NT/LC, grey not confirmed); dark ring = inside a current marine heatwave. Areas without markers have no records in this dataset.</p>}
          {act.date && effBase.startsWith("forecast") && range && act.date !== range.latest_date && (
            <p role="note" className="mt-1 rounded bg-slate-50 px-2 py-1 text-xs text-slate-700">Forecasts exist for the latest date ({range.latest_date}) only; the forecast layers show that date.</p>
          )}
        </div>
        <div className={selected ? "fixed inset-x-0 bottom-0 z-[1150] max-h-[68vh] overflow-y-auto rounded-t-xl shadow-2xl xl:static xl:max-h-none xl:overflow-visible xl:shadow-none" : ""}>
        <LocationReport point={selected} dataset={dataset} date={act.date} onClose={() => setSelected(null)} onFocus={(la, lo) => setSelected({ lat: la, lon: lo > 180 ? lo - 360 : lo })} />
        </div>
      </div>
      <div className="mt-3 text-xs text-slate-600">
        <button type="button" className="font-semibold text-tide hover:underline" onClick={() => navigate(`/ocean-data`)}>Data, coverage and sources →</button>
      </div>
    </div>
  );
}
