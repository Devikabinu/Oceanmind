import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import Pagination from "../components/Pagination";
import { listDataSources, listDatasets } from "../api/dataSources";
import type { DataSource, Dataset } from "../types";

const PAGE_SIZE = 10;

export default function Datasets() {
  const [datasets, setDatasets] = useState<Dataset[]>([]);
  const [sources, setSources] = useState<DataSource[]>([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [sourceFilter, setSourceFilter] = useState<string>("");
  const [isLoading, setIsLoading] = useState(true);

  useEffect(() => {
    listDataSources().then(setSources);
  }, []);

  useEffect(() => {
    setIsLoading(true);
    listDatasets({
      page,
      page_size: PAGE_SIZE,
      data_source_id: sourceFilter || undefined,
    })
      .then((result) => {
        setDatasets(result.items);
        setTotal(result.total);
      })
      .finally(() => setIsLoading(false));
  }, [page, sourceFilter]);

  const sourceById = Object.fromEntries(sources.map((s) => [s.id, s.name]));

  return (
    <div>
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-xl font-semibold text-slate-900">Datasets</h1>
          <p className="mt-1 text-sm text-slate-500">Every dataset produced by an ingestion run.</p>
        </div>
        <select
          value={sourceFilter}
          onChange={(e) => {
            setPage(1);
            setSourceFilter(e.target.value);
          }}
          className="rounded-md border border-slate-300 bg-white px-3 py-1.5 text-sm"
        >
          <option value="">All sources</option>
          {sources.map((s) => (
            <option key={s.id} value={s.id}>
              {s.name}
            </option>
          ))}
        </select>
      </div>

      <div className="mt-6 overflow-x-auto rounded-lg border border-slate-200 bg-white">
        <table className="min-w-full divide-y divide-slate-200 text-sm">
          <thead className="bg-slate-50 text-left text-xs font-medium uppercase tracking-wide text-slate-500">
            <tr>
              <th className="px-4 py-2">Name</th>
              <th className="px-4 py-2">Source</th>
              <th className="px-4 py-2">Kind</th>
              <th className="px-4 py-2">Records</th>
              <th className="px-4 py-2">Temporal range</th>
              <th className="px-4 py-2"></th>
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-100">
            {isLoading ? (
              <tr>
                <td colSpan={6} className="px-4 py-6 text-center text-slate-400">
                  Loading...
                </td>
              </tr>
            ) : datasets.length === 0 ? (
              <tr>
                <td colSpan={6} className="px-4 py-6 text-center text-slate-400">
                  No datasets have been loaded yet. Datasets are created by ingestion jobs (Ingestion tab) and by the sync/publish jobs.
                </td>
              </tr>
            ) : (
              datasets.map((dataset) => (
                <tr key={dataset.id}>
                  <td className="px-4 py-2 font-medium text-slate-900">{dataset.name}</td>
                  <td className="px-4 py-2 text-slate-600">
                    {sourceById[dataset.data_source_id] ?? "-"}
                  </td>
                  <td className="px-4 py-2 text-slate-600">{dataset.kind}</td>
                  <td className="px-4 py-2 text-slate-600">{dataset.record_count}</td>
                  <td className="px-4 py-2 text-slate-600">
                    {dataset.temporal_start?.slice(0, 10)} &ndash; {dataset.temporal_end?.slice(0, 10)}
                  </td>
                  <td className="px-4 py-2">
                    <Link
                      to={`/data-quality?dataset_id=${dataset.id}`}
                      className="text-xs font-medium text-slate-600 underline"
                    >
                      Quality &rarr;
                    </Link>
                  </td>
                </tr>
              ))
            )}
          </tbody>
        </table>
      </div>

      <Pagination page={page} pageSize={PAGE_SIZE} total={total} isLoading={isLoading} onPageChange={setPage} />
    </div>
  );
}
