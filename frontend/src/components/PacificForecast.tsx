import { useMemo, useState } from "react";
import { getForecast, getForecastMap } from "../api/environment";
import type { EnvironmentLayer } from "../api/environment";
import type { MapLayer } from "../api/monitor";
import { useActive } from "../contexts/ActiveSelection";
import { useAsync } from "../hooks/useAsync";
import { cached } from "../hooks/useCached";
import { getRegions } from "../api/environment";
import { axisOrigin, extentToBounds } from "../utils/mapCoords";
import ContextBar from "./ContextBar";
import ExplanationPanel from "./ExplanationPanel";
import PageHeader from "./PageHeader";
import RelatedLinks from "./RelatedLinks";
import SourceTag from "./SourceTag";
import SstMap from "./SstMap";
import Status from "./Status";

const signed = (v: number | null | undefined, d = 2) => (v == null ? "–" : `${v > 0 ? "+" : ""}${v.toFixed(d)}`);
const f1 = (v: number | null | undefined) => (v == null ? "–" : v.toFixed(1));

/** Forecast of a dataset other than the NE Pacific: the existing ConvLSTM pipeline run on that dataset, with its provenance and the performance measured there. */
export default function PacificForecast() {
  const act = useActive();
  const [horizon, setHorizon] = useState(7);
  const [kind, setKind] = useState<EnvironmentLayer>("anomaly");
  const fc = useAsync(() => getForecast(act.dataset, act.region), [act.dataset, act.region]);
  const map = useAsync(() => getForecastMap(act.dataset, horizon, act.region, kind), [act.dataset, act.region, horizon, kind]);
  const regions = useAsync(() => cached("env-regions", getRegions), []);
  const info = regions.data?.regions.find((r) => r.id === act.region);
  const fitTo = useMemo(() => (info?.map_extent ? extentToBounds(info.map_extent) : null), [info]);
  const F = fc.data && !fc.isLoading && fc.data.dataset === act.dataset && fc.data.region.id === act.region ? fc.data : null;
  const M = map.data && !map.isLoading && map.data.dataset === act.dataset && map.data.region.id === act.region && map.data.horizon === horizon ? map.data : null;
  const layer: MapLayer | null = M
    ? {
        layer: "forecast", label: M.label, kind: "forecast", unit: M.unit, horizon: M.horizon, date: M.date, diverging: M.diverging,
        coverage: M.coverage, lat: M.lat, lon: M.lon, values: M.values, min: M.min, max: M.max,
      }
    : null;
  const perf = F?.performance;
  return (
    <div>
      <PageHeader title="SST forecast, 1–7 days" actions={<SourceTag kind="forecast" />}>
        What the ConvLSTM expects for the selected dataset and region, compared with a persistence forecast and the climatology, together with how that model has actually
        performed on this dataset.
      </PageHeader>
      <div className="mt-3">
        <ContextBar note="The forecast is issued from the dataset's latest day; the date selector does not apply." />
      </div>
      <Status isLoading={fc.isLoading} error={fc.error} hasData={!!F} emptyMessage="No forecast for this dataset.">
        {F && (
          <div className="mt-4 space-y-4">
            <ExplanationPanel explanation={F.explanation} title="Forecast in plain language" />

            <section className="rounded-lg bg-white/70 p-4 ring-1 ring-slate-200" aria-labelledby="fc-t">
              <h2 id="fc-t" className="text-sm font-semibold uppercase tracking-wide text-slate-800">
                {F.region.name}: forecast from {F.issued_from} (last observed {f1(F.last_observed_sst)} °C, anomaly {signed(F.last_observed_anomaly, 1)} °C)
              </h2>
              <div className="mt-2 overflow-x-auto">
                <table className="w-full text-left text-sm">
                  <caption className="sr-only">Forecast by horizon</caption>
                  <thead className="text-xs uppercase text-slate-600">
                    <tr>
                      <th scope="col" className="py-1 pr-3">Day</th>
                      <th scope="col" className="py-1 pr-3">Date</th>
                      <th scope="col" className="py-1 pr-3">Forecast °C</th>
                      <th scope="col" className="py-1 pr-3">Anomaly °C</th>
                      <th scope="col" className="py-1 pr-3">Persistence °C</th>
                      <th scope="col" className="py-1 pr-3">Climatology °C</th>
                      <th scope="col" className="py-1">Typical error °C</th>
                    </tr>
                  </thead>
                  <tbody>
                    {F.horizons.map((h, i) => (
                      <tr key={h} className="border-t border-slate-100">
                        <td className="py-1 pr-3 font-medium">+{h}</td>
                        <td className="py-1 pr-3">{F.target_dates[i]}</td>
                        <td className="py-1 pr-3">{f1(F.forecast_sst[i])}</td>
                        <td className="py-1 pr-3">{signed(F.forecast_anomaly[i])}</td>
                        <td className="py-1 pr-3">{f1(F.persistence_sst[i])}</td>
                        <td className="py-1 pr-3">{f1(F.climatology_sst[i])}</td>
                        <td className="py-1">{F.typical_error_c ? `±${F.typical_error_c[i].toFixed(2)}` : "not evaluated"}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
              <p className="mt-2 text-xs text-slate-600">Regional means are weighted by cos(latitude) over valid cells. “Typical error” is the model’s mean absolute error on this dataset’s test period (whole domain).</p>
            </section>

            <section className="rounded-lg bg-white/70 p-4 ring-1 ring-slate-200" aria-labelledby="fc-m">
              <h2 id="fc-m" className="text-sm font-semibold uppercase tracking-wide text-slate-800">Model information</h2>
              <dl className="mt-2 grid grid-cols-1 gap-x-6 gap-y-1 text-sm md:grid-cols-2">
                <div><dt className="inline font-medium">Model: </dt><dd className="inline">{F.model.name}</dd></div>
                <div><dt className="inline font-medium">Checkpoint: </dt><dd className="inline">{F.model.checkpoint.which}, epoch {F.model.checkpoint.epoch ?? "n/a"}</dd></div>
                <div className="md:col-span-2"><dt className="inline font-medium">Trained on: </dt><dd className="inline">{F.model.origin ? `${F.model.origin.trained_on}${F.model.origin.retrained ? "" : " (not retrained for this dataset)"}` : "unknown"}</dd></div>
              </dl>
              {perf ? (
                <div className="mt-3 overflow-x-auto">
                  <table className="w-full text-left text-sm">
                    <caption className="sr-only">Measured error on this dataset</caption>
                    <thead className="text-xs uppercase text-slate-600">
                      <tr><th scope="col" className="py-1 pr-3">Measured on {perf.date_range[0]} to {perf.date_range[1]}</th><th scope="col" className="py-1 pr-3">Mean MAE °C</th><th scope="col" className="py-1">Mean RMSE °C</th></tr>
                    </thead>
                    <tbody>
                      {Object.entries(perf.models).map(([k, m]) => (
                        <tr key={k} className="border-t border-slate-100"><td className="py-1 pr-3 font-medium capitalize">{k === "convlstm" ? "ConvLSTM" : k}</td><td className="py-1 pr-3">{m.mean_mae.toFixed(3)}</td><td className="py-1">{m.mean_rmse.toFixed(3)}</td></tr>
                      ))}
                    </tbody>
                  </table>
                  <p className="mt-2 text-sm text-slate-800">
                    {perf.beats_persistence ? "The model beat persistence at every horizon." : "The model did not beat persistence at every horizon."} Skill versus persistence by horizon:{" "}
                    {perf.mae_skill_vs_persistence.map((s) => `${(s * 100).toFixed(1)}%`).join(", ")} (positive = better). {perf.n_windows} windows.
                  </p>
                </div>
              ) : (
                <p className="mt-2 text-sm text-slate-700">No evaluation of this model on this dataset exists, so no accuracy is claimed.</p>
              )}
            </section>
          </div>
        )}
      </Status>

      <section className="mt-6" aria-labelledby="fcmap">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <h2 id="fcmap" className="text-lg font-semibold text-slate-900">Forecast map</h2>
          <div className="flex flex-wrap items-center gap-3 text-sm">
            <label className="flex items-center gap-1">Day
              <select value={horizon} onChange={(e) => setHorizon(Number(e.target.value))} className="rounded-md border border-slate-300 bg-white px-2 py-1">
                {[1, 2, 3, 4, 5, 6, 7].map((h) => <option key={h} value={h}>+{h}</option>)}
              </select>
            </label>
            <div role="radiogroup" aria-label="Forecast layer" className="flex overflow-hidden rounded-md border border-slate-300">
              {(["sst", "anomaly"] as const).map((k) => (
                <button key={k} type="button" role="radio" aria-checked={kind === k} onClick={() => setKind(k)} className={`px-3 py-1 ${kind === k ? "bg-deep text-white" : "bg-white text-slate-800"}`}>
                  {k === "sst" ? "Forecast SST" : "Forecast anomaly"}
                </button>
              ))}
            </div>
          </div>
        </div>
        {map.error && <div role="alert" className="mt-2 rounded-md bg-amber-50 px-3 py-2 text-sm text-amber-900">Forecast map unavailable: {map.error}</div>}
        <div className="mt-2">
          <SstMap
            layer={layer}
            fitTo={fitTo}
            lonOrigin={layer ? axisOrigin(layer.lon) : null}
            showOutline={false}
            unavailable={!!map.error}
            badge={M ? `${M.region.name} · forecast for ${M.date} · model output` : undefined}
            initialView="world"
            heightClass="h-[28rem]"
            ariaLabel="Forecast map"
          />
        </div>
        <div className="mt-3"><RelatedLinks to={["map", "heatwaves", "risk", "alerts"]} /></div>
      </section>
    </div>
  );
}
