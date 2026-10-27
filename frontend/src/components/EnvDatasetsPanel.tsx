import { getCoverage, getDatasets } from "../api/environment";
import type { EnvironmentDatasetAvailable } from "../api/environment";
import { useAsync } from "../hooks/useAsync";
import Badge from "./Badge";
import { providerLabel } from "../utils/format";
import SourceTag from "./SourceTag";
import Status from "./Status";

const lonText = (l: number) => (l < 0 ? `${Math.abs(l)}° W` : l > 180 ? `${l}° E (${360 - l}° W)` : `${l}° E`);

function Dataset({ d }: { d: EnvironmentDatasetAvailable }) {
  const cov = useAsync(() => getCoverage({ dataset: d.id, layer: "sst", region: "pacific" }), [d.id]);
  const c = cov.data?.coverage;
  const e = d.extent;
  return (
    <article className="rounded-lg bg-white/80 p-4 ring-1 ring-slate-200" aria-label={d.name}>
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div>
          <h3 className="text-base font-semibold text-slate-900">{d.name}</h3>
          <p className="text-sm text-slate-600">{d.provider.description}</p>
        </div>
        <div className="flex items-center gap-2">
          <Badge tone="slate">{d.id}</Badge>
          <SourceTag kind={d.provider.is_observational ? "observed" : "generated"} />
        </div>
      </div>
      <dl className="mt-3 grid grid-cols-1 gap-x-6 gap-y-2 text-sm md:grid-cols-3">
        <div><dt className="text-xs font-medium uppercase text-slate-500">Provider</dt><dd>{d.provider.source?.provider ?? providerLabel(d.provider)}</dd></div>
        <div><dt className="text-xs font-medium uppercase text-slate-500">Dataset</dt><dd>{d.provider.source?.dataset ?? d.name}</dd></div>
        {d.provider.source?.reference_url && (
          <div><dt className="text-xs font-medium uppercase text-slate-500">Reference</dt><dd><a className="underline" href={d.provider.source.reference_url} target="_blank" rel="noreferrer">{d.provider.source.reference_url}</a></dd></div>
        )}
        {d.provider.source?.urls && d.provider.source.urls.length > 0 && (
          <div className="md:col-span-2"><dt className="text-xs font-medium uppercase text-slate-500">Access points</dt><dd className="break-all">{d.provider.source.urls.map((u) => <a key={u} className="mr-3 underline" href={u} target="_blank" rel="noreferrer">{u}</a>)}</dd></div>
        )}
        {d.provider.source?.citation && <div className="md:col-span-3"><dt className="text-xs font-medium uppercase text-slate-500">Citation</dt><dd>{d.provider.source.citation}</dd></div>}
        {d.provider.source?.update_frequency && <div><dt className="text-xs font-medium uppercase text-slate-500">Update frequency</dt><dd>{d.provider.source.update_frequency}</dd></div>}
        {d.freshness && (
          <div className="md:col-span-2">
            <dt className="text-xs font-medium uppercase text-slate-500">Freshness</dt>
            <dd>
              <span className={`mr-2 rounded px-1.5 py-0.5 text-xs font-semibold ${d.freshness.status === "current" ? "bg-emerald-100 text-emerald-900" : d.freshness.status === "delayed" ? "bg-amber-100 text-amber-900" : "bg-red-100 text-red-900"}`}>{d.freshness.status}</span>
              Observation date {d.freshness.observation_date}. {d.freshness.message}
            </dd>
          </div>
        )}
        {d.provider.source?.final_through && (
          <div><dt className="text-xs font-medium uppercase text-slate-500">Final / preliminary</dt><dd>Final product through {d.provider.source.final_through}{d.preliminary_from ? `; ${d.preliminary_from} onwards is preliminary and may change slightly` : ""}</dd></div>
        )}
        <div><dt className="text-xs font-medium uppercase text-slate-500">Source retrieved</dt><dd>{d.source_timestamp ? d.source_timestamp.slice(0, 16).replace("T", " ") + " UTC" : "not recorded"}</dd></div>
        <div><dt className="text-xs font-medium uppercase text-slate-500">Processed</dt><dd>{d.processed_at ? d.processed_at.slice(0, 16).replace("T", " ") + " UTC" : "not recorded"}</dd></div>
        <div><dt className="text-xs font-medium uppercase text-slate-500">Data type</dt><dd>{d.provider.is_observational ? "Observations (satellite and in-situ analysis)" : "Modelled dataset"}</dd></div>
        <div><dt className="text-xs font-medium uppercase text-slate-500">Variable and units</dt><dd>{d.variable ?? "Sea surface temperature"} · {d.units}</dd></div>
        <div><dt className="text-xs font-medium uppercase text-slate-500">Temporal resolution</dt><dd>{d.temporal_resolution ?? "daily"}</dd></div>
        <div><dt className="text-xs font-medium uppercase text-slate-500">Climatology / baseline</dt><dd>{d.baseline ? `${d.baseline[0]} to ${d.baseline[1]}. ` : ""}{d.climatology ?? "not recorded"}</dd></div>
        <div className="md:col-span-2"><dt className="text-xs font-medium uppercase text-slate-500">Processing</dt><dd>{d.processing}</dd></div>
        <div><dt className="text-xs font-medium uppercase text-slate-500">Update method</dt><dd>{d.update_method}</dd></div>
        <div className="md:col-span-3"><dt className="text-xs font-medium uppercase text-slate-500">Limitations</dt><dd><ul className="list-disc pl-5">{d.limitations?.map((l) => <li key={l}>{l}</li>)}</ul></dd></div>
        <div><dt className="text-xs font-medium uppercase text-slate-500">Spatial coverage</dt><dd>{e.lat_min}° to {e.lat_max}° N, {lonText(e.lon_min)} to {lonText(e.lon_max)}</dd></div>
        <div><dt className="text-xs font-medium uppercase text-slate-500">Resolution and grid</dt><dd>{d.resolution_deg}° · {d.grid_shape[0]} × {d.grid_shape[1]} cells</dd></div>
        <div><dt className="text-xs font-medium uppercase text-slate-500">Longitude convention</dt><dd>{d.lon_convention}</dd></div>
        <div><dt className="text-xs font-medium uppercase text-slate-500">Temporal coverage</dt><dd>{d.first_date} to {d.latest_date} ({d.n_dates.toLocaleString()} days)</dd></div>
        <div><dt className="text-xs font-medium uppercase text-slate-500">Latest available date</dt><dd>{d.latest_date}</dd></div>
        <div>
          <dt className="text-xs font-medium uppercase text-slate-500">Coverage on the latest date</dt>
          <dd>
            {cov.error ? "unavailable" : c ? `${c.valid_cells.toLocaleString()} valid and ${c.missing_cells.toLocaleString()} missing of ${c.ocean_cells.toLocaleString()} ocean cells${c.valid_pct_of_ocean != null ? ` (${c.valid_pct_of_ocean}% valid)` : ""}; ${c.land_cells.toLocaleString()} land` : "loading…"}
          </dd>
        </div>
      </dl>
    </article>
  );
}

/** Environmental datasets as the backend reports them (provider, coverage, resolution, dates, valid and missing cells). Nothing here is hard-coded. */
export default function EnvDatasetsPanel() {
  const ds = useAsync(() => getDatasets(), []);
  return (
    <section className="mb-8" aria-labelledby="envds-h">
      <h2 id="envds-h" className="border-l-4 border-lagoon pl-3 text-lg font-semibold text-slate-900">Environmental datasets</h2>
      <p className="mt-1 text-sm text-slate-600">The datasets every map, risk, heatwave, forecast and alert view can run on. Switch between them with the Dataset selector.</p>
      <Status isLoading={ds.isLoading} error={ds.error} hasData={!!ds.data}>
        <div className="mt-3 space-y-3">
          {ds.data?.datasets.map((d) =>
            d.available ? (
              <Dataset key={d.id} d={d} />
            ) : (
              <article key={d.id} className="rounded-lg border border-amber-300 bg-amber-50 p-4 text-sm text-amber-900">
                <h3 className="font-semibold">{d.name} ({d.id})</h3>
                <p>Not available: {d.message}</p>
              </article>
            ),
          )}
        </div>
      </Status>
    </section>
  );
}
