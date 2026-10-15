import { useState } from "react";
import { Area, CartesianGrid, ComposedChart, Legend, Line, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { getPerformance, getRegion } from "../api/monitor";
import type { RegionName } from "../api/monitor";
import { useAsync } from "../hooks/useAsync";
import { cached } from "../hooks/useCached";
import SourceTag from "./SourceTag";
import Status from "./Status";
import Term from "./Term";

export const REGION_LABELS: Record<RegionName, string> = {
  all: "Whole study region (20–50°N, 160–120°W)",
  north: "Northern half (35–50°N)",
  south: "Southern half (20–35°N)",
  west: "Western part (160–140°W)",
  east: "Eastern part (140–120°W)",
};

const fmt = (v: unknown) => (typeof v === "number" ? `${v.toFixed(2)} °C` : "–");

/** Regional-mean forecast for the next 7 days from the last observed day, with the model's typical error as a band. */
export default function RegionForecast({ withTable = false }: { withTable?: boolean }) {
  const [region, setRegion] = useState<RegionName>("all");
  const { data, error, isLoading } = useAsync(() => getRegion(region), [region]);
  const perf = useAsync(() => cached("performance", getPerformance), []);

  const rows =
    data &&
    [
      { day: "Day 0", date: data.latest.observed_date, forecast: data.latest.sst_c, normal: null as number | null, range: null as [number, number] | null },
      ...data.horizons.map((h, i) => {
        const f = data.latest.forecast[i];
        const mae = perf.data?.models.convlstm.mae[i];
        return {
          day: `Day ${h}`,
          date: data.latest.dates[i],
          forecast: f,
          normal: data.latest.climatology[i],
          range: f != null && mae != null ? ([f - mae, f + mae] as [number, number]) : null,
        };
      }),
    ];
  const vals = rows?.flatMap((r) => [r.forecast, r.normal, ...(r.range ?? [])].filter((v): v is number => typeof v === "number")) ?? [];
  const lo = vals.length ? Math.floor((Math.min(...vals) - 0.2) * 2) / 2 : 0;
  const hi = vals.length ? Math.ceil((Math.max(...vals) + 0.4) * 2) / 2 : 1;

  return (
    <div className="rounded-lg border border-slate-200 bg-white p-4">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h2 className="text-sm font-semibold text-slate-900">Forecast: regional mean SST, next 7 days</h2>
        <div className="flex items-center gap-2">
          <select
            aria-label="Region"
            value={region}
            onChange={(e) => setRegion(e.target.value as RegionName)}
            className="rounded-md border border-slate-300 bg-white px-2 py-1 text-sm text-slate-800"
          >
            {(Object.keys(REGION_LABELS) as RegionName[]).map((r) => (
              <option key={r} value={r}>
                {REGION_LABELS[r]}
              </option>
            ))}
          </select>
          <SourceTag kind="forecast" />
        </div>
      </div>
      <div className="mt-3">
        <Status isLoading={isLoading} error={error} hasData={!!data}>
          {data && rows && (
            <>
              <ResponsiveContainer width="100%" height={260}>
                <ComposedChart data={rows} margin={{ top: 8, right: 16, bottom: 18, left: 4 }} aria-label="Seven day SST forecast">
                  <CartesianGrid strokeDasharray="3 3" stroke="#e2e8f0" />
                  <XAxis dataKey="day" tick={{ fontSize: 12 }} label={{ value: "Days after last observation", position: "insideBottom", offset: -10, fontSize: 11 }} />
                  <YAxis domain={[lo, hi]} tick={{ fontSize: 12 }} width={52} label={{ value: "SST (°C)", angle: -90, position: "insideLeft", fontSize: 11 }} />
                  <Tooltip formatter={fmt} labelFormatter={(l, items) => `${String(l)} · ${items?.[0]?.payload?.date ?? ""}`} />
                  <Legend verticalAlign="top" wrapperStyle={{ fontSize: 12, paddingBottom: 8 }} />
                  <Area dataKey="range" stroke="none" fill="#bfdbfe" fillOpacity={0.6} name="Typical error range (± test MAE)" />
                  <Line type="monotone" dataKey="forecast" name="ConvLSTM forecast (Day 0 = last observed)" stroke="#2563eb" strokeWidth={2.5} dot={{ r: 3 }} />
                  <Line type="monotone" dataKey="normal" name="Normal for the date (2012–2023 average)" stroke="#94a3b8" strokeDasharray="4 4" dot={false} />
                </ComposedChart>
              </ResponsiveContainer>
              {withTable && (
                <div className="mt-3 overflow-x-auto">
                  <table className="w-full text-left text-sm">
                    <caption className="sr-only">Forecast by day</caption>
                    <thead className="text-xs uppercase text-slate-600">
                      <tr>
                        <th scope="col" className="py-1 pr-3">Horizon</th>
                        <th scope="col" className="py-1 pr-3">Date</th>
                        <th scope="col" className="py-1 pr-3">Forecast °C</th>
                        <th scope="col" className="py-1 pr-3">Normal °C</th>
                        <th scope="col" className="py-1">
                          <Term k="anomaly">Anomaly</Term> °C
                        </th>
                      </tr>
                    </thead>
                    <tbody>
                      {data.horizons.map((h, i) => {
                        const f = data.latest.forecast[i];
                        const n = data.latest.climatology[i];
                        return (
                          <tr key={h} className="border-t border-slate-100">
                            <td className="py-1 pr-3 font-medium">+{h} d</td>
                            <td className="py-1 pr-3 text-slate-600">{data.latest.dates[i]}</td>
                            <td className="py-1 pr-3 font-medium text-blue-800">{f?.toFixed(2) ?? "–"}</td>
                            <td className="py-1 pr-3">{n?.toFixed(2) ?? "–"}</td>
                            <td className="py-1">{f != null && n != null ? `${f - n > 0 ? "+" : ""}${(f - n).toFixed(2)}` : "–"}</td>
                          </tr>
                        );
                      })}
                    </tbody>
                  </table>
                </div>
              )}
              <p className="mt-2 text-xs text-slate-600">
                Mean over {data.n_cells.toLocaleString()} ocean cells. Forecast issued from {data.latest.observed_date} (the last processed observation). The
                shaded band is the model&apos;s typical absolute error at each horizon on the test period (<Term k="mae">MAE</Term>), not a statistical confidence interval.
              </p>
            </>
          )}
        </Status>
      </div>
    </div>
  );
}
