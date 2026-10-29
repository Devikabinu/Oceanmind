import { useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { Brush, CartesianGrid, ComposedChart, Legend, Line, ReferenceLine, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { getSstHistory } from "../api/environment";
import type { SstAggregation } from "../api/environment";
import { useActive } from "../contexts/ActiveSelection";
import { useAsync } from "../hooks/useAsync";
import { buildRows, signed } from "../utils/sstHistory";
import type { ChartRow, SstView } from "../utils/sstHistory";
import SourceTag from "./SourceTag";
import Status from "./Status";

const VIEWS: { id: SstView; label: string }[] = [
  { id: "sst", label: "SST" },
  { id: "anomaly", label: "SST anomaly" },
  { id: "annual", label: "Annual mean SST" },
];
const year = (t: number) => String(new Date(t).getUTCFullYear());
const day = (t: number) => new Date(t).toISOString().slice(0, 10);

/** The Historical SST section of the Dashboard: observed SST (or anomaly, or annual means) over the whole record for the selected place or region, with the forecast drawn as a
 *  separate dashed series. The place is the one picked on the Ocean Map; without one the graph shows the area-weighted mean of the selected region. */
export default function HistoricalSst() {
  const act = useActive();
  const [view, setView] = useState<SstView>("sst");
  const [aggregation, setAggregation] = useState<SstAggregation>("monthly");
  const point = act.point;
  const h = useAsync(
    () => getSstHistory({ dataset: act.dataset, region: act.region, lat: point?.lat, lon: point?.lon, aggregation }),
    [act.dataset, act.region, point?.lat, point?.lon, aggregation],
  );
  // never draw a result that belongs to another dataset, region, place or resolution
  const H = h.data && !h.isLoading && h.data.dataset.id === act.dataset && h.data.aggregation === aggregation && (point ? h.data.location !== null : h.data.location === null && h.data.region.id === act.region) ? h.data : null;
  const rows = useMemo<ChartRow[]>(() => (H ? buildRows(view, aggregation, H.series, H.annual_summary, view === "annual" ? null : H.forecast?.series ?? null, H.trend) : []), [H, view, aggregation]);
  const unit = "°C";
  const selectedT = act.date ? Date.parse(`${act.date}T00:00:00Z`) : null;
  const tr = H?.trend;
  const st = H?.statistics;
  const yLabel = view === "anomaly" ? "SST anomaly (°C)" : view === "annual" ? "Annual mean SST (°C)" : "Sea surface temperature (°C)";

  return (
    <section className="rounded-xl bg-white/80 p-4 ring-1 ring-slate-200" aria-labelledby="hist-sst-title" data-testid="historical-sst">
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div>
          <h2 id="hist-sst-title" className="text-base font-semibold text-slate-900">Historical SST Change</h2>
          <p className="text-xs text-slate-600">
            {H ? <>Showing <strong>{H.scope.name}</strong>{H.scope.type === "location" ? ` (grid cell ${H.location!.cell.lat.toFixed(2)}°, ${H.location!.cell.lon_180.toFixed(2)}°)` : ""}. </> : null}
            {point ? (
              <button type="button" className="font-semibold text-tide hover:underline" onClick={() => act.setPoint(null)}>Show the {H?.region.name ?? "whole region"} instead</button>
            ) : (
              <>Click a place on the <Link to={`/ocean-map${act.toQuery({ layer: "sst" })}`} className="font-semibold text-tide hover:underline">Ocean Map</Link> to see its own history.</>
            )}
          </p>
        </div>
        <div className="flex items-center gap-2">
          <SourceTag kind="observed" />
          {H?.forecast && view !== "annual" && <SourceTag kind="forecast" />}
        </div>
      </div>

      <div className="mt-2 flex flex-wrap items-center gap-x-4 gap-y-2">
        <div role="radiogroup" aria-label="Graph" className="flex overflow-hidden rounded-md border border-slate-300 text-sm">
          {VIEWS.map((v) => (
            <button key={v.id} type="button" role="radio" aria-checked={view === v.id} onClick={() => setView(v.id)}
              className={`px-3 py-1 ${view === v.id ? "bg-deep font-semibold text-white" : "bg-white text-slate-800 hover:bg-slate-50"}`}>{v.label}</button>
          ))}
        </div>
        {view !== "annual" && (
          <label className="flex items-center gap-1.5 text-xs text-slate-700">
            Resolution
            <select aria-label="Resolution" value={aggregation} onChange={(e) => setAggregation(e.target.value as SstAggregation)} className="rounded border border-slate-300 bg-white px-1.5 py-1 text-xs">
              <option value="monthly">Monthly means</option>
              <option value="daily">Daily values</option>
            </select>
          </label>
        )}
      </div>

      <Status isLoading={h.isLoading} error={h.error} hasData={!!H}>
        {H && (
          <>
            <dl className="mt-3 grid grid-cols-2 gap-2 text-sm sm:grid-cols-3 lg:grid-cols-5" aria-label="Historical SST summary">
              <div className="rounded-md bg-slate-50 p-2"><dt className="text-xs text-slate-600">Period</dt><dd className="font-semibold text-slate-900">{H.period.start.slice(0, 4)}–{H.period.end.slice(0, 4)}</dd></div>
              <div className="rounded-md bg-slate-50 p-2"><dt className="text-xs text-slate-600">Mean SST</dt><dd className="font-semibold text-slate-900">{st?.mean_sst == null ? "–" : `${st.mean_sst.toFixed(1)} ${unit}`}</dd></div>
              <div className="rounded-md bg-slate-50 p-2">
                <dt className="text-xs text-slate-600">Change</dt>
                <dd className="font-semibold text-slate-900" title={H.change?.basis}>{H.change?.mean_sst_change == null ? "–" : `${signed(H.change.mean_sst_change)} ${unit}`}</dd>
                {H.change && <dd className="text-[11px] text-slate-500">{H.change.from_year} to {H.change.to_year} annual means</dd>}
              </div>
              <div className="rounded-md bg-slate-50 p-2">
                <dt className="text-xs text-slate-600">Trend</dt>
                <dd className="font-semibold text-slate-900">{tr?.slope_per_year == null ? "n/a" : `${signed(tr.slope_per_year)} ${unit}/year`}</dd>
                <dd className="text-[11px] text-slate-500">{tr?.slope_per_year == null ? "record too short" : tr.significant ? `${tr.direction}, significant` : "not significant"}</dd>
              </div>
              <div className="rounded-md bg-slate-50 p-2"><dt className="text-xs text-slate-600">Data points</dt><dd className="font-semibold text-slate-900">{st?.observations.toLocaleString()}</dd><dd className="text-[11px] text-slate-500">of {st?.expected_days.toLocaleString()} days</dd></div>
            </dl>

            {rows.length === 0 ? (
              <p className="mt-3 rounded-md bg-slate-50 p-3 text-sm text-slate-700" role="status">No SST observations are available for this place and period.</p>
            ) : (
              <div className="mt-3" role="img" aria-label={`${yLabel} for ${H.scope.name}, ${H.period.start} to ${H.period.end}`}>
                <ResponsiveContainer width="100%" height={300}>
                  <ComposedChart data={rows} margin={{ top: 8, right: 16, bottom: 4, left: 4 }}>
                    <CartesianGrid strokeDasharray="3 3" stroke="#e2e8f0" />
                    <XAxis dataKey="t" type="number" scale="time" domain={["dataMin", "dataMax"]} tickFormatter={year} tick={{ fontSize: 11 }} minTickGap={32} label={{ value: "Year", position: "insideBottom", offset: -2, fontSize: 11 }} />
                    <YAxis tick={{ fontSize: 11 }} width={48} domain={["auto", "auto"]} tickFormatter={(v) => Number(v).toFixed(1)} label={{ value: yLabel, angle: -90, position: "insideLeft", fontSize: 11 }} />
                    <Tooltip content={<HistTooltip view={view} />} />
                    <Legend verticalAlign="top" wrapperStyle={{ fontSize: 11, paddingBottom: 6 }} />
                    <Line type="monotone" dataKey="observed" name={view === "annual" ? "Observed annual mean (°C)" : view === "anomaly" ? "Observed anomaly (°C)" : "Observed SST (°C)"} stroke="#0f766e" strokeWidth={view === "annual" ? 2 : 1.6}
                      dot={view === "annual" ? { r: 3 } : false} connectNulls={false} isAnimationActive={false} />
                    {view !== "annual" && H.forecast && (
                      <Line type="monotone" dataKey="forecast" name="Forecast (model prediction)" stroke="#c2410c" strokeWidth={2.5} strokeDasharray="5 4" dot={{ r: 3 }} connectNulls={false} isAnimationActive={false} />
                    )}
                    {view === "annual" && <Line type="linear" dataKey="trend" name="Linear trend (complete years)" stroke="#475569" strokeDasharray="6 4" dot={false} connectNulls isAnimationActive={false} />}
                    {selectedT != null && selectedT >= rows[0].t && <ReferenceLine x={selectedT} stroke="#0f172a" strokeDasharray="2 3" label={{ value: "selected date", fontSize: 10, position: "insideTopRight" }} />}
                    {rows.length > 24 && <Brush dataKey="t" height={22} stroke="#0f766e" tickFormatter={year} travellerWidth={8} />}
                  </ComposedChart>
                </ResponsiveContainer>
                <p className="text-[11px] text-slate-500">Drag the handles under the graph to zoom to a period. Gaps in the line are periods with no data (never drawn as zero).{H.forecast && view !== "annual" ? ` The dashed orange line is the model forecast issued from ${H.forecast.issued_from}; it is a prediction, not an observation.` : ""}</p>
              </div>
            )}

            <div className="mt-3 space-y-1 text-xs text-slate-700">
              <p><strong>{H.statement}</strong></p>
              <p>{tr?.message}{tr?.ci95 && tr.slope_per_year != null ? ` Trend ${signed(tr.slope_per_year, 3)} °C/year (95% interval ${signed(tr.ci95[0], 3)} to ${signed(tr.ci95[1], 3)}, ${tr.n_years} complete years).` : ""}</p>
              <p>
                Data: {H.dataset.name}; {st?.observations.toLocaleString()} observations of {st?.expected_days.toLocaleString()} days
                {st && st.missing_days > 0 ? ` (${st.missing_days.toLocaleString()} days without data are left out, not set to zero)` : ""}; range {st?.min_sst?.toFixed(1)}–{st?.max_sst?.toFixed(1)} °C.
                {H.baseline ? ` Anomalies are relative to the ${H.baseline[0].slice(0, 4)}–${H.baseline[1].slice(0, 4)} daily climatology.` : ""} {H.percent_change_note}
              </p>
            </div>
          </>
        )}
      </Status>
    </section>
  );
}

function HistTooltip({ active, payload, view }: { active?: boolean; payload?: { payload: ChartRow }[]; view: SstView }) {
  if (!active || !payload?.length) return null;
  const r = payload[0].payload;
  const isForecast = r.forecast != null;
  const v = isForecast ? r.forecast : r.observed;
  const label = view === "annual" ? `Year ${year(r.t)}` : day(r.t);
  return (
    <div className="rounded-md border border-slate-300 bg-white p-2 text-xs shadow">
      <div className="font-semibold text-slate-900">{label}</div>
      <div className={isForecast ? "text-orange-800" : "text-teal-800"}>
        {isForecast ? "Forecast (prediction)" : view === "anomaly" ? "Observed anomaly" : view === "annual" ? "Observed annual mean" : "Observed SST"}: {v == null ? "no data" : `${view === "anomaly" ? signed(v) : v.toFixed(2)} °C`}
      </div>
      {!isForecast && r.observations != null && <div className="text-slate-500">{r.observations.toLocaleString()} observation{r.observations === 1 ? "" : "s"}</div>}
    </div>
  );
}
