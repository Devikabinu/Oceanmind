import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import StatCard from "./StatCard";
import { listAlerts, listAnomalies, listForecasts, listRiskScores } from "../api/modelOutputs";
import { errorMessage } from "../utils/format";
import type { RiskLevel } from "../types";

const RISK_LEVELS: RiskLevel[] = ["CRITICAL", "HIGH", "MEDIUM", "LOW"];
const SAMPLE_SIZE = 100;

interface Summary {
  forecastTotal: number;
  meanForecastSst: number | null;
  anomalyTotal: number;
  riskCounts: Record<RiskLevel, number>;
  riskSampleSize: number;
  openAlerts: number;
  newAlerts: number;
}

async function loadSummary(): Promise<Summary> {
  const [forecasts, anomalies, risks, newAlerts, ackAlerts] = await Promise.all([
    listForecasts({ page_size: SAMPLE_SIZE }),
    listAnomalies({ is_anomaly: true, page_size: 1 }),
    listRiskScores({ page_size: SAMPLE_SIZE }),
    listAlerts({ status: "NEW", page_size: 1 }),
    listAlerts({ status: "ACKNOWLEDGED", page_size: 1 }),
  ]);
  const riskCounts: Record<RiskLevel, number> = { LOW: 0, MEDIUM: 0, HIGH: 0, CRITICAL: 0 };
  for (const r of risks.items) riskCounts[r.risk_level] += 1;
  const meanForecastSst = forecasts.items.length
    ? forecasts.items.reduce((sum, f) => sum + f.predicted_sst, 0) / forecasts.items.length
    : null;
  return {
    forecastTotal: forecasts.total,
    meanForecastSst,
    anomalyTotal: anomalies.total,
    riskCounts,
    riskSampleSize: risks.items.length,
    openAlerts: newAlerts.total + ackAlerts.total,
    newAlerts: newAlerts.total,
  };
}

const RISK_TEXT: Record<RiskLevel, string> = {
  CRITICAL: "text-red-700",
  HIGH: "text-orange-700",
  MEDIUM: "text-yellow-700",
  LOW: "text-green-700",
};

export default function ModelOutputsSummary() {
  const [summary, setSummary] = useState<Summary | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    loadSummary()
      .then((s) => !cancelled && setSummary(s))
      .catch((err: unknown) => !cancelled && setError(errorMessage(err)));
    return () => {
      cancelled = true;
    };
  }, []);

  const dots = (v: string | number | undefined) => (summary ? (v ?? "-") : "...");

  return (
    <section className="mt-10">
      <h2 className="text-lg font-semibold text-slate-900">Forecasts, Anomalies, Risk &amp; Alerts</h2>
      <p className="mt-1 text-sm text-slate-500">Summary of the model outputs (currently placeholder data).</p>
      {error && <div className="mt-3 rounded-md bg-red-50 px-3 py-2 text-sm text-red-700">{error}</div>}
      <div className="mt-4 grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-4">
        <div>
          <StatCard
            label="Forecasts"
            value={dots(summary?.forecastTotal)}
            hint={summary?.meanForecastSst != null ? `Mean predicted SST ${summary.meanForecastSst.toFixed(1)}°C (latest ${SAMPLE_SIZE})` : undefined}
          />
          <Link to="/forecast" className="mt-1 inline-block text-xs font-medium text-slate-600 underline">
            View forecasts &rarr;
          </Link>
        </div>
        <div>
          <StatCard label="Active anomalies" value={dots(summary?.anomalyTotal)} hint="Observations flagged as anomalous" />
          <Link to="/anomaly" className="mt-1 inline-block text-xs font-medium text-slate-600 underline">
            View anomalies &rarr;
          </Link>
        </div>
        <div>
          <div className="rounded-lg border border-slate-200 bg-white p-4">
            <div className="text-xs font-medium uppercase tracking-wide text-slate-500">Risk levels</div>
            <div className="mt-2 grid grid-cols-4 gap-1 text-center">
              {RISK_LEVELS.map((level) => (
                <div key={level}>
                  <div className={`text-lg font-semibold ${RISK_TEXT[level]}`}>
                    {summary ? summary.riskCounts[level] : "..."}
                  </div>
                  <div className="text-[10px] text-slate-400">{level}</div>
                </div>
              ))}
            </div>
            <div className="mt-1 text-xs text-slate-400">Latest {summary?.riskSampleSize ?? SAMPLE_SIZE} scores</div>
          </div>
          <Link to="/risk" className="mt-1 inline-block text-xs font-medium text-slate-600 underline">
            View risk &rarr;
          </Link>
        </div>
        <div>
          <StatCard
            label="Open alerts"
            value={dots(summary?.openAlerts)}
            hint={summary ? `${summary.newAlerts} new, ${summary.openAlerts - summary.newAlerts} acknowledged` : undefined}
          />
          <Link to="/alerts" className="mt-1 inline-block text-xs font-medium text-slate-600 underline">
            View alerts &rarr;
          </Link>
        </div>
      </div>
    </section>
  );
}
