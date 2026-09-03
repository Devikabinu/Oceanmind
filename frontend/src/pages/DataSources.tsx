import { useEffect, useState } from "react";
import { listDataSources } from "../api/dataSources";
import type { DataSource } from "../types";

export default function DataSources() {
  const [sources, setSources] = useState<DataSource[]>([]);
  const [isLoading, setIsLoading] = useState(true);

  useEffect(() => {
    listDataSources()
      .then(setSources)
      .finally(() => setIsLoading(false));
  }, []);

  return (
    <div>
      <h1 className="text-xl font-semibold text-slate-900">Data Sources</h1>
      <p className="mt-1 text-sm text-slate-500">The registry of external datasets this platform can ingest.</p>

      {isLoading ? (
        <p className="mt-6 text-sm text-slate-400">Loading...</p>
      ) : (
        <div className="mt-6 grid grid-cols-1 gap-4 lg:grid-cols-3">
          {sources.map((source) => (
            <div key={source.id} className="rounded-lg border border-slate-200 bg-white p-5">
              <div className="flex items-start justify-between">
                <h2 className="text-sm font-semibold text-slate-900">{source.name}</h2>
                <span
                  className={`rounded px-1.5 py-0.5 text-xs font-medium ${
                    source.status === "ACTIVE"
                      ? "bg-green-50 text-green-700"
                      : "bg-slate-100 text-slate-500"
                  }`}
                >
                  {source.status}
                </span>
              </div>
              <p className="mt-1 text-xs text-slate-500">{source.provider}</p>
              <p className="mt-3 text-sm text-slate-600">{source.description}</p>
              <dl className="mt-4 space-y-1 text-xs text-slate-500">
                <div className="flex justify-between">
                  <dt>Dataset</dt>
                  <dd className="text-right text-slate-700">{source.dataset}</dd>
                </div>
                <div className="flex justify-between">
                  <dt>Version</dt>
                  <dd className="text-slate-700">{source.version}</dd>
                </div>
                <div className="flex justify-between">
                  <dt>Last updated</dt>
                  <dd className="text-slate-700">
                    {new Date(source.last_updated).toLocaleDateString()}
                  </dd>
                </div>
              </dl>
              <a
                href={source.source_url}
                target="_blank"
                rel="noreferrer"
                className="mt-4 inline-block text-xs font-medium text-slate-600 underline"
              >
                Source &rarr;
              </a>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
