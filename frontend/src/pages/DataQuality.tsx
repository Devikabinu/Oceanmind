import { useEffect, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { Bar, BarChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { listDatasets } from "../api/dataSources";
import { getQualityReports } from "../api/quality";
import type { DataQualityReport, Dataset } from "../types";

export default function DataQuality() {
  const [searchParams, setSearchParams] = useSearchParams();
  const selectedDatasetId = searchParams.get("dataset_id") ?? "";

  const [datasets, setDatasets] = useState<Dataset[]>([]);
  const [reports, setReports] = useState<DataQualityReport[]>([]);
  const [isLoading, setIsLoading] = useState(false);

  useEffect(() => {
    listDatasets({ page_size: 100 }).then((result) => setDatasets(result.items));
  }, []);

  useEffect(() => {
    if (!selectedDatasetId) {
      setReports([]);
      return;
    }
    setIsLoading(true);
    getQualityReports(selectedDatasetId)
      .then(setReports)
      .finally(() => setIsLoading(false));
  }, [selectedDatasetId]);

  const latest = reports[0];
  const chartData = latest
    ? [
        { reason: "Valid", count: latest.records_valid },
        { reason: "Missing", count: latest.missing_values },
        { reason: "Duplicate", count: latest.duplicate_records },
        { reason: "Bad coords", count: latest.invalid_coordinates },
        { reason: "Bad timestamp", count: latest.invalid_timestamps },
        { reason: "Bad SST", count: latest.invalid_sst },
      ]
    : [];

  return (
    <div>
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-xl font-semibold text-slate-900">Data Quality</h1>
          <p className="mt-1 text-sm text-slate-500">Per-dataset validation results from the ingestion pipeline.</p>
        </div>
        <select
          value={selectedDatasetId}
          onChange={(e) => setSearchParams(e.target.value ? { dataset_id: e.target.value } : {})}
          className="rounded-md border border-slate-300 bg-white px-3 py-1.5 text-sm"
        >
          <option value="">Select a dataset...</option>
          {datasets.map((d) => (
            <option key={d.id} value={d.id}>
              {d.name}
            </option>
          ))}
        </select>
      </div>

      {!selectedDatasetId ? (
        <p className="mt-6 text-sm text-slate-400">Select a dataset to view its quality reports.</p>
      ) : isLoading ? (
        <p className="mt-6 text-sm text-slate-400">Loading...</p>
      ) : reports.length === 0 ? (
        <p className="mt-6 text-sm text-slate-400">No quality report exists for this dataset. Reports are written when an ingestion job completes.</p>
      ) : (
        <>
          <div className="mt-6 rounded-lg border border-slate-200 bg-white p-5">
            <h2 className="text-sm font-semibold text-slate-900">Rejection breakdown (most recent run)</h2>
            <div className="mt-4 h-64">
              <ResponsiveContainer width="100%" height="100%">
                <BarChart data={chartData}>
                  <CartesianGrid strokeDasharray="3 3" stroke="#e2e8f0" />
                  <XAxis dataKey="reason" tick={{ fontSize: 12 }} />
                  <YAxis tick={{ fontSize: 12 }} />
                  <Tooltip />
                  <Bar dataKey="count" fill="#0f172a" radius={[4, 4, 0, 0]} isAnimationActive={false} />
                </BarChart>
              </ResponsiveContainer>
            </div>
          </div>

          <div className="mt-6 overflow-x-auto rounded-lg border border-slate-200 bg-white">
            <table className="min-w-full divide-y divide-slate-200 text-sm">
              <thead className="bg-slate-50 text-left text-xs font-medium uppercase tracking-wide text-slate-500">
                <tr>
                  <th className="px-4 py-2">Run</th>
                  <th className="px-4 py-2">Read</th>
                  <th className="px-4 py-2">Valid</th>
                  <th className="px-4 py-2">Rejected</th>
                  <th className="px-4 py-2">Missing</th>
                  <th className="px-4 py-2">Duplicates</th>
                  <th className="px-4 py-2">Bad coords</th>
                  <th className="px-4 py-2">Bad timestamps</th>
                  <th className="px-4 py-2">Bad SST</th>
                  <th className="px-4 py-2">Outliers</th>
                  <th className="px-4 py-2">Schema mismatches</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-100">
                {reports.map((report) => (
                  <tr key={report.id}>
                    <td className="px-4 py-2 text-slate-600">
                      {new Date(report.created_at).toLocaleString()}
                    </td>
                    <td className="px-4 py-2 text-slate-600">{report.records_read}</td>
                    <td className="px-4 py-2 text-slate-600">{report.records_valid}</td>
                    <td className="px-4 py-2 text-slate-600">{report.records_rejected}</td>
                    <td className="px-4 py-2 text-slate-600">{report.missing_values}</td>
                    <td className="px-4 py-2 text-slate-600">{report.duplicate_records}</td>
                    <td className="px-4 py-2 text-slate-600">{report.invalid_coordinates}</td>
                    <td className="px-4 py-2 text-slate-600">{report.invalid_timestamps}</td>
                    <td className="px-4 py-2 text-slate-600">{report.invalid_sst}</td>
                    <td className="px-4 py-2 text-slate-600">{report.outliers}</td>
                    <td className="px-4 py-2 text-slate-600">{report.schema_mismatches}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </>
      )}
    </div>
  );
}
