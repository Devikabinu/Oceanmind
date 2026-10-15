import { Bar, CartesianGrid, ComposedChart, Legend, Line, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import type { HistoryPoint } from "../api/monitor";

const fmt = (v: unknown) => (typeof v === "number" ? `${v.toFixed(2)} °C` : "–");

/** SST against its seasonal normal and 90th-percentile heatwave threshold, plus the anomaly underneath. */
export default function HistoryChart({ series, height = 220 }: { series: HistoryPoint[]; height?: number }) {
  return (
    <figure>
      <ResponsiveContainer width="100%" height={height}>
        <ComposedChart data={series} margin={{ top: 8, right: 12, bottom: 18, left: 4 }} aria-label="Sea surface temperature history">
          <CartesianGrid strokeDasharray="3 3" stroke="#e2e8f0" />
          <XAxis dataKey="date" tick={{ fontSize: 11 }} minTickGap={36} label={{ value: "Date", position: "insideBottom", offset: -10, fontSize: 11 }} />
          <YAxis domain={["auto", "auto"]} tick={{ fontSize: 11 }} width={48} label={{ value: "SST (°C)", angle: -90, position: "insideLeft", fontSize: 11 }} />
          <Tooltip formatter={fmt} />
          <Legend verticalAlign="top" wrapperStyle={{ fontSize: 11, paddingBottom: 8 }} />
          <Line type="monotone" dataKey="sst" name="Observed SST" stroke="#16a34a" strokeWidth={2} dot={false} />
          <Line type="monotone" dataKey="climatology" name="Normal (2012-2023 average)" stroke="#64748b" strokeDasharray="4 4" dot={false} />
          <Line type="monotone" dataKey="p90_threshold" name="Heatwave threshold (90th percentile)" stroke="#ea580c" strokeDasharray="2 3" dot={false} />
        </ComposedChart>
      </ResponsiveContainer>
      <ResponsiveContainer width="100%" height={150}>
        <ComposedChart data={series} margin={{ top: 4, right: 12, bottom: 18, left: 4 }} aria-label="Sea surface temperature anomaly history">
          <CartesianGrid strokeDasharray="3 3" stroke="#e2e8f0" />
          <XAxis dataKey="date" tick={{ fontSize: 11 }} minTickGap={36} label={{ value: "Date", position: "insideBottom", offset: -10, fontSize: 11 }} />
          <YAxis tick={{ fontSize: 11 }} width={48} label={{ value: "Anomaly (°C)", angle: -90, position: "insideLeft", fontSize: 11 }} />
          <Tooltip formatter={fmt} />
          <Bar dataKey="anomaly" name="Daily anomaly" fill="#fdba74" />
          <Line type="monotone" dataKey="anomaly_7d_mean" name="7-day mean anomaly" stroke="#9a3412" strokeWidth={2} dot={false} />
        </ComposedChart>
      </ResponsiveContainer>
      <figcaption className="text-xs text-slate-600">
        Source: NOAA OISST v2.1 (observation); normal and threshold are derived from 2012-2023. Anomaly = observed minus normal.
      </figcaption>
    </figure>
  );
}
