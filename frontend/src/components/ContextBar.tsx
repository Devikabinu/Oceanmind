import { getDates, getDatasets, getRegions } from "../api/environment";
import { useActive } from "../contexts/ActiveSelection";
import { useAsync } from "../hooks/useAsync";
import { cached } from "../hooks/useCached";

const field = "flex min-w-0 max-w-full flex-col gap-1 text-[11px] font-semibold uppercase tracking-[0.12em] text-cyan-100/90";
const sel = "w-full min-w-0 max-w-full rounded-md border border-white/30 bg-white px-2 py-1.5 text-sm font-normal normal-case tracking-normal text-slate-900";

/** The shared Dataset / Region / Date controls for pages that do not have their own toolbar. Changing them changes the selection for every related page. */
export default function ContextBar({ showRegion = true, showDate = false, note }: { showRegion?: boolean; showDate?: boolean; note?: string }) {
  const act = useActive();
  const datasets = useAsync(() => cached("env-datasets", getDatasets), []);
  const regions = useAsync(() => (showRegion ? cached("env-regions", getRegions) : Promise.resolve(null)), [showRegion]);
  const dates = useAsync(() => (showDate ? cached(`env-dates-${act.dataset}`, () => getDates(act.dataset)) : Promise.resolve(null)), [showDate, act.dataset]);
  const ds = datasets.data?.datasets.find((d) => d.id === act.dataset);
  const range = dates.data && dates.data.dataset === act.dataset ? dates.data : null;
  return (
    <div className="on-deep flex flex-wrap items-end gap-x-4 gap-y-3 rounded-xl bg-gradient-to-r from-deep via-abyss to-tide px-4 py-3 text-white" data-testid="context-bar">
      <label className={field}>
        Dataset
        <select className={sel} value={act.dataset} onChange={(e) => act.setDataset(e.target.value)}>
          {!ds && <option value={act.dataset}>{act.dataset}</option>}
          {datasets.data?.datasets.map((d) => (
            <option key={d.id} value={d.id} disabled={!d.available}>
              {d.name}
              {d.available ? "" : " (not available)"}
            </option>
          ))}
        </select>
      </label>
      {showRegion && (
        <label className={field}>
          Region
          <select className={sel} value={act.region} onChange={(e) => act.setRegion(e.target.value)}>
            {!regions.data?.regions.some((r) => r.id === act.region) && <option value={act.region}>{act.region}</option>}
            {regions.data?.regions.map((r) => (
              <option key={r.id} value={r.id}>
                {r.parent && r.parent !== "pacific" ? "\u00a0\u00a0" : ""}
                {r.name}
              </option>
            ))}
          </select>
        </label>
      )}
      {showDate && range && (
        <label className={field}>
          Date
          <input type="date" className={sel} min={range.first_date} max={range.latest_date} value={act.date ?? range.latest_date} onChange={(e) => act.setDate(e.target.value || null)} />
        </label>
      )}
      <p className="flex flex-wrap items-center gap-x-3 gap-y-1 pb-1 text-xs text-cyan-50">
        {ds && ds.available && (
          <>
            <span className="text-cyan-200/80" title={ds.provider.description}>Dataset source on Ocean Data</span>
            <span className="text-cyan-200/80">latest {ds.latest_date}</span>
          </>
        )}
        {ds && !ds.available && <span className="text-amber-200">{ds.message}</span>}
        {note && <span className="text-cyan-100/90">{note}</span>}
      </p>
    </div>
  );
}
