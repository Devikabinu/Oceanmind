import { useMemo, useState } from "react";
import type { ReactNode } from "react";
import { getRegions, getSpeciesDistribution, getSpeciesObservations, listSpecies } from "../api/intelligence";
import { listAlerts } from "../api/modelOutputs";
import { getCoverage as getEnvCoverage, getDates, getDatasets, getMap as getEnvMap, getRegions as getEnvRegions } from "../api/environment";
import type { EnvironmentDatasetAvailable, EnvironmentLayer } from "../api/environment";
import { getHotspots, getMapLayer } from "../api/monitor";
import type { HeatwaveEvent, Layer } from "../api/monitor";
import { useActive } from "../contexts/ActiveSelection";
import RelatedLinks from "./RelatedLinks";
import { useAsync } from "../hooks/useAsync";
import { cached, useOverview } from "../hooks/useCached";
import LocationPanel from "./LocationPanel";
import SourceTag from "./SourceTag";
import type { DataKind } from "./SourceTag";
import SstMap from "./SstMap";
import { axisOrigin, extentToBounds, toMapLayer } from "../utils/mapCoords";
import { providerLabel } from "../utils/format";

const LEGACY_DATASET = "ne_pacific";
const ENV_LAYERS: Layer[] = ["observed", "observed_anomaly"];
const envLayerOf = (l: Layer): EnvironmentLayer => (l === "observed" ? "sst" : "anomaly");

interface LayerDef {
  value: Layer;
  label: string;
  tag: DataKind;
  group: string;
  horizon?: boolean;
  date?: boolean;
  help: string;
  source: string;
}

export const LAYER_DEFS: LayerDef[] = [
  { value: "observed", label: "Current SST", tag: "observed", group: "Observed now", date: true, help: "Sea surface temperature from NOAA OISST on the selected observed day.", source: "NOAA OISST v2.1 (observation)" },
  { value: "observed_anomaly", label: "SST anomaly", tag: "derived", group: "Observed now", date: true, help: "Observed SST minus the 2012-2023 average for the same day of the year. Red = warmer than normal, blue = colder.", source: "NOAA OISST v2.1 minus 2012-2023 climatology (derived)" },
  { value: "forecast", label: "Forecast SST", tag: "forecast", group: "Forecast (model output)", horizon: true, help: "ConvLSTM forecast issued from the last observed day. Not an observation.", source: "Project ConvLSTM forecast (model output)" },
  { value: "forecast_anomaly", label: "Forecast anomaly", tag: "forecast", group: "Forecast (model output)", horizon: true, help: "Forecast SST minus the 2012-2023 average for the target day.", source: "ConvLSTM forecast minus 2012-2023 climatology (model output)" },
  { value: "heatwave", label: "Marine heatwave", tag: "derived", group: "Environment & risk", help: "Anomaly shown only where a project-definition marine heatwave (90th percentile exceeded for 5+ days) is active.", source: "NOAA OISST v2.1, project heatwave definition (derived)" },
  { value: "risk", label: "Ecological risk", tag: "derived", group: "Environment & risk", help: "Project environmental risk indicator 0-1: SST anomaly, heatwave persistence, forecast anomaly and species overlap. Monitoring priority, not proof of harm.", source: "Project risk indicator from NOAA OISST, ConvLSTM and OBIS (derived)" },
  { value: "hindcast", label: "Hindcast SST", tag: "forecast", group: "Verification (past forecast)", horizon: true, help: "Forecast issued 7 days before the verification window, for days that are now observed.", source: "Project ConvLSTM hindcast (model output)" },
  { value: "hindcast_truth", label: "Observed for hindcast days", tag: "observed", group: "Verification (past forecast)", horizon: true, help: "What was actually observed on the hindcast days.", source: "NOAA OISST v2.1 (observation)" },
  { value: "hindcast_error", label: "Hindcast error", tag: "evaluation", group: "Verification (past forecast)", horizon: true, help: "Forecast minus observed. Near zero = accurate.", source: "ConvLSTM hindcast minus NOAA OISST (evaluation)" },
];

const SELECT = "w-full min-w-0 max-w-full rounded-md border border-white/30 bg-white px-2 py-1.5 text-sm text-slate-900";

