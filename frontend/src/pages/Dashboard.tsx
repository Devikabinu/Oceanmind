import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import ModelOutputsSummary from "../components/ModelOutputsSummary";
import StatCard from "../components/StatCard";
import { listDatasets } from "../api/dataSources";
import { listBiodiversityObservations, listIngestionJobs, listOceanObservations } from "../api/ingestion";
import { getQualityReports } from "../api/quality";
import type { DataQualityReport, IngestionJob } from "../types";

export default function Dashboard() {
  const [datasetCount, setDatasetCount] = useState<number | null>(null);
  const [oceanCount, setOceanCount] = useState<number | null>(null);
  const [bioCount, setBioCount] = useState<number | null>(null);
  const [latestJob, setLatestJob] = useState<IngestionJob | null>(null);
  const [latestQuality, setLatestQuality] = useState<DataQualityReport | null>(null);
  const [isLoading, setIsLoading] = useState(true);

  useEffect(() => {
    let cancelled = false;

    async function load() {
      const [datasets, oceanObs, bioObs, jobs] = await Promise.all([
        listDatasets({ page_size: 1 }),
        listOceanObservations({ page_size: 1 }),
        listBiodiversityObservations({ page_size: 1 }),
        listIngestionJobs({ page_size: 1 }),
      ]);
      if (cancelled) return;

      setDatasetCount(datasets.total);
      setOceanCount(oceanObs.total);
      setBioCount(bioObs.total);

      const mostRecentJob = jobs[0] ?? null;
      setLatestJob(mostRecentJob);

      if (mostRecentJob?.dataset_id) {
        const reports = await getQualityReports(mostRecentJob.dataset_id);
        if (!cancelled) setLatestQuality(reports[0] ?? null);
      }
      setIsLoading(false);
    }

    void load();
    return () => {
      cancelled = true;
    };
  }, []);

  return (
    <div>
      <h1 className="text-xl font-semibold text-slate-900">Dashboard</h1>
      <p className="mt-1 text-sm text-slate-500">
        Overview of data sources, ingested observations, pipeline health, and model outputs.
      </p>

      <div className="mt-6 grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3">
        <StatCard label="Datasets" value={isLoading ? "..." : (datasetCount ?? 0)} />
        <StatCard label="Ocean Observations" value={isLoading ? "..." : (oceanCount ?? 0)} />
        <StatCard label="Biodiversity Observations" value={isLoading ? "..." : (bioCount ?? 0)} />

        <div className="rounded-lg border border-slate-200 bg-white p-4 sm:col-span-2 lg:col-span-1">
          <div className="text-xs font-medium uppercase tracking-wide text-slate-500">
            Latest Ingestion
          </div>
          {latestJob ? (
            <>
              <div className="mt-1 text-lg font-semibold text-slate-900">{latestJob.status}</div>
              <div className="mt-1 text-xs text-slate-400">
                {latestJob.records_valid} / {latestJob.records_read} records valid
              </div>
            </>
          ) : (
            <div className="mt-1 text-sm text-slate-400">No ingestion jobs yet</div>
          )}
          <Link to="/ingestion" className="mt-2 inline-block text-xs font-medium text-slate-600 underline">
            View ingestion &rarr;
          </Link>
        </div>

        <div className="rounded-lg border border-slate-200 bg-white p-4 sm:col-span-2">
          <div className="text-xs font-medium uppercase tracking-wide text-slate-500">
            Data Quality (most recent run)
          </div>
          {latestQuality ? (
            <div className="mt-2 grid grid-cols-3 gap-3 text-sm sm:grid-cols-5">
              <div>
                <div className="text-slate-400">Read</div>
                <div className="font-medium text-slate-900">{latestQuality.records_read}</div>
              </div>
              <div>
                <div className="text-slate-400">Valid</div>
                <div className="font-medium text-slate-900">{latestQuality.records_valid}</div>
              </div>
              <div>
                <div className="text-slate-400">Rejected</div>
                <div className="font-medium text-slate-900">{latestQuality.records_rejected}</div>
              </div>
              <div>
                <div className="text-slate-400">Missing</div>
                <div className="font-medium text-slate-900">{latestQuality.missing_values}</div>
              </div>
              <div>
                <div className="text-slate-400">Invalid coords</div>
                <div className="font-medium text-slate-900">{latestQuality.invalid_coordinates}</div>
              </div>
            </div>
          ) : (
            <div className="mt-1 text-sm text-slate-400">No quality reports yet</div>
          )}
          <Link to="/data-quality" className="mt-2 inline-block text-xs font-medium text-slate-600 underline">
            View data quality &rarr;
          </Link>
        </div>
      </div>

      <ModelOutputsSummary />
    </div>
  );
}
