import { useState } from "react";
import { Area, CartesianGrid, ComposedChart, Legend, Line, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { getHeatwaveSeries } from "../api/intelligence";
import { useAsync } from "../hooks/useAsync";
import SourceTag from "./SourceTag";
import Status from "./Status";
import Term from "./Term";

const RANGES = [
  { days: 90, label: "90 days" },
  { days: 365, label: "1 year" },
  { days: 1095, label: "3 years" },
];

/** Whole-region history: mean SST anomaly and the share of ocean area in a marine heatwave. */
export default function TrendCharts({ dataset }: { dataset?: string }) {
  const [days, setDays] = useState(365);
  const { data, error, isLoading } = useAsync(() => getHeatwaveSeries(days, dataset), [days, dataset]);
  const rows = data?.dates.map((d, i) => ({
    date: d,
    anomaly: data.mean_anomaly[i],
    sst: data.mean_sst[i],
    share: +((data.heatwave_area_km2[i] / data.ocean_area_km2) * 100).toFixed(2),
  }));
  return (
    <div className="rounded-lg border border-slate-200 bg-white p-4">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h2 className="text-sm font-semibold text-slate-900">{dataset && dataset !== "ne_pacific" ? "Trends across the dataset domain" : "Trends in the study region"}</h2>
        <div className="flex items-center gap-2">
          <div role="group" aria-label="Time range" className="flex overflow-hidden rounded-md border border-slate-300 text-sm">
            {RANGES.map((r) => (
              <button
                key={r.days}
                type="button"
                aria-pressed={days === r.days}
                onClick={() => setDays(r.days)}
                className={`px-2.5 py-1 ${days === r.days ? "bg-slate-900 text-white" : "bg-white text-slate-700 hover:bg-slate-50"}`}
              >
                {r.label}
              </button>
            ))}
          </div>
          <SourceTag kind="derived" />
        </div>
      </div>
      <Status isLoading={isLoading} error={error} hasData={!!rows}>
        {rows && (
          <div className="mt-3 grid grid-cols-1 gap-4 lg:grid-cols-2">
            <figure>
              <figcaption className="mb-1 text-xs font-medium text-slate-700">
                Mean <Term k="anomaly">SST anomaly</Term> (°C above the 2012–2023 average)
              </figcaption>
              <ResponsiveContainer width="100%" height={200}>
                <ComposedChart data={rows} margin={{ top: 4, right: 12, bottom: 18, left: 4 }} aria-label="Mean SST anomaly over time">
                  <CartesianGrid strokeDasharray="3 3" stroke="#e2e8f0" />
                  <XAxis dataKey="date" tick={{ fontSize: 11 }} minTickGap={40} label={{ value: "Date", position: "insideBottom", offset: -10, fontSize: 11 }} />
                  <YAxis tick={{ fontSize: 11 }} width={48} label={{ value: "Anomaly (°C)", angle: -90, position: "insideLeft", fontSize: 11 }} />
                  <Tooltip formatter={(v) => (typeof v === "number" ? `${v.toFixed(2)} °C` : "–")} />
                  <Line type="monotone" dataKey="anomaly" name="Mean anomaly" stroke="#b45309" strokeWidth={1.8} dot={false} />
                </ComposedChart>
              </ResponsiveContainer>
            </figure>
            <figure>
              <figcaption className="mb-1 text-xs font-medium text-slate-700">
                Share of ocean area in a <Term k="heatwave">marine heatwave</Term> (project definition, %)
              </figcaption>
              <ResponsiveContainer width="100%" height={200}>
                <ComposedChart data={rows} margin={{ top: 4, right: 12, bottom: 18, left: 4 }} aria-label="Marine heatwave area share over time">
                  <CartesianGrid strokeDasharray="3 3" stroke="#e2e8f0" />
                  <XAxis dataKey="date" tick={{ fontSize: 11 }} minTickGap={40} label={{ value: "Date", position: "insideBottom", offset: -10, fontSize: 11 }} />
                  <YAxis tick={{ fontSize: 11 }} width={48} unit="%" label={{ value: "Area (%)", angle: -90, position: "insideLeft", fontSize: 11 }} />
                  <Tooltip formatter={(v) => (typeof v === "number" ? `${v.toFixed(1)} %` : "–")} />
                  <Legend verticalAlign="top" wrapperStyle={{ fontSize: 11, paddingBottom: 8 }} />
                  <Area type="monotone" dataKey="share" name="Area in heatwave" stroke="#c2410c" fill="#fdba74" />
                </ComposedChart>
              </ResponsiveContainer>
            </figure>
          </div>
        )}
      </Status>
      <p className="mt-2 text-xs text-slate-600">
        Source: NOAA OISST v2.1 (processed study region). Anomaly and heatwave state are derived metrics; the heatwave definition is simplified (see the Marine
        Heatwaves page).
      </p>
    </div>
  );
}
