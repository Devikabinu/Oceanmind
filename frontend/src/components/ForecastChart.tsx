import { CartesianGrid, Legend, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";

export interface ForecastSeries {
  horizons: number[];
  dates: string[];
  forecast: (number | null)[];
  observed: (number | null)[];
  climatology: (number | null)[];
  persistence: (number | null)[] | null;
  last_observed: number | null;
}

/** Hindcast verification: Day 0 = last input day; days 1..7 = forecast vs what was later observed, persistence, climatology. */
export default function ForecastChart({ series, height = 280 }: { series: ForecastSeries; height?: number }) {
  const data = [
    {
      day: "Day 0",
      date: series.dates.length ? "last input day" : "",
      forecast: series.last_observed,
      observed: series.last_observed,
      persistence: series.last_observed,
      climatology: null as number | null,
    },
    ...series.horizons.map((h, i) => ({
      day: `Day ${h}`,
      date: series.dates[i],
      forecast: series.forecast[i],
      observed: series.observed[i],
      persistence: series.persistence?.[i] ?? null,
      climatology: series.climatology[i],
    })),
  ];
  const values = data.flatMap((d) => [d.forecast, d.observed, d.persistence, d.climatology].filter((v): v is number => typeof v === "number"));
  const lo = Math.floor((Math.min(...values) - 0.2) * 2) / 2;
  const hi = Math.ceil((Math.max(...values) + 0.2) * 2) / 2;

  return (
    <ResponsiveContainer width="100%" height={height}>
      <LineChart data={data} margin={{ top: 8, right: 16, bottom: 18, left: 4 }} aria-label="Forecast versus observed SST">
        <CartesianGrid strokeDasharray="3 3" stroke="#e2e8f0" />
        <XAxis dataKey="day" tick={{ fontSize: 12 }} label={{ value: "Days after last input", position: "insideBottom", offset: -10, fontSize: 11 }} />
        <YAxis domain={[lo, hi]} tick={{ fontSize: 12 }} width={52} label={{ value: "SST (°C)", angle: -90, position: "insideLeft", fontSize: 11 }} />
        <Tooltip
          formatter={(v) => (typeof v === "number" ? `${v.toFixed(2)} °C` : "–")}
          labelFormatter={(label, items) => `${String(label)} · ${items?.[0]?.payload?.date ?? ""}`}
        />
        <Legend verticalAlign="top" wrapperStyle={{ fontSize: 12, paddingBottom: 8 }} />
        <Line type="monotone" dataKey="forecast" name="ConvLSTM forecast (model output)" stroke="#2563eb" strokeWidth={2.5} dot={{ r: 3 }} />
        <Line type="monotone" dataKey="observed" name="Observed (verification)" stroke="#16a34a" strokeWidth={2} dot={{ r: 3 }} />
        <Line type="monotone" dataKey="persistence" name="Persistence baseline" stroke="#f59e0b" strokeDasharray="5 4" dot={false} />
        <Line type="monotone" dataKey="climatology" name="Climatology baseline" stroke="#94a3b8" strokeDasharray="2 4" dot={false} />
      </LineChart>
    </ResponsiveContainer>
  );
}
