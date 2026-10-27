import type { ReactNode } from "react";
import { getPoint } from "../api/environment";
import type { EnvironmentLayer, EnvironmentPoint } from "../api/environment";
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


function PanelShell({ place, children }: { place: string; children: ReactNode }) {
  return (
    <section aria-label="Selected location" className="overflow-hidden rounded-xl bg-white shadow-sm ring-1 ring-slate-200">
      <div className="on-deep bg-gradient-to-r from-deep to-tide px-4 py-2.5 text-white">
        <div className="text-[11px] font-semibold uppercase tracking-[0.14em] text-cyan-100/90">Selected location</div>
        <div className="text-lg font-semibold tabular-nums">{place}</div>
      </div>
      <div className="space-y-4 p-4">{children}</div>
    </section>
  );
}

function Meta({ fresh }: { fresh: EnvironmentPoint }) {
  const gen = !fresh.provider.is_observational;
  return (
    <dl className="space-y-1 border-t border-slate-200 pt-3 text-xs text-slate-600">
      <div className="flex justify-between gap-3"><dt>Dataset</dt><dd className="text-right font-medium text-slate-800">{fresh.dataset.name}</dd></div>
      <div className="flex justify-between gap-3"><dt>Date</dt><dd className="font-medium text-slate-800">{fresh.date}</dd></div>
      <div className="flex justify-between gap-3"><dt>Source</dt><dd className="text-right font-medium text-slate-800">{fresh.provider.provider_id}</dd></div>
      <div className="flex justify-between gap-3">
        <dt>Data status</dt>
        <dd className={`rounded px-1.5 py-0.5 font-semibold ${gen ? "bg-amber-100 text-amber-900" : "bg-emerald-100 text-emerald-900"}`}>
          {gen ? "Modelled dataset" : "Observational"}
        </dd>
      </div>
      <p className="pt-1 text-slate-500">Marine-heatwave, ecological-risk and forecast evidence for this place is on the linked pages below.</p>
    </dl>
  );
}

/** What is known about one clicked location, with the evidence and a plain-language reading. */
export interface EnvironmentSelection {
  dataset: string;
  /** The date the map is currently showing (null while it is still loading). */
  date: string | null;
  layer: EnvironmentLayer;
}

/** `environment`: look the point up in that /api/environment dataset (date and layer as shown on the map). Without it: the NE Pacific dashboard lookup. */
export default function LocationPanel({ point, environment }: { point: { lat: number; lon: number } | null; environment?: EnvironmentSelection }) {
  const env = useAsync(
    () => (point && environment?.date ? getPoint(environment.dataset, point.lat, point.lon, environment.date, environment.layer) : Promise.resolve(null)),
    [point?.lat, point?.lon, environment?.dataset, environment?.date, environment?.layer],
  );
  const loc = useAsync(() => (point && !environment ? getLocation(point.lat, point.lon) : Promise.resolve(null)), [point?.lat, point?.lon, !!environment]);
  const hist = useAsync(
    () => (point && !environment && loc.data?.in_coverage && loc.data.is_ocean ? getHistory(point.lat, point.lon, 180) : Promise.resolve(null)),
    [point?.lat, point?.lon, !!environment, loc.data?.in_coverage, loc.data?.is_ocean],
  );

  if (!point) {
    return (
      <div className="rounded-xl bg-white p-4 text-sm text-slate-600 shadow-sm ring-1 ring-slate-200">
        <div className="text-[11px] font-semibold uppercase tracking-[0.14em] text-slate-600">Selected location</div>
        <p className="mt-2">{environment ? "Click anywhere on the map to see the sea surface temperature and anomaly of that grid cell on the selected date." : "Click anywhere on the map to see sea surface temperature, anomaly, forecast, risk and marine-heatwave status for that spot."}</p>
      </div>
    );
  }
  if (environment) {
    const e = env.data;
    const place = `${Math.abs(point.lat).toFixed(2)}° ${point.lat >= 0 ? "N" : "S"} · ${Math.abs(point.lon).toFixed(2)}° ${point.lon < 0 ? "W" : "E"}`;
    // only show a result that belongs to this click, date and dataset
    const fresh = e && !env.isLoading && e.dataset.id === environment.dataset && e.date === environment.date && e.query.lat === point.lat && e.query.lon === point.lon ? e : null;
    if (env.error) return <div role="alert" className="rounded-xl border border-amber-300 bg-amber-50 p-4 text-sm text-amber-900">Location data unavailable: {env.error}</div>;
    if (!fresh) {
      return (
        <PanelShell place={place}>
          <p role="status" className="text-sm text-slate-600">Loading location…</p>
        </PanelShell>
      );
    }
    if (fresh.status !== "valid") {
      const title =
        fresh.status === "land" ? "Land" : fresh.status === "missing" ? "No data for this ocean cell on this date" : "Outside this dataset";
      return (
        <PanelShell place={place}>
          <div className="rounded-lg border border-dashed border-slate-300 bg-slate-50 p-3">
            <div className="text-sm font-semibold text-slate-900">{title}</div>
            <p className="mt-1 text-sm text-slate-700">{fresh.message}</p>
          </div>
          <Meta fresh={fresh} />
        </PanelShell>
      );
    }
    return (
      <PanelShell place={place}>
        {fresh.cell && <p className="-mt-1 text-xs text-slate-500">Matched grid cell {fresh.cell.lat.toFixed(2)}° N · {Math.abs(fresh.cell.lon_180).toFixed(2)}° {fresh.cell.lon_180 < 0 ? "W" : "E"}</p>}
        <div>
          <div className="text-[11px] font-semibold uppercase tracking-[0.12em] text-slate-600"><Term k="sst">Sea surface temperature</Term></div>
          <div className="text-4xl font-semibold tracking-tight text-slate-900">{fresh.sst == null ? "–" : `${fresh.sst.toFixed(1)} °C`}</div>
        </div>
        <div>
          <div className="text-[11px] font-semibold uppercase tracking-[0.12em] text-slate-600"><Term k="anomaly">Anomaly</Term> (difference from normal)</div>
          <div className={`text-3xl font-semibold tracking-tight ${fresh.anomaly == null ? "text-slate-500" : fresh.anomaly > 0.5 ? "text-orange-700" : fresh.anomaly < -0.5 ? "text-sky-800" : "text-slate-900"}`}>
            {fresh.anomaly == null ? "–" : `${signed(fresh.anomaly)} °C`}
            {fresh.anomaly != null && <span className="ml-2 text-sm font-medium">{fresh.anomaly > 0.5 ? "warmer than normal" : fresh.anomaly < -0.5 ? "colder than normal" : "near normal"}</span>}
          </div>
          {fresh.anomaly == null && fresh.message && <p className="text-xs text-slate-600">{fresh.message}</p>}
        </div>
        <Meta fresh={fresh} />
      </PanelShell>
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
