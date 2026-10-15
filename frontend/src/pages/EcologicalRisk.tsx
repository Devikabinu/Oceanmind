import { useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { getMethodology, getRiskAreas, getSpeciesRanking } from "../api/intelligence";
import type { RiskArea } from "../api/intelligence";
import { getMapLayer } from "../api/monitor";
import type { Level, RegionName } from "../api/monitor";
import { REGION_LABELS } from "../components/RegionForecast";
import EmptyState from "../components/EmptyState";
import LocationPanel from "../components/LocationPanel";
import PageHeader from "../components/PageHeader";
import SeverityBadge from "../components/SeverityBadge";
import SourceTag from "../components/SourceTag";
import SstMap from "../components/SstMap";
import Status from "../components/Status";
import Term from "../components/Term";
import { useAsync } from "../hooks/useAsync";
import Risk from "./Risk";

const TABS = [
  { id: "areas", label: "Areas" },
  { id: "species", label: "Species" },
  { id: "method", label: "Methodology" },
] as const;
type TabId = (typeof TABS)[number]["id"];
const LEVELS: Level[] = ["LOW", "MEDIUM", "HIGH", "CRITICAL"];
const FACTOR_NAME: Record<string, string> = { anomaly: "SST anomaly", persistence: "Heatwave persistence", forecast: "Forecast anomaly", overlap: "Species overlap" };

function Areas() {
  const [min, setMin] = useState<Level>("HIGH");
  const [region, setRegion] = useState<RegionName>("all");
  const [selected, setSelected] = useState<{ lat: number; lon: number } | null>(null);
  const map = useAsync(() => getMapLayer("risk", 1), []);
  const areas = useAsync(() => getRiskAreas(min, 40, region), [min, region]);
  const pick = (a: RiskArea) => setSelected({ lat: a.lat, lon: a.lon });
  return (
    <div>
      <div className="grid grid-cols-1 gap-4 xl:grid-cols-3">
        <div className="xl:col-span-2">
          <SstMap layer={map.data} selected={selected} onPick={(lat, lon) => setSelected({ lat, lon })} ariaLabel="Ecological risk map" />
          <p className="mt-1 text-xs text-slate-500">Colour = <Term k="risk">project environmental risk indicator</Term> (0–1) per grid cell. Click a cell for the factors and the reasons.</p>
        </div>
        <LocationPanel point={selected} />
      </div>
      <section className="mt-6 rounded-lg border border-slate-200 bg-white p-4" aria-labelledby="ra">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <h2 id="ra" className="text-sm font-semibold text-slate-900">Highest-risk 2°×2° areas</h2>
          <label className="flex items-center gap-2 text-sm text-slate-700">
            Region
            <select value={region} onChange={(e) => setRegion(e.target.value as RegionName)} className="rounded-md border border-slate-300 bg-white px-2 py-1 text-sm">
              {(Object.keys(REGION_LABELS) as RegionName[]).map((r) => (
                <option key={r} value={r}>{REGION_LABELS[r]}</option>
              ))}
            </select>
          </label>
          <label className="flex items-center gap-2 text-sm text-slate-700">
            Minimum level
            <select value={min} onChange={(e) => setMin(e.target.value as Level)} className="rounded-md border border-slate-300 bg-white px-2 py-1 text-sm">
              {LEVELS.map((l) => (
                <option key={l} value={l}>{l}</option>
              ))}
            </select>
          </label>
        </div>
        <Status isLoading={areas.isLoading} error={areas.error} hasData={!!areas.data}>
          {areas.data && areas.data.items.length === 0 ? (
            <div className="mt-3">
              <EmptyState title={`No area in this region is rated ${min} or above on ${areas.data.date}`}>
                <p>{region === "all" ? "No 2°×2° block reaches this level today." : `No block in “${REGION_LABELS[region]}” reaches this level today.`} Lower the minimum level or choose a larger region.</p>
                <p>Risk is only computed inside the NE Pacific study region.</p>
              </EmptyState>
            </div>
          ) : (
            <div className="mt-3 overflow-x-auto">
              <table className="w-full text-left text-sm">
                <caption className="sr-only">Highest-risk areas</caption>
                <thead className="text-xs uppercase text-slate-600">
                  <tr>
                    <th scope="col" className="py-1 pr-3">Area</th>
                    <th scope="col" className="py-1 pr-3">Level</th>
                    <th scope="col" className="py-1 pr-3">Score</th>
                    <th scope="col" className="py-1 pr-3">Main driver</th>
                    <th scope="col" className="py-1">Factors (0–1)</th>
                  </tr>
                </thead>
                <tbody>
                  {areas.data?.items.map((a) => (
                    <tr key={`${a.lat}-${a.lon}`} className="border-t border-slate-100">
                      <td className="py-1.5 pr-3"><button type="button" className="underline" onClick={() => pick(a)}>{a.lat.toFixed(1)}°N, {Math.abs(a.lon).toFixed(1)}°W</button></td>
                      <td className="py-1.5 pr-3"><SeverityBadge level={a.level} /></td>
                      <td className="py-1.5 pr-3">{a.score.toFixed(2)}</td>
                      <td className="py-1.5 pr-3">{FACTOR_NAME[a.top_driver] ?? a.top_driver}</td>
                      <td className="py-1.5 text-xs text-slate-600">{Object.entries(a.factors).map(([k, v]) => `${FACTOR_NAME[k] ?? k} ${v.toFixed(2)}`).join(" · ")}</td>
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

function SpeciesTab() {
  const rank = useAsync(() => getSpeciesRanking(), []);
  const [group, setGroup] = useState("");
  const [level, setLevel] = useState("");
  const rows = (rank.data?.items ?? []).filter((x) => (!group || x.taxon_group === group) && (!level || (level === "NONE" ? !x.available : x.level === level)));
  const groups = Array.from(new Set((rank.data?.items ?? []).map((x) => x.taxon_group).filter((g): g is string => !!g)));
  return (
    <section className="rounded-lg border border-slate-200 bg-white p-4" aria-labelledby="sr">
      <div className="flex items-center gap-2">
        <h2 id="sr" className="text-sm font-semibold text-slate-900">Species potential environmental exposure</h2>
        <SourceTag kind="derived" />
      </div>
      <p className="mt-1 text-sm text-slate-600">
        For each catalogued species, today&apos;s conditions at the places it was recorded in the last two years. This is a monitoring-priority indicator, not a conservation
        assessment and not evidence of harm.
      </p>
      <div className="mt-3 flex flex-wrap items-center gap-3 text-sm text-slate-700">
        <label className="flex items-center gap-2">Group
          <select value={group} onChange={(e) => setGroup(e.target.value)} className="rounded-md border border-slate-300 bg-white px-2 py-1 text-sm">
            <option value="">All groups</option>
            {groups.map((g) => <option key={g} value={g}>{g}</option>)}
          </select>
        </label>
        <label className="flex items-center gap-2">Exposure level
          <select value={level} onChange={(e) => setLevel(e.target.value)} className="rounded-md border border-slate-300 bg-white px-2 py-1 text-sm">
            <option value="">Any</option>
            {LEVELS.map((l) => <option key={l} value={l}>{l}</option>)}
            <option value="NONE">No assessment (no recent records)</option>
          </select>
        </label>
      </div>
      <Status isLoading={rank.isLoading} error={rank.error} hasData={!!rank.data}>
        {rank.data && rank.data.items.length === 0 ? (
          <div className="mt-3"><EmptyState title="No species in the catalogue"><p>The species catalogue is empty. Load it with: python -m app.jobs sync-biodiversity</p></EmptyState></div>
        ) : rows.length === 0 ? (
          <div className="mt-3"><EmptyState title="No species match these filters"><p>{rank.data?.items.length} species are catalogued. Try “All groups” and “Any” exposure level; the combination you chose has no species.</p></EmptyState></div>
        ) : (
          <div className="mt-3 overflow-x-auto">
            <table className="w-full text-left text-sm">
              <caption className="sr-only">Species exposure ranking</caption>
              <thead className="text-xs uppercase text-slate-600">
                <tr>
                  <th scope="col" className="py-1 pr-3">Species</th>
                  <th scope="col" className="py-1 pr-3">Group</th>
                  <th scope="col" className="py-1 pr-3">Level</th>
                  <th scope="col" className="py-1 pr-3">Score</th>
                  <th scope="col" className="py-1 pr-3">Records (2 yrs)</th>
                  <th scope="col" className="py-1">Positions ≥ 1 °C from normal</th>
                </tr>
              </thead>
              <tbody>
                {rows.map((s) => (
                  <tr key={s.aphia_id} className="border-t border-slate-100">
                    <td className="py-1.5 pr-3"><Link to={`/species/${s.aphia_id}`} className="underline">{s.common_name ?? s.scientific_name}</Link></td>
                    <td className="py-1.5 pr-3 text-xs text-slate-600">{s.taxon_group}</td>
                    {s.available && s.level ? (
                      <>
                        <td className="py-1.5 pr-3"><SeverityBadge level={s.level} /></td>
                        <td className="py-1.5 pr-3">{s.score?.toFixed(2)}</td>
                        <td className="py-1.5 pr-3">{s.n_records.toLocaleString()}</td>
                        <td className="py-1.5">{s.exposed_share != null ? `${(s.exposed_share * 100).toFixed(0)}%` : "–"}</td>
                      </>
                    ) : (
                      <td colSpan={4} className="py-1.5 text-xs text-slate-500">No available observations in the study region, so no assessment.</td>
                    )}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Status>
    </section>
  );
}

function Method() {
  const m = useAsync(() => getMethodology(), []);
  return (
    <Status isLoading={m.isLoading} error={m.error} hasData={!!m.data}>
      {m.data && (
        <div className="space-y-4">
          <div className="rounded-md border border-amber-200 bg-amber-50 px-3 py-2 text-sm text-amber-900">{m.data.name}: {m.data.status}</div>
          <section className="rounded-lg border border-slate-200 bg-white p-4">
            <h2 className="text-sm font-semibold text-slate-900">Factors and weights</h2>
            <table className="mt-2 w-full text-left text-sm">
              <caption className="sr-only">Risk factors</caption>
              <thead className="text-xs uppercase text-slate-600">
                <tr><th scope="col" className="py-1 pr-3">Factor</th><th scope="col" className="py-1 pr-3">Weight</th><th scope="col" className="py-1">Definition</th></tr>
              </thead>
              <tbody>
                {Object.entries(m.data.factors).map(([k, v]) => (
                  <tr key={k} className="border-t border-slate-100 align-top">
                    <td className="py-1.5 pr-3 font-medium">{FACTOR_NAME[k] ?? k}</td>
                    <td className="py-1.5 pr-3">{(m.data!.weights[k] * 100).toFixed(0)}%</td>
                    <td className="py-1.5 text-slate-700">{v}</td>
                  </tr>
                ))}
              </tbody>
            </table>
            <p className="mt-2 text-sm text-slate-700">{m.data.levels}</p>
            <p className="mt-1 text-xs text-slate-600">{m.data.weights_note}</p>
          </section>
          <section className="rounded-lg border border-slate-200 bg-white p-4">
            <h2 className="text-sm font-semibold text-slate-900">Confidence and limitations</h2>
            <p className="mt-1 text-sm text-slate-700">{m.data.confidence}</p>
            <ul className="mt-2 list-disc space-y-1 pl-5 text-sm text-slate-700">{m.data.limitations.map((l) => <li key={l}>{l}</li>)}</ul>
          </section>
        </div>
      )}
    </Status>
  );
}

export default function EcologicalRisk() {
  const [params, setParams] = useSearchParams();
  const tab = (TABS.find((t) => t.id === params.get("tab"))?.id ?? "areas") as TabId;
  return (
    <div>
      <PageHeader title="Ecological risk">
        Which areas and species deserve monitoring attention, and exactly why. The score combines the size of the SST anomaly, how long the heat has lasted, what the
        forecast expects and how many species have records there.
      </PageHeader>
      <div className="mt-3 rounded-md border border-amber-200 bg-amber-50 px-3 py-2 text-sm text-amber-900" role="note">
        <strong>Modelled potential exposure, not confirmed damage.</strong> The score is a transparent project calculation (four weighted factors, see the Methodology tab). It
        ranks where monitoring attention is most useful; it does not measure ecological harm.
      </div>
      <div role="tablist" aria-label="Ecological risk views" className="mt-4 flex gap-1 border-b border-slate-200">
        {TABS.map((t) => (
          <button
            key={t.id}
            role="tab"
            aria-selected={tab === t.id}
            type="button"
            onClick={() => setParams({ tab: t.id })}
            className={`-mb-px border-b-2 px-4 py-2 text-sm font-medium ${tab === t.id ? "border-slate-900 text-slate-900" : "border-transparent text-slate-600 hover:text-slate-900"}`}
          >
            {t.label}
          </button>
        ))}
      </div>
      <div className="mt-4" role="tabpanel">
        {tab === "areas" && <Areas />}
        {tab === "species" && <SpeciesTab />}
        {tab === "method" && <Method />}
      </div>
      <details className="mt-8 rounded-lg border border-slate-200 bg-white p-4">
        <summary className="cursor-pointer text-sm font-semibold text-slate-900">Stored per-record risk scores (database)</summary>
        <p className="mt-2 text-sm text-slate-600">One row per recent OBIS record, scored against the latest conditions at that position.</p>
        <Risk />
      </details>
    </div>
  );
}
