import type { ReactNode } from "react";
import { getHistory, getLocation } from "../api/monitor";
import { useAsync } from "../hooks/useAsync";
import EmptyState from "./EmptyState";
import FactorBars from "./FactorBars";
import HistoryChart from "./HistoryChart";
import SeverityBadge from "./SeverityBadge";
import SourceTag from "./SourceTag";
import Term from "./Term";
import WhyPanel from "./WhyPanel";

const signed = (v: number, d = 1) => `${v > 0 ? "+" : ""}${v.toFixed(d)}`;

function Row({ label, value, note }: { label: ReactNode; value: ReactNode; note?: string }) {
  return (
    <div className="flex items-baseline justify-between gap-3 border-b border-slate-100 py-1.5 text-sm">
      <dt className="text-slate-600">{label}</dt>
      <dd className="text-right font-medium text-slate-900">
        {value}
        {note && <div className="text-xs font-normal text-slate-500">{note}</div>}
      </dd>
    </div>
  );
}

/** What is known about one clicked location, with the evidence and a plain-language reading. */
export default function LocationPanel({ point }: { point: { lat: number; lon: number } | null }) {
  const loc = useAsync(() => (point ? getLocation(point.lat, point.lon) : Promise.resolve(null)), [point?.lat, point?.lon]);
  const hist = useAsync(
    () => (point && loc.data?.in_coverage && loc.data.is_ocean ? getHistory(point.lat, point.lon, 180) : Promise.resolve(null)),
    [point?.lat, point?.lon, loc.data?.in_coverage, loc.data?.is_ocean],
  );

  if (!point) {
    return (
      <div className="rounded-lg border border-slate-200 bg-white p-4 text-sm text-slate-600">
        <div className="text-xs font-medium uppercase tracking-wide text-slate-600">Selected location</div>
        <p className="mt-2">Click anywhere on the map to see sea surface temperature, anomaly, forecast, risk and marine-heatwave status for that spot.</p>
      </div>
    );
  }
  if (loc.isLoading && !loc.data) return <div className="rounded-lg border border-slate-200 bg-white p-4 text-sm text-slate-600">Loading location…</div>;
  if (loc.error) return <div className="rounded-lg border border-amber-200 bg-amber-50 p-4 text-sm text-amber-800">{loc.error}</div>;
  const d = loc.data;
  if (!d) return null;
  const title = `${Math.abs(point.lat).toFixed(2)}°${point.lat >= 0 ? "N" : "S"}, ${Math.abs(point.lon).toFixed(2)}°${point.lon < 0 ? "W" : "E"}`;
  if (!d.in_coverage || !d.is_ocean || !d.observed || !d.forecast || !d.risk) {
    return (
      <div className="rounded-lg border border-slate-200 bg-white p-4">
        <div className="text-xs font-medium uppercase tracking-wide text-slate-600">Selected location</div>
        <div className="mt-1 text-sm font-semibold text-slate-900">{title}</div>
        <div className="mt-3">
          <EmptyState title={d.in_coverage ? "No ocean data at this spot" : "Outside the area covered by this project's data"}>
            <p>{d.message}</p>
            <p>
              Data coverage: {d.coverage.lat_min.toFixed(0)}–{d.coverage.lat_max.toFixed(0)}°N, {Math.abs(d.coverage.lon_max).toFixed(0)}–
              {Math.abs(d.coverage.lon_min).toFixed(0)}°W (<Term k="coverage">what is this?</Term>). Try a point inside the dashed outline.
            </p>
          </EmptyState>
        </div>
      </div>
    );
  }
  const hw = d.heatwave;
  const f7 = d.forecast.sst_c[d.forecast.sst_c.length - 1];
  return (
    <div className="space-y-4 rounded-lg border border-slate-200 bg-white p-4">
      <div>
        <div className="text-xs font-medium uppercase tracking-wide text-slate-600">Selected location</div>
        <div className="text-sm font-semibold text-slate-900">{title}</div>
        <div className="text-xs text-slate-500">Grid cell centre {d.cell?.lat.toFixed(3)}°, {d.cell?.lon.toFixed(3)}°</div>
      </div>
      <dl>
        <Row label={<>Current <Term k="sst">SST</Term> <SourceTag kind="observed" /></>} value={`${d.observed.sst_c.toFixed(1)} °C`} note={`observed ${d.observed.date}`} />
        <Row label={<><Term k="anomaly">SST anomaly</Term> <SourceTag kind="derived" /></>} value={`${signed(d.observed.anomaly_c)} °C`} note={`normal ${d.observed.climatology_c.toFixed(1)} °C`} />
        <Row
          label={<>Forecast, +{d.forecast.sst_c.length} days <SourceTag kind="forecast" /></>}
          value={f7 == null ? "–" : `${f7.toFixed(1)} °C`}
          note={d.forecast.day7_change_c == null ? undefined : `${signed(d.forecast.day7_change_c)} °C vs now`}
        />
        <Row label={<>Environmental risk <SourceTag kind="derived" /></>} value={<SeverityBadge level={d.risk.level} />} note={`score ${d.risk.score.toFixed(2)} (0-1)`} />
        <Row
          label={<><Term k="heatwave">Marine heatwave</Term> <SourceTag kind="derived" /></>}
          value={hw ? (hw.active ? `ACTIVE (day ${hw.run_days})` : "Not active") : "n/a"}
          note={hw?.percentile != null ? `warmer than ${hw.percentile.toFixed(0)}% of baseline values` : undefined}
        />
        <Row
          label="Potential species overlap"
          value={d.risk.n_species == null ? "No species data loaded" : `${d.risk.n_species} species`}
          note="OBIS records, 2x2° block, last 2 years"
        />
      </dl>
      <WhyPanel title="What does this mean?" reasons={[...(d.explanation ?? []), ...d.risk.reasons.slice(1)]} classification="Observation + model output + project indicator (potential exposure, not proof of harm)" />
      <div>
        <div className="mb-1 text-sm font-semibold text-slate-900">Risk factors</div>
        <FactorBars factors={d.risk.factors} />
      </div>
      <div>
        <div className="mb-1 text-sm font-semibold text-slate-900">Last 180 days at this location</div>
        {hist.isLoading && <p className="text-sm text-slate-500">Loading history…</p>}
        {hist.data && <HistoryChart series={hist.data.series} />}
      </div>
    </div>
  );
}
