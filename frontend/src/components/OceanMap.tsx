import { useMemo, useState } from "react";
import { getRegions, getSpeciesDistribution, getSpeciesObservations, listSpecies } from "../api/intelligence";
import { listAlerts } from "../api/modelOutputs";
import { getHotspots, getMapLayer } from "../api/monitor";
import type { HeatwaveEvent, Layer } from "../api/monitor";
import { useAsync } from "../hooks/useAsync";
import { cached, useOverview } from "../hooks/useCached";
import LocationPanel from "./LocationPanel";
import SourceTag from "./SourceTag";
import type { DataKind } from "./SourceTag";
import SstMap from "./SstMap";

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

const SELECT = "rounded-md border border-slate-300 bg-white px-2 py-1.5 text-sm text-slate-800";

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
}: Props) {
  const [layer, setLayer] = useState<Layer>(initialLayer);
  const [horizon, setHorizon] = useState(initialHorizon);
  const [day, setDay] = useState<string>("");
  const [showHotspots, setShowHotspots] = useState(true);
  const [showEvents, setShowEvents] = useState(true);
  const [selected, setSelected] = useState<{ lat: number; lon: number } | null>(null);
  const [regionId, setRegionId] = useState("study");
  const [speciesId, setSpeciesId] = useState<number | null>(null);
  const [showDist, setShowDist] = useState(false);
  const [showAlerts, setShowAlerts] = useState(false);

  const def = LAYER_DEFS.find((l) => l.value === layer) ?? LAYER_DEFS[0];
  const options = LAYER_DEFS.filter((l) => !layers || layers.includes(l.value));
  const groups = Array.from(new Set(options.map((l) => l.group)));
  const overview = useOverview();
  const range = overview.data?.data_status.available_dates;

  const map = useAsync(() => getMapLayer(layer, horizon, def.date && day ? day : undefined), [layer, horizon, day]);
  const spots = useAsync(
    () => (def.value === "observed_anomaly" || def.value === "forecast_anomaly" || def.value === "forecast" || def.value === "observed"
      ? getHotspots(def.horizon ? horizon : 0, 1, 200, def.date && day ? day : undefined)
      : Promise.resolve(null)),
    [layer, horizon, day],
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
  const fitTo = useMemo<[[number, number], [number, number]] | null>(() => {
    if (regionId === "study" && regions.data?.study_region) {
      const s = regions.data.study_region;
      return [
        [s.lat_min, s.lon_min],
        [s.lat_max, s.lon_max],
      ];
    }
    return region ? region.approx_bounds : null;
  }, [regionId, region, regions.data]);

  const observations = useMemo(
    () => (obs.data?.items ?? []).map((o) => ({ lat: o.latitude, lon: o.longitude, label: `${o.scientific_name} · ${o.timestamp.slice(0, 10)}` })),
    [obs.data],
  );
  const anomalyLayer = def.value === "observed_anomaly" || def.value === "forecast_anomaly";

  return (
    <div>
      <div className="mb-3 flex flex-wrap items-end gap-3">
        <label className="flex flex-col gap-1 text-xs font-medium text-slate-600">
          Layer
          <select className={SELECT} value={layer} onChange={(e) => setLayer(e.target.value as Layer)}>
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
        </label>
        {def.horizon && (
          <label className="flex flex-col gap-1 text-xs font-medium text-slate-600">
            Forecast horizon
            <select className={SELECT} value={horizon} onChange={(e) => setHorizon(Number(e.target.value))}>
              {[1, 2, 3, 4, 5, 6, 7].map((h) => (
                <option key={h} value={h}>
                  +{h} day{h > 1 ? "s" : ""}
                </option>
              ))}
            </select>
          </label>
        )}
        {def.date && range && (
          <label className="flex flex-col gap-1 text-xs font-medium text-slate-600">
            Observed date
            <input type="date" className={SELECT} min={range.start} max={range.end} value={day || range.end} onChange={(e) => setDay(e.target.value)} />
          </label>
        )}
        {showExtras && (
          <label className="flex flex-col gap-1 text-xs font-medium text-slate-600">
            Region
            <select className={SELECT} value={regionId} onChange={(e) => setRegionId(e.target.value)}>
              <option value="study">NE Pacific study region (detailed data)</option>
              {regions.data?.regions.map((r) => (
                <option key={r.id} value={r.id}>
                  {r.name}
                </option>
              ))}
            </select>
          </label>
        )}
        {showExtras && (
          <label className="flex flex-col gap-1 text-xs font-medium text-slate-600">
            Species overlay
            <select className={SELECT} value={speciesId ?? ""} onChange={(e) => { setSpeciesId(e.target.value ? Number(e.target.value) : null); setShowDist(false); }}>
              <option value="">None</option>
              {speciesList.data?.items.map((s) => (
                <option key={s.aphia_id} value={s.aphia_id}>
                  {s.common_name ?? s.scientific_name} ({s.n_observations})
                </option>
              ))}
            </select>
          </label>
        )}
        <div className="flex flex-wrap items-center gap-3 pb-1.5 text-sm text-slate-700">
          {spots.data && (
            <label className="flex items-center gap-1.5">
              <input type="checkbox" checked={showHotspots} onChange={(e) => setShowHotspots(e.target.checked)} />
              Outline areas ≥ 1 °C from normal
            </label>
          )}
          {events && events.length > 0 && (
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
        <div className="ml-auto flex items-center gap-2 pb-1.5 text-sm text-slate-600">
          {map.data && <span>{map.data.date}</span>}
          <SourceTag kind={def.tag} />
        </div>
      </div>

      <p className="mb-1 text-xs text-slate-700">{def.help}</p>
      <p className="mb-2 text-xs text-slate-500">
        Layer: <strong>{def.label}</strong> · Unit: {map.data?.unit ?? "…"} · Date: {map.data?.date ?? "…"} · Source: {def.source}. Coverage: NE Pacific study region only.
      </p>
      {noData && (
        <div role="status" className="mb-3 rounded-md border border-slate-300 bg-slate-50 px-3 py-2 text-sm text-slate-800">
          No data available for this layer for the selected {def.date ? "date" : "horizon"}. Try another date or layer.
        </div>
      )}
      {map.error && <div className="mb-3 rounded-md bg-amber-50 px-3 py-2 text-sm text-amber-800">Map data unavailable: {map.error}</div>}
      {dist.error && <div className="mb-3 rounded-md bg-amber-50 px-3 py-2 text-sm text-amber-800">OBIS distribution unavailable: {dist.error}</div>}

      <div className="grid grid-cols-1 gap-4 xl:grid-cols-3">
        <div className="xl:col-span-2">
          <SstMap
            layer={map.data}
            hotspots={showHotspots && (anomalyLayer || def.value === "forecast" || def.value === "observed") ? spots.data?.items : undefined}
            events={showEvents ? events : undefined}
            observations={observations}
            alertMarkers={showAlerts ? alertMarkers : undefined}
            distribution={showDist ? dist.data?.geojson : null}
            selected={selected}
            onPick={(lat, lon) => setSelected({ lat, lon })}
            onEventClick={onEventClick}
            fitTo={fitTo}
            initialView={view}
            heightClass={heightClass}
          />
          <p className="mt-1 text-xs text-slate-500">
            Use the + / − buttons (or click the map, then scroll) to zoom, drag to pan, hover to read a value, click the ocean for details. The dashed outline is the area this project has data for.
          </p>
          {showExtras && region && (
            <p className="mt-1 rounded bg-slate-100 px-2 py-1 text-xs text-slate-700">
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
              Yellow dots: {obs.data.total.toLocaleString()} stored OBIS records (observation; a sample, effort is uneven).
              {obs.data.total === 0 && " No available observations for this species in the loaded region."}
            </p>
          )}
        </div>
        <LocationPanel point={selected} />
      </div>
    </div>
  );
}
