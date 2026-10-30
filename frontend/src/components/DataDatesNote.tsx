import { getDataDates } from "../api/environment";
import { useActive } from "../contexts/ActiveSelection";
import { useAsync } from "../hooks/useAsync";

/** One line that says which day each product refers to, and says so plainly when they differ, so that no product is read as describing another day. */
export default function DataDatesNote() {
  const act = useActive();
  const d = useAsync(() => getDataDates(act.dataset, act.date ?? undefined), [act.dataset, act.date]);
  const D = d.data && !d.isLoading && d.data.dataset === act.dataset ? d.data : null;
  if (d.error || !D) return null;
  const f = D.forecast;
  const r = D.freshness.refresh;
  const when = (t?: string | null) => (t ? `${t.slice(0, 16).replace("T", " ")} UTC` : "not yet");
  const stateLabel = D.freshness.status;
  const failedAttempt = !!r && (r.outcome === "failed" || r.outcome === "source_unavailable" || r.outcome === "interrupted");
  /** The state is written out in words and carries its own symbol (shape), so it never relies on colour alone. */
  const TONE: Record<string, string> = {
    current: "bg-emerald-100 text-emerald-900 before:content-['●_']", delayed: "bg-amber-100 text-amber-900 before:content-['◐_']",
    stale: "bg-red-100 text-red-900 before:content-['▲_']", "refresh failed": "bg-red-100 text-red-900 before:content-['✕_']",
  };
  const badge = `rounded px-1.5 py-0.5 text-[11px] font-semibold ${TONE[stateLabel] ?? "bg-slate-100 text-slate-800"}`;
  const Item = ({ label, children, id }: { label: string; children: React.ReactNode; id?: string }) => (
    <div className="min-w-0"><dt className="text-slate-500">{label}</dt><dd className="font-semibold text-slate-900" data-testid={id}>{children}</dd></div>
  );
  return (
    <details className="mt-3 rounded-lg border border-slate-200 bg-white/90 px-3 py-2 text-xs text-slate-700 shadow-sm" data-testid="data-dates" open={!D.aligned || D.freshness.status !== "current"}>
      <summary className="cursor-pointer text-sm font-semibold text-slate-900">
        Observations through {D.sst_observation.latest_available}
        {" · "}Forecast: {f.valid_dates ? `${f.valid_dates[0]} → ${f.valid_dates[f.valid_dates.length - 1]}` : "not available for this date"}
        {D.aligned ? "" : " · products differ"}
        {D.freshness.status !== "current" ? <>{" · "}<span className={badge} data-testid="dd-badge">{stateLabel}</span></> : null}
      </summary>
      <div className="mt-2 grid gap-3 sm:grid-cols-2">
        <section aria-label="Observations">
          <h2 className="text-[11px] font-semibold uppercase tracking-wide text-slate-600">Observations</h2>
          <dl className="mt-1 grid grid-cols-2 gap-x-3 gap-y-1.5">
            <Item label="Latest source observation (at the last check)" id="dd-source">{r?.source_latest ?? "not confirmed by the last check"}{r?.source_latest && r.source_checked_at ? <span className="block font-normal text-slate-500">checked {when(r.source_checked_at)}</span> : null}</Item>
            <Item label="Latest observation processed" id="dd-processed">{D.sst_observation.latest_available}</Item>
            <Item label="Last successful source check" id="dd-success">{when(r?.last_success_at)}</Item>
            <Item label="Last dataset update" id="dd-update">{when(r?.last_update_at)}</Item>
            <Item label="Data state" id="dd-state"><span className={badge}>{stateLabel}</span>{r?.outcome === "running" ? " (refresh running)" : r?.outcome === "interrupted" ? " (last attempt interrupted)" : failedAttempt ? " (last attempt failed)" : ""}</Item>
            <Item label="Anomaly">{D.anomaly.date}</Item>
            <Item label="Marine heatwaves">{D.marine_heatwave.date ?? "not computed"}</Item>
          </dl>
        </section>
        <section aria-label="Forecast and records">
          <h2 className="text-[11px] font-semibold uppercase tracking-wide text-slate-600">Forecast and records</h2>
          <dl className="mt-1 grid grid-cols-2 gap-x-3 gap-y-1.5">
            <Item label="Forecast initialised from">{f.initialised_from ?? "–"}</Item>
            <Item label="Forecast valid dates">{f.valid_dates ? `${f.valid_dates[0]} to ${f.valid_dates[f.valid_dates.length - 1]}` : "–"}</Item>
            <Item label="Newest species record">{D.species_records.latest_record ?? "none"}</Item>
          </dl>
        </section>
      </div>
      <p className="mt-2 max-w-3xl leading-relaxed text-slate-700">{D.message} {D.freshness.message}</p>
    </details>
  );
}
