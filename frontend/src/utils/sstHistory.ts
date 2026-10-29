import type { SstAggregation, SstAnnual, SstPoint, SstTrend } from "../api/environment";

export type SstView = "sst" | "anomaly" | "annual";

export interface ChartRow {
  t: number;
  date: string;
  observed: number | null;
  forecast: number | null;
  trend: number | null;
  observations: number | null;
}

const ms = (d: string) => Date.parse(`${d}T00:00:00Z`);

/** Start of the next step of an aggregation, so a month or year with no data shows as a visible gap instead of the line bridging it. */
function next(d: string, how: SstAggregation): string {
  const t = new Date(ms(d));
  if (how === "annual") t.setUTCFullYear(t.getUTCFullYear() + 1);
  else if (how === "monthly") t.setUTCMonth(t.getUTCMonth() + 1);
  else t.setUTCDate(t.getUTCDate() + 1);
  return t.toISOString().slice(0, 10);
}

/** Observed rows (with explicit null rows where a month/year has no data), the forecast as a separate column that never shares a value with the observations, and, for
 *  the annual view, the fitted trend line. Missing values stay null: they are never zero. */
export function buildRows(
  view: SstView,
  aggregation: SstAggregation,
  series: SstPoint[],
  annual: SstAnnual[],
  forecast: SstPoint[] | null,
  trend: SstTrend | null,
): ChartRow[] {
  const rows: ChartRow[] = [];
  const key = view === "anomaly" ? "anomaly" : "sst";
  if (view === "annual") {
    for (const a of annual) {
      const v = a.mean_sst;
      const fit = trend && trend.slope_per_year != null && trend.anomaly_at_reference_year != null && trend.reference_year != null && a.mean_sst != null && a.mean_anomaly != null
        ? a.mean_sst - a.mean_anomaly + trend.anomaly_at_reference_year + trend.slope_per_year * (a.year - trend.reference_year)
        : null;
      const date = `${a.year}-07-01`;
      rows.push({ t: ms(date), date, observed: v, forecast: null, trend: a.complete ? fit : null, observations: a.observations });
    }
    return rows;
  }
  const have = new Map(series.map((p) => [p.date, p]));
  if (series.length && aggregation !== "daily") {
    for (let d = series[0].date; d <= series[series.length - 1].date; d = next(d, aggregation)) {
      const p = have.get(d);
      rows.push({ t: ms(d), date: d, observed: p ? p[key] : null, forecast: null, trend: null, observations: p?.observations ?? 0 });
    }
  } else {
    for (const p of series) rows.push({ t: ms(p.date), date: p.date, observed: p[key], forecast: null, trend: null, observations: p.observations ?? 1 });
  }
  for (const f of forecast ?? []) rows.push({ t: ms(f.date), date: f.date, observed: null, forecast: f[key], trend: null, observations: null });
  return rows;
}

export const signed = (v: number | null | undefined, d = 2) => (v == null ? "–" : `${v > 0 ? "+" : ""}${v.toFixed(d)}`);
