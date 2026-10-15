import { useNavigate } from "react-router-dom";
import { getCoverage, listHeatwaves } from "../api/intelligence";
import OceanMap from "../components/OceanMap";
import PageHeader from "../components/PageHeader";
import Status from "../components/Status";
import { useAsync } from "../hooks/useAsync";
import { cached } from "../hooks/useCached";

/** Global-capable map. Layers are drawn only where data exist; the coverage table below says exactly where that is. */
export default function OceanMapPage() {
  const navigate = useNavigate();
  const heatwaves = useAsync(() => listHeatwaves(), []);
  const coverage = useAsync(() => cached("coverage", getCoverage), []);
  return (
    <div>
      <PageHeader title="Ocean map">
        Explore the ocean worldwide, but note that SST, forecast, heatwave and risk layers exist only inside the dashed study-region outline. Species records
        come from OBIS and can be shown for any catalogued species, including a global density view.
      </PageHeader>
      <div className="mt-4">
        <OceanMap
          view="world"
          showExtras
          initialLayer="observed_anomaly"
          events={heatwaves.data?.items}
          onEventClick={(id) => navigate(`/heatwaves?event=${id}`)}
          heightClass="h-[34rem]"
        />
      </div>

      <section className="mt-8" aria-labelledby="cov-h">
        <h2 id="cov-h" className="text-lg font-semibold text-slate-900">Data coverage</h2>
        <p className="mt-1 text-sm text-slate-600">What each layer is based on, and where it actually has data.</p>
        <Status isLoading={coverage.isLoading} error={coverage.error} hasData={!!coverage.data}>
          <div className="mt-3 overflow-x-auto rounded-lg border border-slate-200 bg-white">
            <table className="w-full text-left text-sm">
              <caption className="sr-only">Coverage by data source</caption>
              <thead className="bg-slate-50 text-xs uppercase text-slate-600">
                <tr>
                  <th scope="col" className="px-3 py-2">Source</th>
                  <th scope="col" className="px-3 py-2">Geographic coverage (source)</th>
                  <th scope="col" className="px-3 py-2">Loaded in this project</th>
                </tr>
              </thead>
              <tbody>
                {coverage.data?.items.map((s) => (
                  <tr key={s.id} className="border-t border-slate-100 align-top">
                    <td className="px-3 py-2 font-medium text-slate-900">{s.name}</td>
                    <td className="px-3 py-2 text-slate-700">{s.coverage_source}</td>
                    <td className="px-3 py-2 text-slate-700">{s.loaded_in_project ?? "Not loaded"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </Status>
      </section>
    </div>
  );
}
