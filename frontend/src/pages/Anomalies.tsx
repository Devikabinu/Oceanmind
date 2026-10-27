import { useMemo, useState } from "react";
import { getHotspots, getMapLayer } from "../api/monitor";
import type { Hotspot, RegionName, Severity } from "../api/monitor";
import AnomalyDetections from "../components/AnomalyDetections";
import EmptyState from "../components/EmptyState";
import LocationPanel from "../components/LocationPanel";
import PageHeader from "../components/PageHeader";
import SeverityBadge from "../components/SeverityBadge";
import SourceTag from "../components/SourceTag";
import SstMap from "../components/SstMap";
import Status from "../components/Status";
import Term from "../components/Term";
import { REGION_LABELS } from "../components/RegionForecast";
import { useAsync } from "../hooks/useAsync";
import { useOverview } from "../hooks/useCached";
import { useActive } from "../contexts/ActiveSelection";
import ContextBar from "../components/ContextBar";
import PacificAnomalies from "../components/PacificAnomalies";

const SELECT = "rounded-md border border-slate-300 bg-white px-2 py-1.5 text-sm text-slate-800";
const REGION_TEST: Record<RegionName, (h: Hotspot) => boolean> = {
  all: () => true,
  north: (h) => h.lat >= 35,
  south: (h) => h.lat < 35,
  west: (h) => h.lon < -140,
  east: (h) => h.lon >= -140,
};

function explain(h: Hotspot): string {
  const dir = h.direction === "warm" ? "warmer" : "colder";
  const base = `${h.kind === "observed" ? "Observed" : "Forecast"} SST ${h.value_c.toFixed(1)} °C is ${Math.abs(h.mean_anomaly).toFixed(1)} °C ${dir} than the ${h.baseline_c.toFixed(1)} °C average for this date`;
  const persist = h.persistence_days ? `; the heat has persisted about ${h.persistence_days} days` : "";
  return `${base}${persist}.`;
}