interface Props {
  initialLayer?: Layer;
  initialHorizon?: number;
  layers?: Layer[];
  heightClass?: string;
  view?: "study" | "world";
  /** Show the region jump list and the species overlay controls (full Ocean Map page). */
  showExtras?: boolean;
  events?: HeatwaveEvent[];
  onEventClick?: (id: string) => void;
  /** Read observed SST / anomaly from /api/environment (dataset, region and date selectors). Pacific is the initial dataset. */
  environment?: boolean;
}

/** The central map: layer, date/horizon and region controls, optional species overlay, and a location inspector. */
export default function OceanMap({
  initialLayer = "observed_anomaly",
  initialHorizon = 7,
  layers,
  heightClass,
  view = "study",
  showExtras = false,
  events,
  onEventClick,
  environment = false,
}: Props) {
  const [layer, setLayer] = useState<Layer>(initialLayer);
  const [horizon, setHorizon] = useState(initialHorizon);
  const act = useActive();
  const [localDay, setLocalDay] = useState<string>("");
  // environment mode: date, dataset and region are the shared, active selection; the legacy dashboard maps keep their own date
  const day = environment ? (act.date ?? "") : localDay;
  const setDay = (v: string) => (environment ? act.setDate(v || null) : setLocalDay(v));
  const [showHotspots, setShowHotspots] = useState(true);
  const [showEvents, setShowEvents] = useState(true);
  const [selected, setSelected] = useState<{ lat: number; lon: number } | null>(null);
  const [regionId, setRegionId] = useState("study");
  const datasetId = act.dataset;
  const setDatasetId = act.setDataset;
  const envRegionId = act.region;
  const setEnvRegionId = act.setRegion;
  const [speciesId, setSpeciesId] = useState<number | null>(null);
  const [showDist, setShowDist] = useState(false);
  const [showAlerts, setShowAlerts] = useState(false);

  // environment mode: datasets other than the NE Pacific study region only have SST and anomaly (forecast, heatwave and risk layers are NE-only)
  const allowed = (l: Layer) => !environment || datasetId === LEGACY_DATASET || ENV_LAYERS.includes(l);
  const options = LAYER_DEFS.filter((l) => (!layers || layers.includes(l.value)) && allowed(l.value));
  const def = options.find((l) => l.value === layer) ?? options[0] ?? LAYER_DEFS[0];
  const useEnvApi = environment && ENV_LAYERS.includes(def.value);
  const groups = Array.from(new Set(options.map((l) => l.group)));
  const overview = useOverview();
  const envDatasets = useAsync(() => (environment ? cached("env-datasets", getDatasets) : Promise.resolve(null)), [environment]);
  const envRegions = useAsync(() => (environment ? cached("env-regions", getEnvRegions) : Promise.resolve(null)), [environment]);
  const dataset = envDatasets.data?.datasets.find((d) => d.id === datasetId) ?? null;
  const datasetOk: EnvironmentDatasetAvailable | null = dataset && dataset.available ? dataset : null;
  const datasetError = !environment || envDatasets.isLoading
    ? null
    : envDatasets.error
      ? `Environmental datasets unavailable: ${envDatasets.error}`
      : !dataset
        ? `The backend does not provide a dataset called "${datasetId}".`
        : !dataset.available
          ? `Dataset "${dataset.name}" is not available: ${dataset.message}`
          : null;
  const envDates = useAsync(() => (datasetOk ? getDates(datasetOk.id) : Promise.resolve(null)), [datasetOk?.id]);
  const range = environment
    ? envDates.data && envDates.data.dataset === datasetId ? { start: envDates.data.first_date, end: envDates.data.latest_date } : undefined
    : overview.data?.data_status.available_dates;

  const envQuery = { dataset: datasetId, layer: envLayerOf(def.value), date: def.date && day ? day : "latest", region: envRegionId };
  const envReady = useEnvApi && !!datasetOk;
  const envMap = useAsync(() => (envReady ? getEnvMap(envQuery) : Promise.resolve(null)), [envReady, datasetId, def.value, day, envRegionId]);
  const envCoverage = useAsync(() => (envReady ? getEnvCoverage(envQuery) : Promise.resolve(null)), [envReady, datasetId, def.value, day, envRegionId]);
  const legacyMap = useAsync(
    () => (useEnvApi || datasetError ? Promise.resolve(null) : getMapLayer(def.value, horizon, def.date && day ? day : undefined)),
    [useEnvApi, datasetError, def.value, horizon, day],
  );
  // the environment response is only shown while it belongs to the current selection (never stale data under a new region/date/layer)
  const envFresh = envMap.data && !envMap.isLoading && envMap.data.dataset.id === datasetId && envMap.data.region.id === envRegionId
    && envMap.data.layer === envLayerOf(def.value) ? envMap.data : null;
  const envLayer = useMemo(() => (envFresh ? toMapLayer(envFresh) : null), [envFresh]);
  const map = useEnvApi
    ? { data: envLayer, error: datasetError ?? envMap.error, isLoading: envMap.isLoading || envDatasets.isLoading }
    : { data: legacyMap.data, error: datasetError ?? legacyMap.error, isLoading: legacyMap.isLoading };
  const covFresh = envCoverage.data && envFresh && envCoverage.data.date === envFresh.date && envCoverage.data.region.id === envFresh.region.id
    && envCoverage.data.layer === envFresh.layer ? envCoverage.data : null;
  const showHotspotData = !environment || datasetId === LEGACY_DATASET;
  const spots = useAsync(
    () => (showHotspotData && (def.value === "observed_anomaly" || def.value === "forecast_anomaly" || def.value === "forecast" || def.value === "observed")
      ? getHotspots(def.horizon ? horizon : 0, 1, 200, def.date && day ? day : undefined)
      : Promise.resolve(null)),
    [showHotspotData, def.value, horizon, day],
  );
  const regions = useAsync(() => cached("regions", getRegions), []);
  const speciesList = useAsync(() => (showExtras ? cached("species-all", () => listSpecies({ page_size: 100 })) : Promise.resolve(null)), [showExtras]);
  const obs = useAsync(() => (speciesId ? getSpeciesObservations(speciesId) : Promise.resolve(null)), [speciesId]);
  const dist = useAsync(() => (speciesId && showDist ? getSpeciesDistribution(speciesId) : Promise.resolve(null)), [speciesId, showDist]);

  const openAlerts = useAsync(() => (showExtras && showAlerts ? listAlerts({ status: "NEW", page_size: 100 }) : Promise.resolve(null)), [showExtras, showAlerts]);
  const alertMarkers = useMemo(
    () => (openAlerts.data?.items ?? []).map((a) => ({ lat: a.latitude, lon: a.longitude, label: `${a.severity} · ${a.alert_type.replace(/_/g, " ").toLowerCase()} · ${a.timestamp.slice(0, 10)}` })),
    [openAlerts.data],
  );
  const noData = !!map.data && map.data.values.every((row) => row.every((v) => v == null));
  const region = regions.data?.regions.find((r) => r.id === regionId);
  const envRegion = envRegions.data?.regions.find((r) => r.id === envRegionId);
  const fitTo = useMemo<[[number, number], [number, number]] | null>(() => {
    if (useEnvApi) return envRegion?.map_extent ? extentToBounds(envRegion.map_extent) : null;
    if (regionId === "study" && regions.data?.study_region) {
      const s = regions.data.study_region;
      return [
        [s.lat_min, s.lon_min],
        [s.lat_max, s.lon_max],
      ];
    }
    return region ? region.approx_bounds : null;
  }, [useEnvApi, envRegion, regionId, region, regions.data]);

  const observations = useMemo(
    () => (obs.data?.items ?? []).map((o) => ({ lat: o.latitude, lon: o.longitude, label: `${o.scientific_name} · ${o.timestamp.slice(0, 10)}` })),
    [obs.data],
  );
  const lonOrigin = useEnvApi && envLayer ? axisOrigin(envLayer.lon) : null;
  const provider = envFresh?.dataset.provider;
  const anomalyLayer = def.value === "observed_anomaly" || def.value === "forecast_anomaly";

  const generated = useEnvApi && !!provider && !provider.is_observational;
  const segmented = environment && options.length <= 2;
  const mapBadge = useEnvApi && envFresh ? `${envFresh.region.name} · ${envFresh.date}${generated ? "" : ""}` : undefined;
  const wide = useEnvApi && envFresh ? envFresh.dataset.extent.lon_max - envFresh.dataset.extent.lon_min >= 150 : false;

  return (
    <div>
      <div className="on-deep rounded-t-xl bg-gradient-to-r from-deep via-abyss to-tide px-4 py-3 text-white">
        <div className="flex flex-wrap items-end gap-x-4 gap-y-3">
          {environment && (
            <Field label="Dataset">
              <select
                className={SELECT}
                value={datasetId}
                onChange={(e) => {
                  setDatasetId(e.target.value);
                }}
              >
                {!dataset && <option value={datasetId}>{datasetId}</option>}
                {envDatasets.data?.datasets.map((d) => (
                  <option key={d.id} value={d.id} disabled={!d.available}>
                    {d.name}
                    {d.available ? "" : " (not available)"}
                  </option>
                ))}
              </select>
            </Field>
          )}
          {segmented ? (
            <Field label="Layer">
              <div role="radiogroup" aria-label="Layer" className="flex overflow-hidden rounded-md border border-white/30">
                {options.map((l) => {
                  const on = l.value === def.value;
                  return (
                    <button
                      key={l.value}
                      type="button"
                      role="radio"
                      aria-checked={on}
                      onClick={() => setLayer(l.value)}
                      className={`px-3 py-1 text-left text-sm ${on ? "bg-white font-semibold text-deep" : "text-white hover:bg-white/10"}`}
                    >
                      <span className="block leading-tight">{l.value === "observed" ? "SST" : "Anomaly"}</span>
                      <span className={`block text-[11px] leading-tight ${on ? "text-slate-600" : "text-cyan-100/80"}`}>
                        {l.value === "observed" ? "How warm is the ocean?" : "Difference from normal"}
                      </span>
                    </button>
                  );
                })}
              </div>
            </Field>
          ) : (
            <Field label="Layer">
              <select className={SELECT} value={def.value} onChange={(e) => setLayer(e.target.value as Layer)}>
                {groups.map((g) => (
                  <optgroup key={g} label={g}>
                    {options.filter((l) => l.group === g).map((l) => (
                      <option key={l.value} value={l.value}>
                        {l.label}
                      </option>
                    ))}
                  </optgroup>
                ))}
              </select>
            </Field>
          )}
          {def.horizon && (
            <Field label="Forecast horizon">
              <select className={SELECT} value={horizon} onChange={(e) => setHorizon(Number(e.target.value))}>
                {[1, 2, 3, 4, 5, 6, 7].map((h) => (
                  <option key={h} value={h}>
                    +{h} day{h > 1 ? "s" : ""}
                  </option>
                ))}
              </select>
            </Field>
          )}
          {def.date && range && (
            <Field label={environment ? "Date" : "Observed date"}>
              <input type="date" className={SELECT} min={range.start} max={range.end} value={day || range.end} onChange={(e) => setDay(e.target.value)} />
            </Field>
          )}
          {environment && (
            <Field label="Region">
              <select className={SELECT} value={envRegionId} onChange={(e) => setEnvRegionId(e.target.value)}>
                {!envRegion && <option value={envRegionId}>{envRegionId}</option>}
                {envRegions.data?.regions.map((r) => (
                  <option key={r.id} value={r.id}>
                    {r.parent && r.parent !== "pacific" ? "  " : ""}
                    {r.name}
                  </option>
                ))}
              </select>
            </Field>
          )}
          {showExtras && !environment && (
            <Field label="Region">
              <select className={SELECT} value={regionId} onChange={(e) => setRegionId(e.target.value)}>
                <option value="study">NE Pacific study region (detailed data)</option>
                {regions.data?.regions.map((r) => (
                  <option key={r.id} value={r.id}>
                    {r.name}
                  </option>
                ))}
              </select>
            </Field>
          )}
        </div>

        {(showExtras || spots.data || (events && events.length > 0 && showHotspotData)) && (
          <details className="mt-3 text-sm text-cyan-50">
            <summary className="cursor-pointer text-xs font-semibold uppercase tracking-[0.12em] text-cyan-100/90">More layers: outlines, species, alerts</summary>
            <div className="mt-2 flex flex-wrap items-end gap-x-4 gap-y-2">
          {showExtras && (
            <Field label="Species overlay">
              <select className={SELECT} value={speciesId ?? ""} onChange={(e) => { setSpeciesId(e.target.value ? Number(e.target.value) : null); setShowDist(false); }}>
                <option value="">None</option>
                {speciesList.data?.items.map((s) => (
                  <option key={s.aphia_id} value={s.aphia_id}>
                    {s.common_name ?? s.scientific_name} ({s.n_observations})
                  </option>
                ))}
              </select>
            </Field>
          )}
            </div>
        <div className="flex flex-wrap items-center gap-x-4 gap-y-2 text-sm text-cyan-50">
          {spots.data && (
            <label className="flex items-center gap-1.5">
              <input type="checkbox" checked={showHotspots} onChange={(e) => setShowHotspots(e.target.checked)} />
              Outline areas ≥ 1 °C from normal
            </label>
          )}
          {events && events.length > 0 && showHotspotData && (
            <label className="flex items-center gap-1.5">
              <input type="checkbox" checked={showEvents} onChange={(e) => setShowEvents(e.target.checked)} />
              Outline marine heatwaves
            </label>
          )}
          {speciesId && (
            <label className="flex items-center gap-1.5">
              <input type="checkbox" checked={showDist} onChange={(e) => setShowDist(e.target.checked)} />
              Observed distribution (OBIS record density, not a range)
            </label>
          )}
          {showExtras && (
            <label className="flex items-center gap-1.5">
              <input type="checkbox" checked={showAlerts} onChange={(e) => setShowAlerts(e.target.checked)} />
              Show new alerts
            </label>
          )}
        </div>

          </details>
        )}

        <div className="mt-3 flex flex-wrap items-center gap-x-3 gap-y-1 border-t border-white/15 pt-2 text-xs text-cyan-50" data-testid="env-meta" aria-live="polite">
          {useEnvApi ? (
            <>
              <span>
                <span className="text-cyan-200/80">Dataset</span> <strong className="font-semibold text-white">{envFresh?.dataset.name ?? "…"}</strong>
              </span>
              <span>
                <span className="text-cyan-200/80">Region</span> <strong className="font-semibold text-white">{envFresh?.region.name ?? "…"}</strong>
              </span>
              <span>
                <span className="text-cyan-200/80">Date</span> <strong className="font-semibold text-white">{envFresh?.date ?? "…"}</strong>
                {envFresh && <span className="text-cyan-200/80"> · latest available {envFresh.latest_available_date}</span>}
              </span>
              {provider && (
                <span className={`rounded px-1.5 py-0.5 font-semibold ${provider.is_observational ? "bg-emerald-200 text-emerald-950" : "bg-amber-200 text-amber-950"}`}>
                  {provider.is_observational ? "Observational" : "Modelled dataset"}
                </span>
              )}
              {provider && <span className="text-cyan-200/80">Source {provider.provider_id}</span>}
            </>
          ) : (
            <>
              <span>
                <span className="text-cyan-200/80">Layer</span> <strong className="font-semibold text-white">{def.label}</strong>
              </span>
              <span>
                <span className="text-cyan-200/80">Date</span> <strong className="font-semibold text-white">{map.data?.date ?? "…"}</strong>
              </span>
              <SourceTag kind={def.tag} />
              <span className="text-cyan-200/80">{def.source} · NE Pacific study region only</span>
            </>
          )}
        </div>
        {useEnvApi && (
          <p className="mt-1.5 text-xs text-cyan-100/90">
            {def.value === "observed"
              ? "SST is sea surface temperature: how warm the ocean surface is, in °C."
              : "Anomaly is the difference between SST and the expected (climatological) value for the same day of the year; red is warmer than normal, blue is colder."}
          </p>
        )}
      </div>

      {noData && (
        <div role="status" className="border-x border-slate-300 bg-slate-50 px-4 py-2 text-sm text-slate-800">
          {useEnvApi && envFresh?.message
            ? envFresh.message
            : `No data available for this layer for the selected ${def.date ? "date" : "horizon"}. Try another date or layer.`}
        </div>
      )}
      {useEnvApi && !map.error && !map.data && map.isLoading && (
        <div role="status" aria-live="polite" className="border-x border-slate-300 bg-white px-4 py-1.5 text-xs text-slate-600">Loading environmental data…</div>
      )}
      {(envRegions.error || (envDatasets.error && !datasetError)) && (
        <div className="bg-amber-50 px-4 py-2 text-sm text-amber-900">The region list could not be loaded: {envRegions.error ?? envDatasets.error}</div>
      )}
      {map.error && <div role="alert" className="bg-amber-50 px-4 py-2 text-sm text-amber-900">Map data unavailable: {map.error}</div>}
      {envCoverage.error && !map.error && <div className="bg-amber-50 px-4 py-2 text-sm text-amber-900">Coverage figures unavailable: {envCoverage.error}</div>}
      {dist.error && <div className="bg-amber-50 px-4 py-2 text-sm text-amber-900">OBIS distribution unavailable: {dist.error}</div>}

      <div className="grid grid-cols-1 gap-4 xl:grid-cols-[minmax(0,1fr)_22rem]">
        <div>
          <SstMap
            layer={map.data}
            hotspots={showHotspots && (anomalyLayer || def.value === "forecast" || def.value === "observed") ? spots.data?.items : undefined}
            events={showEvents && showHotspotData ? events : undefined}
            observations={observations}
            alertMarkers={showAlerts ? alertMarkers : undefined}
            distribution={showDist ? dist.data?.geojson : null}
            selected={selected}
            onPick={(lat, lon) => setSelected({ lat, lon })}
            onEventClick={onEventClick}
            fitTo={fitTo}
            lonOrigin={lonOrigin}
            unavailable={!!map.error}
            coverageLabel={useEnvApi ? (envFresh?.dataset.name ?? "selected dataset") : undefined}
            showOutline={!wide}
            badge={mapBadge}
            initialView={view}
            heightClass={heightClass}
          />
          <details className="mt-2 text-xs text-slate-600">
            <summary className="cursor-pointer font-medium text-slate-700">Data, coverage and how to use the map</summary>
            <div className="mt-1 space-y-1">
              {useEnvApi && provider && (
                <p>
                  <strong>Source:</strong> {providerLabel(provider)} ({provider.is_observational ? "observations" : "modelled dataset"}). {provider.description}
                </p>
              )}
              {covFresh && (
                <p data-testid="env-coverage">
                  <strong>Coverage in {covFresh.region.name}:</strong> {covFresh.coverage.valid_cells.toLocaleString()} of {covFresh.coverage.ocean_cells.toLocaleString()} ocean cells have data
                  {covFresh.coverage.valid_pct_of_ocean != null && ` (${covFresh.coverage.valid_pct_of_ocean}%)`}; {covFresh.coverage.missing_cells.toLocaleString()} missing;{" "}
                  {covFresh.coverage.land_cells.toLocaleString()} land. Dataset extent {covFresh.extent.lat_min}° to {covFresh.extent.lat_max}° N, {covFresh.extent.lon_min}° to{" "}
                  {covFresh.extent.lon_max}° E (continuous east longitude).
                  {envFresh && envFresh.downsample_factor > 1 && ` Shown at ${envFresh.downsample_factor}× reduced resolution (averaged by the backend).`}
                </p>
              )}
              <p>Use the + / − buttons (or click the map, then scroll) to zoom, drag to pan, hover to read a value, click the ocean for details.</p>
            </div>
          </details>
          {environment && envRegion && (
            <p className="mt-1 text-xs text-slate-700">
              <strong>{envRegion.name}:</strong> {envRegion.description}
            </p>
          )}
          {showExtras && !environment && region && (
            <p className="mt-1 text-xs text-slate-700">
              <strong>{region.name}:</strong> {region.note}{" "}
              {region.stored_species_records != null && `Stored species records here: ${region.stored_species_records.toLocaleString()}.`}
            </p>
          )}
          {showAlerts && openAlerts.data && (
            <p className="mt-1 text-xs text-slate-600">
              Dark-ringed circles: {openAlerts.data.items.length} new alert{openAlerts.data.items.length === 1 ? "" : "s"} (hover for details; open them on the Alerts page).
              {openAlerts.data.items.length === 0 && " There are no new alerts to show."}
            </p>
          )}
          {speciesId && obs.data && (
            <p className="mt-1 text-xs text-slate-600">
              Yellow dots: {obs.data.total.toLocaleString()} stored OBIS records (observations; recording effort is uneven).
              {obs.data.total === 0 && " No available observations for this species in the loaded region."}
            </p>
          )}
        </div>
        <div className="space-y-3">
        <LocationPanel
          point={selected}
          environment={environment && datasetId !== LEGACY_DATASET ? { dataset: datasetId, date: envFresh?.date ?? null, layer: envLayerOf(def.value) } : undefined}
        />
        {environment && (
          <div className="rounded-xl bg-white/70 p-3 ring-1 ring-slate-200">
            <RelatedLinks point={selected} to={["risk", "heatwaves", "alerts", "forecast"]} />
          </div>
        )}
        </div>
      </div>
    </div>
  );
}

function Field({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div className="flex min-w-0 max-w-full flex-col gap-1">
      <span className="text-[11px] font-semibold uppercase tracking-[0.12em] text-cyan-100/90">{label}</span>
      {children}
    </div>
  );
}
