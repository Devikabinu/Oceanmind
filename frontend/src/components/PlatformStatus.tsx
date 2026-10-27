import { getDates, getDatasets, getRegions } from "../api/environment";
import { useActive } from "../contexts/ActiveSelection";
import { useAsync } from "../hooks/useAsync";
import { cached } from "../hooks/useCached";

/** One line of data context for the header: the ACTIVE dataset, region and date, whether the data are observations or modelled, and the latest available date.
 *  All values come from the API. */
export default function PlatformStatus() {
  const act = useActive();
  const info = useAsync(async () => {
    const [list, regions] = await Promise.all([cached("env-datasets", getDatasets), cached("env-regions", getRegions)]);
    const ds = list.datasets.find((d) => d.id === act.dataset);
    const region = regions.regions.find((r) => r.id === act.region)?.name ?? act.region;
    if (!ds) return { name: act.dataset, region, latest: null, observational: null as boolean | null, unavailable: `not provided by the backend` };
    if (!ds.available) return { name: ds.name, region, latest: null, observational: null as boolean | null, unavailable: ds.message };
    const dates = await cached(`env-dates-${ds.id}`, () => getDates(ds.id));
    return { name: ds.name, region, latest: dates.latest_date, observational: ds.provider.is_observational, unavailable: null as string | null };
  }, [act.dataset, act.region]);

  if (info.error) return <span className="text-xs text-amber-800" role="status">Environmental data service unavailable</span>;
  if (!info.data) return <span className="text-xs text-slate-500" role="status">Checking data…</span>;
  const d = info.data;
  return (
    <p className="flex flex-wrap items-center gap-x-2 gap-y-0.5 text-xs text-slate-600" aria-label="Active dataset, region and date">
      <span className="font-semibold text-slate-800">{d.name}</span>
      <span aria-hidden>·</span>
      <span>{d.region}</span>
      {d.unavailable ? (
        <span className="text-amber-800">· dataset unavailable: {d.unavailable}</span>
      ) : (
        <>
          <span aria-hidden>·</span>
          <span>{act.date ? `date ${act.date}` : `latest ${d.latest}`}</span>
          <span aria-hidden>·</span>
          <span className="text-slate-500" title={d.observational ? "Measured data" : "Modelled dataset, not direct observations (see Ocean Data)"}>
            {d.observational ? "observed data" : "modelled data"}
          </span>
        </>
      )}
    </p>
  );
}
