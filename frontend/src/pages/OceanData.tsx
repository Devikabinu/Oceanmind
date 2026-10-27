import { useState } from "react";
import { getCoverage, getRegions } from "../api/intelligence";
import type { SourceInfo } from "../api/intelligence";
import Badge from "../components/Badge";
import PageHeader from "../components/PageHeader";
import SourceTag from "../components/SourceTag";
import Status from "../components/Status";
import { useAsync } from "../hooks/useAsync";
import { cached } from "../hooks/useCached";
import EnvDatasetsPanel from "../components/EnvDatasetsPanel";
import DataQuality from "./DataQuality";
import DataSources from "./DataSources";
import Datasets from "./Datasets";
import Ingestion from "./Ingestion";

const fmtDate = (v?: string | null) => (v ? v.slice(0, 10) : "–");

function SourceCard({ s }: { s: SourceInfo }) {
  const db = s.database;
  return (
    <article className="rounded-lg border border-slate-200 bg-white p-4" aria-label={s.name}>
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div>
          <h3 className="text-base font-semibold text-slate-900">{s.name}</h3>
          <p className="text-sm text-slate-600">{s.provider}</p>
        </div>
        <div className="flex items-center gap-2">
          {db.status && <span title="Whether the source is enabled in the data-source registry; see Status in the table above for whether data are loaded"><Badge tone="slate">{`Registry: ${db.status}`}</Badge></span>}
          <SourceTag kind={s.data_type.toLowerCase().includes("model") ? "forecast" : "observed"} />
        </div>
      </div>
      <dl className="mt-3 grid grid-cols-1 gap-x-6 gap-y-2 text-sm md:grid-cols-2">
        <div><dt className="text-xs font-medium uppercase text-slate-500">Data type</dt><dd className="text-slate-800">{s.data_type}</dd></div>
        <div><dt className="text-xs font-medium uppercase text-slate-500">Variables</dt><dd className="text-slate-800">{s.variables.join(", ")}</dd></div>
        <div><dt className="text-xs font-medium uppercase text-slate-500">Geographic coverage (source)</dt><dd className="text-slate-800">{s.coverage_source}</dd></div>
        <div><dt className="text-xs font-medium uppercase text-slate-500">Temporal coverage / updates (source)</dt><dd className="text-slate-800">{s.temporal_source}</dd></div>
        <div className="md:col-span-2">
          <dt className="text-xs font-medium uppercase text-slate-500">Loaded in this project</dt>
          <dd className="text-slate-800">{s.loaded_in_project ?? "Nothing loaded"}</dd>
        </div>
        {s.update_frequency && <div><dt className="text-xs font-medium uppercase text-slate-500">Update frequency</dt><dd className="text-slate-800">{s.update_frequency}</dd></div>}
        {s.resolution && <div><dt className="text-xs font-medium uppercase text-slate-500">Resolution</dt><dd className="text-slate-800">{s.resolution}</dd></div>}
        {s.baseline && <div><dt className="text-xs font-medium uppercase text-slate-500">Baseline for anomalies</dt><dd className="text-slate-800">{s.baseline[0].slice(0, 4)} to {s.baseline[1].slice(0, 4)}</dd></div>}
        {s.freshness && (
          <div>
            <dt className="text-xs font-medium uppercase text-slate-500">Freshness</dt>
            <dd className="text-slate-800">
              <span className={`mr-2 rounded px-1.5 py-0.5 text-xs font-semibold ${s.freshness.status === "current" ? "bg-emerald-100 text-emerald-900" : s.freshness.status === "delayed" ? "bg-amber-100 text-amber-900" : "bg-red-100 text-red-900"}`}>{s.freshness.status}</span>
              {s.freshness.message}
            </dd>
          </div>
        )}
        {s.last_updated && <div><dt className="text-xs font-medium uppercase text-slate-500">Last updated here</dt><dd className="text-slate-800">{s.last_updated.slice(0, 16).replace("T", " ")} UTC</dd></div>}
        {s.processing && <div className="md:col-span-2"><dt className="text-xs font-medium uppercase text-slate-500">Processing</dt><dd className="text-slate-800">{s.processing}</dd></div>}
        {s.limitations && s.limitations.length > 0 && (
          <div className="md:col-span-2"><dt className="text-xs font-medium uppercase text-slate-500">Limitations</dt><dd className="text-slate-800"><ul className="list-disc pl-5">{s.limitations.map((l) => <li key={l}>{l}</li>)}</ul></dd></div>
        )}
        {db.registered && (
          <>
            <div><dt className="text-xs font-medium uppercase text-slate-500">Stored datasets / records</dt><dd className="text-slate-800">{db.datasets ?? 0} datasets · {(db.records ?? 0).toLocaleString()} records</dd></div>
            <div><dt className="text-xs font-medium uppercase text-slate-500">Stored time range</dt><dd className="text-slate-800">{fmtDate(db.temporal_start)} → {fmtDate(db.temporal_end)}</dd></div>
            <div><dt className="text-xs font-medium uppercase text-slate-500">Last successful ingestion</dt><dd className="text-slate-800">{db.last_successful_ingestion ? db.last_successful_ingestion.slice(0, 16).replace("T", " ") : "None recorded"}</dd></div>
          </>
        )}
      </dl>
      <p className="mt-3 flex flex-wrap gap-x-4 text-xs">
        {s.documentation && <a href={s.documentation} className="underline" target="_blank" rel="noreferrer">Source documentation</a>}
        {s.url && <a href={s.url} className="break-all underline" target="_blank" rel="noreferrer">Data access point</a>}
      </p>
    </article>
  );
}