function NeAnomalies() {
  const overview = useOverview();
  const range = overview.data?.data_status.available_dates;
  const [mode, setMode] = useState<"observed" | "forecast">("observed");
  const [horizon, setHorizon] = useState(7);
  const [day, setDay] = useState("");
  const [severity, setSeverity] = useState<"ALL" | Severity>("ALL");
  const [direction, setDirection] = useState<"all" | "warm" | "cold">("all");
  const [region, setRegion] = useState<RegionName>("all");
  const [selected, setSelected] = useState<{ lat: number; lon: number } | null>(null);

  const h = mode === "observed" ? 0 : horizon;
  const hot = useAsync(() => getHotspots(h, 1, 500, mode === "observed" && day ? day : undefined), [h, day, mode]);
  const map = useAsync(
    () => getMapLayer(mode === "observed" ? "observed_anomaly" : "forecast_anomaly", Math.max(1, horizon), mode === "observed" && day ? day : undefined),
    [mode, horizon, day],
  );

  const items = useMemo(
    () =>
      (hot.data?.items ?? []).filter(
        (x) => (severity === "ALL" || x.severity === severity) && (direction === "all" || x.direction === direction) && REGION_TEST[region](x),
      ),
    [hot.data, severity, direction, region],
  );
  const counts = useMemo(() => {
    const c: Record<Severity, number> = { MEDIUM: 0, HIGH: 0, CRITICAL: 0 };
    for (const x of items) c[x.severity] += 1;
    return c;
  }, [items]);

  return (
    <div>
      <PageHeader title="SST anomalies">
        Where the sea is warmer or colder than normal. An <Term k="anomaly">anomaly</Term> is today&apos;s temperature minus the 2012–2023 average for the same day of the
        year. Choose an observed day or a forecast day, filter by region and severity, and select an area to inspect it.
      </PageHeader>
      <div className="mt-3"><ContextBar showRegion={false} note="NE Pacific study-region anomalies. Switch the dataset for the Pacific-wide anomaly view." /></div>

      <div className="mt-4 flex flex-wrap items-end gap-3 rounded-lg border border-slate-200 bg-white p-3">
        <label className="flex flex-col gap-1 text-xs font-medium text-slate-600">
          Show
          <select className={SELECT} value={mode} onChange={(e) => setMode(e.target.value as "observed" | "forecast")}>
            <option value="observed">Observed anomalies</option>
            <option value="forecast">Forecast anomalies (model output)</option>
          </select>
        </label>
        {mode === "observed" && range && (
          <label className="flex flex-col gap-1 text-xs font-medium text-slate-600">
            Date
            <input type="date" className={SELECT} min={range.start} max={range.end} value={day || range.end} onChange={(e) => setDay(e.target.value)} />
          </label>
        )}
        {mode === "forecast" && (
          <label className="flex flex-col gap-1 text-xs font-medium text-slate-600">
            Forecast day
            <select className={SELECT} value={horizon} onChange={(e) => setHorizon(Number(e.target.value))}>
              {[1, 2, 3, 4, 5, 6, 7].map((n) => (
                <option key={n} value={n}>+{n} day{n > 1 ? "s" : ""}</option>
              ))}
            </select>
          </label>
        )}
        <label className="flex flex-col gap-1 text-xs font-medium text-slate-600">
          Region
          <select className={SELECT} value={region} onChange={(e) => setRegion(e.target.value as RegionName)}>
            {(Object.keys(REGION_LABELS) as RegionName[]).map((r) => (
              <option key={r} value={r}>{REGION_LABELS[r]}</option>
            ))}
          </select>
        </label>
        <label className="flex flex-col gap-1 text-xs font-medium text-slate-600">
          Severity
          <select className={SELECT} value={severity} onChange={(e) => setSeverity(e.target.value as "ALL" | Severity)}>
            <option value="ALL">All categories</option>
            <option value="CRITICAL">Critical (≥ 3 °C)</option>
            <option value="HIGH">High (≥ 2 °C)</option>
            <option value="MEDIUM">Medium (≥ 1 °C)</option>
          </select>
        </label>
        <label className="flex flex-col gap-1 text-xs font-medium text-slate-600">
          Direction
          <select className={SELECT} value={direction} onChange={(e) => setDirection(e.target.value as "all" | "warm" | "cold")}>
            <option value="all">Warm and cold</option>
            <option value="warm">Warmer than normal</option>
            <option value="cold">Colder than normal</option>
          </select>
        </label>
        <div className="ml-auto pb-1.5"><SourceTag kind={mode === "observed" ? "derived" : "forecast"} /></div>
      </div>

      <div className="mt-4 grid grid-cols-1 gap-4 xl:grid-cols-3">
        <div className="xl:col-span-2">
          <SstMap layer={map.data} hotspots={items} selected={selected} onPick={(lat, lon) => setSelected({ lat, lon })} ariaLabel="SST anomaly map" />
          <p className="mt-1 text-xs text-slate-500">
            Outlined squares are 2°×2° areas at least 1 °C from normal (yellow ≥ 1, orange ≥ 2, red ≥ 3 °C). Click the map or a row below to inspect.
          </p>
        </div>
        <LocationPanel point={selected} />
      </div>

      <section className="mt-8 rounded-lg border border-slate-200 bg-white p-4" aria-labelledby="areas-h">
        <h2 id="areas-h" className="text-sm font-semibold text-slate-900">Anomalous areas on {hot.data?.date ?? "…"}</h2>
        <Status isLoading={hot.isLoading} error={hot.error} hasData={!!hot.data}>
          {hot.data && (
            <>
              <div className="mt-2 flex flex-wrap items-center gap-3 text-sm text-slate-700">
                <span>{items.length} area{items.length === 1 ? "" : "s"}:</span>
                {(["CRITICAL", "HIGH", "MEDIUM"] as Severity[]).map((s) => (
                  <span key={s} className="flex items-center gap-1"><SeverityBadge level={s} /> {counts[s]}</span>
                ))}
              </div>
              {items.length === 0 ? (
                <div className="mt-3">
                  <EmptyState title="No anomalous areas match these filters">
                    <p>
                      Coverage: NOAA OISST in the study region, {range ? `${range.start} to ${range.end}` : "latest data"}; forecasts cover the 7 days after the last
                      observation.
                    </p>
                    <p>Try another date, a larger region or a lower severity.</p>
                  </EmptyState>
                </div>
              ) : (
                <div className="mt-3 overflow-x-auto">
                  <table className="w-full text-left text-sm">
                    <caption className="sr-only">Anomalous 2 by 2 degree areas</caption>
                    <thead className="text-xs uppercase text-slate-600">
                      <tr>
                        <th scope="col" className="py-1 pr-3">Location</th>
                        <th scope="col" className="py-1 pr-3">Date</th>
                        <th scope="col" className="py-1 pr-3">Value °C</th>
                        <th scope="col" className="py-1 pr-3">Baseline °C</th>
                        <th scope="col" className="py-1 pr-3">Anomaly °C</th>
                        <th scope="col" className="py-1 pr-3">Severity</th>
                        <th scope="col" className="py-1 pr-3">Source</th>
                        <th scope="col" className="py-1">Explanation</th>
                      </tr>
                    </thead>
                    <tbody>
                      {items.slice(0, 40).map((x) => (
                        <tr key={`${x.lat}-${x.lon}`} className="border-t border-slate-100 align-top">
                          <td className="py-1.5 pr-3">
                            <button type="button" className="underline" onClick={() => { setSelected({ lat: x.lat, lon: x.lon }); window.scrollTo({ top: 0, behavior: "smooth" }); }}>
                              {x.lat.toFixed(1)}°N, {Math.abs(x.lon).toFixed(1)}°W
                            </button>
                          </td>
                          <td className="py-1.5 pr-3">{x.date}</td>
                          <td className="py-1.5 pr-3">{x.value_c.toFixed(1)}</td>
                          <td className="py-1.5 pr-3">{x.baseline_c.toFixed(1)}</td>
                          <td className="py-1.5 pr-3 font-medium">{x.mean_anomaly > 0 ? "+" : ""}{x.mean_anomaly.toFixed(2)}</td>
                          <td className="py-1.5 pr-3"><SeverityBadge level={x.severity} /></td>
                          <td className="py-1.5 pr-3 text-xs text-slate-600">{x.source}</td>
                          <td className="py-1.5 text-xs text-slate-700">{explain(x)}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                  {items.length > 40 && <p className="mt-1 text-xs text-slate-500">Showing the 40 largest of {items.length}.</p>}
                </div>
              )}
              <p className="mt-3 text-xs text-slate-600">
                {hot.data.basis} Categories are SST-departure bands defined for this dashboard; they are not ecological risk levels.
              </p>
            </>
          )}
        </Status>
      </section>

      <details className="mt-8 rounded-lg border border-slate-200 bg-white p-4">
        <summary className="cursor-pointer text-sm font-semibold text-slate-900">
          Stored detector output (database) <SourceTag kind="derived" />
        </summary>
        <p className="mt-2 text-sm text-slate-600">
          Per-observation rows written by the publish job: a simple departure detector (|anomaly| ≥ 1 °C versus the 2012–2023 average) on a 1° subset of the last 14
          days of NOAA OISST.
        </p>
        <AnomalyDetections />
      </details>
    </div>
  );
}

export default function Anomalies() {
  const act = useActive();
  return act.dataset === "ne_pacific" ? <NeAnomalies /> : <PacificAnomalies />;
}
