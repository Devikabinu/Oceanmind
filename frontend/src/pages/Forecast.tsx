import { useState } from "react";
import { getRegion } from "../api/monitor";
import type { RegionName } from "../api/monitor";
import ForecastChart from "../components/ForecastChart";
import OceanMap from "../components/OceanMap";
import PageHeader from "../components/PageHeader";
import RegionForecast, { REGION_LABELS } from "../components/RegionForecast";
import SourceTag from "../components/SourceTag";
import Status from "../components/Status";
import Term from "../components/Term";
import TrendCharts from "../components/TrendCharts";
import WhyPanel from "../components/WhyPanel";
import { useAsync } from "../hooks/useAsync";
import { useOverview } from "../hooks/useCached";

function Verification() {
  const [region, setRegion] = useState<RegionName>("all");
  const { data, error, isLoading } = useAsync(() => getRegion(region), [region]);
  const errs = data ? data.forecast.map((f, i) => (f != null && data.observed[i] != null ? Math.abs(f - data.observed[i]!) : null)) : [];
  const perr = data ? (data.persistence ?? []).map((p, i) => (p != null && data.observed[i] != null ? Math.abs(p - data.observed[i]!) : null)) : [];
  return (
    <div className="rounded-lg border border-slate-200 bg-white p-4">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h2 className="text-sm font-semibold text-slate-900">
          How did a past forecast do? (<Term k="hindcast">hindcast</Term> check)
        </h2>
        <div className="flex items-center gap-2">
          <select
            aria-label="Region for verification"
            value={region}
            onChange={(e) => setRegion(e.target.value as RegionName)}
            className="rounded-md border border-slate-300 bg-white px-2 py-1 text-sm"
          >
            {(Object.keys(REGION_LABELS) as RegionName[]).map((r) => (
              <option key={r} value={r}>
                {REGION_LABELS[r]}
              </option>
            ))}
          </select>
          <SourceTag kind="evaluation" />
        </div>
      </div>
      <p className="mt-1 text-xs text-slate-600">
        The same model, run from {data?.last_observed_date ?? "an earlier day"} for the following week, compared with what was actually observed.
      </p>
      <Status isLoading={isLoading} error={error} hasData={!!data}>
        {data && (
          <>
            <ForecastChart series={data} />
            <div className="mt-2 overflow-x-auto">
              <table className="w-full text-left text-sm">
                <caption className="sr-only">Absolute error by horizon</caption>
                <thead className="text-xs uppercase text-slate-600">
                  <tr>
                    <th scope="col" className="py-1 pr-3">Horizon</th>
                    <th scope="col" className="py-1 pr-3">Forecast error °C</th>
                    <th scope="col" className="py-1">Persistence error °C</th>
                  </tr>
                </thead>
                <tbody>
                  {data.horizons.map((h, i) => (
                    <tr key={h} className="border-t border-slate-100">
                      <td className="py-1 pr-3 font-medium">+{h} d</td>
                      <td className="py-1 pr-3">{errs[i]?.toFixed(2) ?? "–"}</td>
                      <td className="py-1">{perr[i]?.toFixed(2) ?? "–"}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <p className="mt-2 text-xs text-slate-600">
              A single week in one region is an illustration, not a performance estimate; see Model Performance for the full test period.
            </p>
          </>
        )}
      </Status>
    </div>
  );
}

export default function Forecast() {
  const overview = useOverview();
  const o = overview.data;
  const fcLines = o?.interpretation.filter((l) => l.startsWith("The model expects") || l.startsWith("Latest observed")) ?? [];
  return (
    <div>
      <PageHeader title="SST forecast, 1–7 days">
        What does the model expect? The ConvLSTM neural network predicts sea surface temperature for the next 7 days from the last 7 observed days. Pick a region, a
        forecast day or click the map for a single location.
      </PageHeader>

      {fcLines.length > 0 && (
        <div className="mt-4">
          <WhyPanel title="In plain language" reasons={fcLines} classification="Model output compared with the latest observation" />
        </div>
      )}

      <div className="mt-6">
        <RegionForecast withTable />
      </div>

      <section className="mt-8" aria-labelledby="fmap">
        <h2 id="fmap" className="mb-3 text-lg font-semibold text-slate-900">Forecast map and location forecast</h2>
        <OceanMap initialLayer="forecast" initialHorizon={7} layers={["forecast", "forecast_anomaly", "observed", "observed_anomaly"]} />
      </section>

      <div className="mt-8">
        <Verification />
      </div>
      <div className="mt-8">
        <TrendCharts />
      </div>
    </div>
  );
}