const STATUS_TONE = { loaded: "green", integrated: "yellow", not_loaded: "slate" } as const;

function DatasetTable({ items }: { items: SourceInfo[] }) {
  const [dataset, setDataset] = useState("");
  const [status, setStatus] = useState("");
  const [since, setSince] = useState("");
  const rows = items.filter((s) => (!dataset || s.id === dataset) && (!status || s.status_kind === status) && (!since || (s.latest_date != null && s.latest_date >= since)));
  return (
    <div>
      <div className="flex flex-wrap items-end gap-3">
        <label className="flex flex-col gap-1 text-xs font-medium text-slate-600">
          Dataset
          <select value={dataset} onChange={(e) => setDataset(e.target.value)} className="rounded-md border border-slate-300 bg-white px-2 py-1.5 text-sm">
            <option value="">All datasets</option>
            {items.map((s) => <option key={s.id} value={s.id}>{s.name}</option>)}
          </select>
        </label>
        <label className="flex flex-col gap-1 text-xs font-medium text-slate-600">
          Status
          <select value={status} onChange={(e) => setStatus(e.target.value)} className="rounded-md border border-slate-300 bg-white px-2 py-1.5 text-sm">
            <option value="">Any status</option>
            <option value="loaded">Loaded</option>
            <option value="integrated">Integrated, not loaded</option>
            <option value="not_loaded">Not loaded</option>
          </select>
        </label>
        <label className="flex flex-col gap-1 text-xs font-medium text-slate-600">
          Latest data on or after
          <input type="date" value={since} onChange={(e) => setSince(e.target.value)} className="rounded-md border border-slate-300 bg-white px-2 py-1.5 text-sm" />
        </label>
        <span className="pb-1.5 text-sm text-slate-600">{rows.length} of {items.length} datasets</span>
      </div>
      <div className="mt-3 overflow-x-auto rounded-lg border border-slate-200 bg-white">
        <table className="w-full text-left text-sm">
          <caption className="sr-only">Datasets: provider, variables, coverage, resolution, latest date, records and status</caption>
          <thead className="bg-slate-50 text-xs uppercase text-slate-600">
            <tr>
              {["Dataset", "Provider", "Variable", "Temporal coverage", "Spatial coverage (loaded)", "Resolution", "Latest available date", "Records", "Status", "Source"].map((h) => (
                <th key={h} scope="col" className="px-3 py-2">{h}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {rows.length === 0 ? (
              <tr><td colSpan={10} className="px-3 py-6 text-center text-slate-600">No dataset matches these filters (a dataset with no loaded data has no latest date, so it is hidden by the date filter). Clear a filter to see all datasets.</td></tr>
            ) : (
              rows.map((s) => (
                <tr key={s.id} className="border-t border-slate-100 align-top">
                  <td className="px-3 py-2 font-medium text-slate-900">{s.name}</td>
                  <td className="px-3 py-2">{s.provider}</td>
                  <td className="px-3 py-2">{s.variables.join(", ")}</td>
                  <td className="px-3 py-2">{s.temporal_source}</td>
                  <td className="px-3 py-2">{s.spatial_loaded}</td>
                  <td className="px-3 py-2">{s.resolution}</td>
                  <td className="px-3 py-2">{s.latest_date ?? "–"}</td>
                  <td className="px-3 py-2">{s.records_label}</td>
                  <td className="px-3 py-2"><Badge tone={STATUS_TONE[s.status_kind]}>{s.status_label}</Badge></td>
                  <td className="px-3 py-2">{s.documentation ? <a href={s.documentation} target="_blank" rel="noreferrer" className="underline">Documentation</a> : "This project"}</td>
                </tr>
              ))
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
}

function Coverage() {
  const cov = useAsync(() => cached("coverage", getCoverage), []);
  const regions = useAsync(() => cached("regions", getRegions), []);
  const [regionFilter, setRegionFilter] = useState("");
  const regionRows = regions.data?.regions.filter((r) => !regionFilter || r.project_data === regionFilter) ?? [];
  return (
    <div className="space-y-6">
      <section aria-labelledby="src-h">
        <h2 id="src-h" className="text-lg font-semibold text-slate-900">Where the information comes from</h2>
        <p className="mt-1 text-sm text-slate-600">
          The coverage a provider offers is not the same as what this project has loaded. Both are shown so that no dataset appears to cover more of the ocean than it does.
        </p>
        <div className="mt-3">
          <Status isLoading={cov.isLoading} error={cov.error} hasData={!!cov.data}>
            {cov.data && <DatasetTable items={cov.data.items} />}
            <h3 className="mb-2 mt-6 text-sm font-semibold text-slate-900">Details by source</h3>
            <div className="space-y-3">{cov.data?.items.map((s) => <SourceCard key={s.id} s={s} />)}</div>
          </Status>
        </div>
      </section>
      <section aria-labelledby="reg-h">
        <h2 id="reg-h" className="text-lg font-semibold text-slate-900">Coverage by ocean region</h2>
        <label className="mt-2 flex items-center gap-2 text-sm text-slate-700">
          Show regions with
          <select value={regionFilter} onChange={(e) => setRegionFilter(e.target.value)} className="rounded-md border border-slate-300 bg-white px-2 py-1 text-sm">
            <option value="">Any coverage</option>
            <option value="partial">Environmental model data (partial)</option>
            <option value="none">No environmental model data</option>
          </select>
        </label>
        <Status isLoading={regions.isLoading} error={regions.error} hasData={!!regions.data}>
          {regions.data && (
            <div className="mt-3 overflow-x-auto rounded-lg border border-slate-200 bg-white">
              <table className="w-full text-left text-sm">
                <caption className="sr-only">Project data by ocean region</caption>
                <thead className="bg-slate-50 text-xs uppercase text-slate-600">
                  <tr>
                    <th scope="col" className="px-3 py-2">Region</th>
                    <th scope="col" className="px-3 py-2">Environmental model (SST, forecast, heatwave, risk)</th>
                    <th scope="col" className="px-3 py-2">Stored OBIS biodiversity records</th>
                    <th scope="col" className="px-3 py-2">Note</th>
                  </tr>
                </thead>
                <tbody>
                  {regionRows.length === 0 && (
                    <tr><td colSpan={4} className="px-3 py-6 text-center text-slate-600">No ocean region has this coverage level. Choose “Any coverage”.</td></tr>
                  )}
                  {regionRows.map((r) => (
                    <tr key={r.id} className="border-t border-slate-100 align-top">
                      <td className="px-3 py-2 font-medium text-slate-900">{r.name}</td>
                      <td className="px-3 py-2">{r.project_data === "partial" ? "Partial (study region only)" : "No data"}</td>
                      <td className="px-3 py-2">{r.stored_species_records?.toLocaleString() ?? "–"}</td>
                      <td className="px-3 py-2 text-slate-700">{r.note}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </Status>
      </section>
    </div>
  );
}

const TABS = [
  { id: "coverage", label: "Coverage", Page: Coverage },
  { id: "sources", label: "Data sources", Page: DataSources },
  { id: "datasets", label: "Datasets", Page: Datasets },
  { id: "ingestion", label: "Ingestion", Page: Ingestion },
  { id: "quality", label: "Data quality", Page: DataQuality },
] as const;

type TabId = (typeof TABS)[number]["id"];

export default function OceanData() {
  const [tab, setTab] = useState<TabId>("coverage");
  const Active = TABS.find((t) => t.id === tab)!.Page;
  return (
    <div>
      <PageHeader title="Ocean data">Sources, coverage, stored datasets, ingestion jobs and data-quality reports behind everything in the platform.</PageHeader>
      <div className="mt-4"><EnvDatasetsPanel /></div>
      <div role="tablist" aria-label="Ocean data views" className="mb-6 mt-4 flex flex-wrap gap-1 border-b border-slate-200">
        {TABS.map((t) => (
          <button
            key={t.id}
            role="tab"
            aria-selected={tab === t.id}
            type="button"
            onClick={() => setTab(t.id)}
            className={`-mb-px border-b-2 px-4 py-2 text-sm font-medium ${tab === t.id ? "border-slate-900 text-slate-900" : "border-transparent text-slate-600 hover:text-slate-900"}`}
          >
            {t.label}
          </button>
        ))}
      </div>
      <div role="tabpanel">
        <Active />
      </div>
    </div>
  );
}
