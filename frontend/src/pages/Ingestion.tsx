import { useEffect, useRef, useState } from "react";
import type { FormEvent } from "react";
import axios from "axios";
import { useAuth } from "../contexts/AuthContext";
import { listIngestionJobs, startIngestion } from "../api/ingestion";
import type { IngestionSource } from "../api/ingestion";
import type { IngestionJob, IngestionJobStatus } from "../types";

const SOURCES: { value: IngestionSource; label: string }[] = [
  { value: "noaa", label: "NOAA OISST v2.1" },
  { value: "copernicus", label: "Copernicus Marine SST" },
  { value: "obis", label: "OBIS" },
];

const STATUS_STYLES: Record<IngestionJobStatus, string> = {
  PENDING: "bg-slate-100 text-slate-600",
  RUNNING: "bg-blue-50 text-blue-700",
  COMPLETED: "bg-green-50 text-green-700",
  FAILED: "bg-red-50 text-red-700",
};

const POLL_INTERVAL_MS = 3000;

export default function Ingestion() {
  const { user } = useAuth();
  const canIngest = user?.role === "ADMIN" || user?.role === "RESEARCHER";

  const [source, setSource] = useState<IngestionSource>("noaa");
  const [startDate, setStartDate] = useState("2023-06-01");
  const [endDate, setEndDate] = useState("2023-06-10");
  const [minLat, setMinLat] = useState("10");
  const [maxLat, setMaxLat] = useState("15");
  const [minLon, setMinLon] = useState("70");
  const [maxLon, setMaxLon] = useState("75");
  const [error, setError] = useState<string | null>(null);
  const [isSubmitting, setIsSubmitting] = useState(false);

  const [jobs, setJobs] = useState<IngestionJob[]>([]);
  const hasActiveJob = jobs.some((j) => j.status === "PENDING" || j.status === "RUNNING");
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);

  async function refreshJobs() {
    const result = await listIngestionJobs({ page_size: 20 });
    setJobs(result);
  }

  useEffect(() => {
    void refreshJobs();
  }, []);

  useEffect(() => {
    if (hasActiveJob && !pollRef.current) {
      pollRef.current = setInterval(() => void refreshJobs(), POLL_INTERVAL_MS);
    }
    if (!hasActiveJob && pollRef.current) {
      clearInterval(pollRef.current);
      pollRef.current = null;
    }
    return () => {
      if (pollRef.current) {
        clearInterval(pollRef.current);
        pollRef.current = null;
      }
    };
  }, [hasActiveJob]);

  async function handleSubmit(event: FormEvent) {
    event.preventDefault();
    setError(null);
    setIsSubmitting(true);
    try {
      await startIngestion(source, {
        start_date: startDate,
        end_date: endDate,
        min_latitude: Number(minLat),
        max_latitude: Number(maxLat),
        min_longitude: Number(minLon),
        max_longitude: Number(maxLon),
      });
      await refreshJobs();
    } catch (err) {
      if (axios.isAxiosError(err) && err.response?.data?.detail) {
        setError(String(err.response.data.detail));
      } else {
        setError("Failed to start ingestion.");
      }
    } finally {
      setIsSubmitting(false);
    }
  }

  return (
    <div>
      <h1 className="text-xl font-semibold text-slate-900">Ingestion</h1>
      <p className="mt-1 text-sm text-slate-500">
        Pull a geographic/temporal subset from a registered data source into the platform.
      </p>

      {canIngest ? (
        <form
          onSubmit={handleSubmit}
          className="mt-6 grid grid-cols-2 gap-4 rounded-lg border border-slate-200 bg-white p-5 sm:grid-cols-4"
        >
          <div className="col-span-2 sm:col-span-1">
            <label className="block text-xs font-medium text-slate-600">Source</label>
            <select
              value={source}
              onChange={(e) => setSource(e.target.value as IngestionSource)}
              className="mt-1 w-full rounded-md border border-slate-300 bg-white px-2 py-1.5 text-sm"
            >
              {SOURCES.map((s) => (
                <option key={s.value} value={s.value}>
                  {s.label}
                </option>
              ))}
            </select>
          </div>
          <div>
            <label className="block text-xs font-medium text-slate-600">Start date</label>
            <input
              type="date"
              required
              value={startDate}
              onChange={(e) => setStartDate(e.target.value)}
              className="mt-1 w-full rounded-md border border-slate-300 px-2 py-1.5 text-sm"
            />
          </div>
          <div>
            <label className="block text-xs font-medium text-slate-600">End date</label>
            <input
              type="date"
              required
              value={endDate}
              onChange={(e) => setEndDate(e.target.value)}
              className="mt-1 w-full rounded-md border border-slate-300 px-2 py-1.5 text-sm"
            />
          </div>
          <div />
          <div>
            <label className="block text-xs font-medium text-slate-600">Min latitude</label>
            <input
              type="number"
              step="any"
              required
              value={minLat}
              onChange={(e) => setMinLat(e.target.value)}
              className="mt-1 w-full rounded-md border border-slate-300 px-2 py-1.5 text-sm"
            />
          </div>
          <div>
            <label className="block text-xs font-medium text-slate-600">Max latitude</label>
            <input
              type="number"
              step="any"
              required
              value={maxLat}
              onChange={(e) => setMaxLat(e.target.value)}
              className="mt-1 w-full rounded-md border border-slate-300 px-2 py-1.5 text-sm"
            />
          </div>
          <div>
            <label className="block text-xs font-medium text-slate-600">Min longitude</label>
            <input
              type="number"
              step="any"
              required
              value={minLon}
              onChange={(e) => setMinLon(e.target.value)}
              className="mt-1 w-full rounded-md border border-slate-300 px-2 py-1.5 text-sm"
            />
          </div>
          <div>
            <label className="block text-xs font-medium text-slate-600">Max longitude</label>
            <input
              type="number"
              step="any"
              required
              value={maxLon}
              onChange={(e) => setMaxLon(e.target.value)}
              className="mt-1 w-full rounded-md border border-slate-300 px-2 py-1.5 text-sm"
            />
          </div>

          {error && <p className="col-span-full text-sm text-red-600">{error}</p>}

          <div className="col-span-full">
            <button
              type="submit"
              disabled={isSubmitting}
              className="rounded-md bg-slate-900 px-4 py-2 text-sm font-medium text-white hover:bg-slate-800 disabled:opacity-50"
            >
              {isSubmitting ? "Starting..." : "Start ingestion"}
            </button>
          </div>
        </form>
      ) : (
        <p className="mt-6 rounded-lg border border-slate-200 bg-white p-4 text-sm text-slate-500">
          Your role ({user?.role}) has read-only access. Ingestion requires ADMIN or RESEARCHER.
        </p>
      )}

      <h2 className="mt-8 text-sm font-semibold text-slate-900">Recent jobs</h2>
      <div className="mt-3 overflow-x-auto rounded-lg border border-slate-200 bg-white">
        <table className="min-w-full divide-y divide-slate-200 text-sm">
          <thead className="bg-slate-50 text-left text-xs font-medium uppercase tracking-wide text-slate-500">
            <tr>
              <th className="px-4 py-2">Status</th>
              <th className="px-4 py-2">Read</th>
              <th className="px-4 py-2">Valid</th>
              <th className="px-4 py-2">Rejected</th>
              <th className="px-4 py-2">Duration</th>
              <th className="px-4 py-2">Started</th>
              <th className="px-4 py-2">Error</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-100">
            {jobs.length === 0 ? (
              <tr>
                <td colSpan={7} className="px-4 py-6 text-center text-slate-400">
                  No ingestion jobs have run yet. Start one with the form above, or run python -m app.jobs sync-biodiversity.
                </td>
              </tr>
            ) : (
              jobs.map((job) => (
                <tr key={job.id}>
                  <td className="px-4 py-2">
                    <span className={`rounded px-1.5 py-0.5 text-xs font-medium ${STATUS_STYLES[job.status]}`}>
                      {job.status}
                    </span>
                  </td>
                  <td className="px-4 py-2 text-slate-600">{job.records_read}</td>
                  <td className="px-4 py-2 text-slate-600">{job.records_valid}</td>
                  <td className="px-4 py-2 text-slate-600">{job.records_rejected}</td>
                  <td className="px-4 py-2 text-slate-600">
                    {job.execution_time_seconds != null ? `${job.execution_time_seconds.toFixed(1)}s` : "-"}
                  </td>
                  <td className="px-4 py-2 text-slate-600">
                    {job.started_at ? new Date(job.started_at).toLocaleString() : "-"}
                  </td>
                  <td className="max-w-xs truncate px-4 py-2 text-xs text-red-600" title={job.error_message ?? ""}>
                    {job.error_message ?? ""}
                  </td>
                </tr>
              ))
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
}
