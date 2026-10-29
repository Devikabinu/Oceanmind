import { useMemo, useState } from "react";
import type { ReactNode } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { getMethodology, getRiskAreas, getRiskExplanation, getRiskMap, getSpeciesRanking } from "../api/intelligence";
import type { RiskArea } from "../api/intelligence";
import { getDates, getDatasets, getRegions as getEnvRegions } from "../api/environment";
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
import FactorBars from "../components/FactorBars";
import { useAsync } from "../hooks/useAsync";
import { cached } from "../hooks/useCached";
import { useActive } from "../contexts/ActiveSelection";
import ExplanationPanel from "../components/ExplanationPanel";
import RelatedLinks from "../components/RelatedLinks";
import { axisOrigin, extentToBounds, riskToMapLayer } from "../utils/mapCoords";
import Risk from "./Risk";

const TABS = [
  { id: "areas", label: "Areas" },
  { id: "species", label: "Species" },
  { id: "method", label: "Methodology" },
] as const;
type TabId = (typeof TABS)[number]["id"];
const LEVELS: Level[] = ["LOW", "MEDIUM", "HIGH", "CRITICAL"];
const FACTOR_NAME: Record<string, string> = { anomaly: "SST anomaly", persistence: "Heatwave persistence", forecast: "Forecast anomaly", overlap: "Species overlap" };

const LEGACY_DATASET = "ne_pacific";
const STATE_COLORS: Record<number, [number, number, number, number]> = { 1: [236, 236, 236, 235], 2: [58, 58, 58, 235] };
const STATE_LABELS: Record<number, string> = {
  1: "not assessed: no SST anomaly",
  2: "unavailable: no environmental data this day",
  3: "land",
  4: "outside the selected region",
};
const STATUS_TITLE: Record<string, string> = {
  insufficient_data: "Not assessed",
  unavailable: "Unavailable",
  land: "Land",
  outside_region: "Outside the selected region",
};
const BIO_TEXT: Record<string, string> = {
  observed: "Observed: OBIS records exist in this 2°×2° block",
  none_recorded: "None recorded (records were gathered for this area)",
  insufficient_coverage: "Limited coverage: no stored records here, which is not the same as no animals",
  unavailable: "Unavailable: no biodiversity data loaded",
};
const lonLabel = (lon: number) => `${Math.abs(lon).toFixed(1)}°${lon < 0 ? "W" : "E"}`;
const latLabel = (lat: number) => `${Math.abs(lat).toFixed(1)}°${lat >= 0 ? "N" : "S"}`;

/** Details of one Pacific risk cell: the score, every factor with its availability, and the biodiversity evidence. Missing evidence is never shown as low risk. */
function RiskCellPanel({ point, dataset, date }: { point: { lat: number; lon: number } | null; dataset: string; date: string | null }) {
  const cell = useAsync(() => (point && date ? getRiskExplanation(point.lat, point.lon, dataset, date) : Promise.resolve(null)), [point?.lat, point?.lon, dataset, date]);
  const shell = (title: string, body: ReactNode) => (
    <section aria-label="Selected cell" className="overflow-hidden rounded-xl bg-white shadow-sm ring-1 ring-slate-200">
      <div className="on-deep bg-gradient-to-r from-deep to-tide px-4 py-2.5 text-white">
        <div className="text-[11px] font-semibold uppercase tracking-[0.14em] text-cyan-100/90">Selected cell</div>
        <div className="text-lg font-semibold tabular-nums">{title}</div>
      </div>
      <div className="space-y-3 p-4">{body}</div>
    </section>
  );
  if (!point) {
    return (
      <div className="rounded-xl bg-white p-4 text-sm text-slate-600 shadow-sm ring-1 ring-slate-200">
        <div className="text-[11px] font-semibold uppercase tracking-[0.14em] text-slate-600">Selected cell</div>
        <p className="mt-2">Click a cell on the risk map to see its score, each factor, and which evidence is missing.</p>
      </div>
    );
  }
  const title = `${latLabel(point.lat)} · ${lonLabel(point.lon)}`;
  if (cell.error) return shell(title, <p role="alert" className="text-sm text-amber-900">{cell.error}</p>);
  const c = cell.data?.cell;
  const explanation = cell.data?.explanation;
  const fresh = c && !cell.isLoading && c.date === date && c.dataset === dataset ? c : null;
  if (!fresh) return shell(title, <p role="status" className="text-sm text-slate-600">Loading cell…</p>);
  const generated = !fresh.source.is_observational;
  return shell(
    title,
    <>
      {fresh.status === "assessed" && fresh.level ? (
        <div>
          <div className="flex items-center gap-2">
            <SeverityBadge level={fresh.level} />
            <span className="text-2xl font-semibold tracking-tight text-slate-900">{fresh.score?.toFixed(2)}</span>
            <span className="text-xs text-slate-500">of 1</span>
          </div>
          {fresh.evidence_completeness != null && fresh.evidence_completeness < 1 && (
            <p className="mt-1 rounded bg-amber-50 px-2 py-1 text-xs text-amber-900">
              Partial evidence: this score uses {Math.round(fresh.evidence_completeness * 100)}% of the methodology weight. Missing factors are left out, not counted as zero.
            </p>
          )}
        </div>
      ) : (
        <div className="rounded-lg border border-dashed border-slate-300 bg-slate-50 p-3">
          <div className="text-sm font-semibold text-slate-900">{STATUS_TITLE[fresh.status] ?? fresh.status}</div>
          <p className="mt-1 text-sm text-slate-700">
            {fresh.status === "insufficient_data"
              ? "The SST anomaly (the core factor) cannot be computed for this cell and day, so no risk level is given. This is not low risk."
              : "No environmental data exist for this ocean cell on this date, so no risk level is given. This is not low risk."}
          </p>
        </div>
      )}
      <div>
        <div className="mb-1 text-sm font-semibold text-slate-900">Risk factors</div>
        <FactorBars factors={fresh.factors} />
        <ul className="mt-2 space-y-1 text-xs text-slate-600">
          {fresh.factors.filter((f) => !f.available && f.reason).map((f) => (
            <li key={f.factor}><strong>{FACTOR_NAME[f.factor] ?? f.factor}:</strong> {f.reason}</li>
          ))}
          {fresh.factors.filter((f) => f.available && f.note).map((f) => (
            <li key={`${f.factor}-note`}><strong>{FACTOR_NAME[f.factor] ?? f.factor}:</strong> {f.note}</li>
          ))}
        </ul>
      </div>
      {explanation && <ExplanationPanel explanation={explanation} title="Why this risk level (plain language)" />}
      <div className="text-xs text-slate-700">
        <div className="font-semibold text-slate-900">Biodiversity evidence</div>
        {BIO_TEXT[fresh.biodiversity_evidence]}
        {fresh.n_species != null && fresh.n_species > 0 && ` (${fresh.n_species} species)`}
      </div>
      <dl className="space-y-1 border-t border-slate-200 pt-2 text-xs text-slate-600">
        <div className="flex justify-between gap-3"><dt>Date</dt><dd className="font-medium text-slate-800">{fresh.date}</dd></div>
        <div className="flex justify-between gap-3"><dt>Grid cell</dt><dd className="font-medium text-slate-800">{latLabel(fresh.cell.lat)} · {lonLabel(fresh.cell.lon_180)}</dd></div>
        <div className="flex justify-between gap-3"><dt>Source</dt><dd className="text-right font-medium text-slate-800">{fresh.source.provider_id}</dd></div>
        <div className="flex justify-between gap-3">
          <dt>Data status</dt>
          <dd className={`rounded px-1.5 py-0.5 font-semibold ${generated ? "bg-amber-100 text-amber-900" : "bg-emerald-100 text-emerald-900"}`}>
            {generated ? "Modelled dataset" : "Observational"}
          </dd>
        </div>
      </dl>
      <RelatedLinks point={{ lat: fresh.cell.lat, lon: fresh.cell.lon_180 }} to={["map", "heatwaves", "alerts"]} />
    </>,
  );
}

function Areas() {
  const [min, setMin] = useState<Level>("HIGH");
  const act = useActive();
  const [qs] = useSearchParams();
  const datasetId = act.dataset;
  const setDatasetId = act.setDataset;
  const region = act.region;
  const setRegion = act.setRegion;
  const [legacyRegion, setLegacyRegion] = useState<RegionName>("all");
  const [selected, setSelected] = useState<{ lat: number; lon: number } | null>(() => {
    const la = Number(qs.get("lat"));
    const lo = Number(qs.get("lon"));
    return qs.get("lat") && qs.get("lon") && Number.isFinite(la) && Number.isFinite(lo) ? { lat: la, lon: lo } : null;
  });
  const dates = useAsync(() => cached(`env-dates-${act.dataset}`, () => getDates(act.dataset)), [act.dataset]);
  const dateRange = dates.data && dates.data.dataset === act.dataset ? dates.data : null;
  const dateArg = act.date ?? undefined;
  const datasets = useAsync(() => cached("env-datasets", getDatasets), []);
  const regions = useAsync(() => cached("env-regions", getEnvRegions), []);
  const pacific = datasetId !== LEGACY_DATASET;
  const legacyMap = useAsync(() => (pacific ? Promise.resolve(null) : getMapLayer("risk", 1)), [pacific]);
  const riskMap = useAsync(() => (pacific ? getRiskMap(datasetId, region, dateArg) : Promise.resolve(null)), [pacific, datasetId, region, dateArg]);
  const areas = useAsync(
    () => getRiskAreas(min, 40, pacific ? region : legacyRegion, pacific ? datasetId : undefined, pacific ? dateArg : undefined),
    [min, pacific, datasetId, region, legacyRegion, dateArg],
  );
  // never show a risk grid that belongs to another dataset or region while a new one loads
  const freshRisk = riskMap.data && !riskMap.isLoading && riskMap.data.dataset === datasetId && riskMap.data.region.id === region ? riskMap.data : null;
  const layer = useMemo(() => (freshRisk ? riskToMapLayer(freshRisk) : null), [freshRisk]);
  const regionInfo = regions.data?.regions.find((r) => r.id === region);
  const fitTo = useMemo(() => (pacific && regionInfo?.map_extent ? extentToBounds(regionInfo.map_extent) : null), [pacific, regionInfo]);
  const unavailable = freshRisk ? Object.entries(freshRisk.factors_unavailable) : [];
  const pick = (a: RiskArea) => setSelected({ lat: a.lat, lon: a.lon_180 ?? a.lon });
  const field = "flex min-w-0 max-w-full flex-col gap-1 text-[11px] font-semibold uppercase tracking-[0.12em] text-cyan-100/90";
  const sel = "w-full min-w-0 max-w-full rounded-md border border-white/30 bg-white px-2 py-1.5 text-sm font-normal normal-case tracking-normal text-slate-900";
  return (
    <div>
      <div className="on-deep flex flex-wrap items-end gap-x-4 gap-y-3 rounded-t-xl bg-gradient-to-r from-deep via-abyss to-tide px-4 py-3 text-white">
        <label className={field}>
          Dataset
          <select
            className={sel}
            value={datasetId}
            onChange={(e) => {
              setDatasetId(e.target.value);
              setSelected(null);
            }}
          >
            {datasets.data?.datasets.map((d) => (
              <option key={d.id} value={d.id} disabled={!d.available}>
                {d.name}
                {d.available ? "" : " (not available)"}
              </option>
            ))}
            {!datasets.data && <option value={datasetId}>{datasetId}</option>}
          </select>
        </label>
        <label className={field}>
          Region
          {pacific ? (
            <select className={sel} value={region} onChange={(e) => setRegion(e.target.value)}>
              {!regionInfo && <option value={region}>{region}</option>}
              {regions.data?.regions.map((r) => (
                <option key={r.id} value={r.id}>
                  {r.parent && r.parent !== "pacific" ? "  " : ""}
                  {r.name}
                </option>
              ))}
            </select>
          ) : (
            <select className={sel} value={legacyRegion} onChange={(e) => setLegacyRegion(e.target.value as RegionName)}>
              {(Object.keys(REGION_LABELS) as RegionName[]).map((r) => (
                <option key={r} value={r}>{REGION_LABELS[r]}</option>
              ))}
            </select>
          )}
        </label>
        {pacific && dateRange && (
          <label className={field}>
            Date
            <input type="date" className={sel} min={dateRange.first_date} max={dateRange.latest_date} value={act.date ?? dateRange.latest_date} onChange={(e) => act.setDate(e.target.value || null)} />
          </label>
        )}
        {pacific && freshRisk && (
          <p className="flex flex-wrap items-center gap-x-3 gap-y-1 pb-1 text-xs text-cyan-50" data-testid="risk-meta">
            <span><span className="text-cyan-200/80">Date</span> <strong className="text-white">{freshRisk.date}</strong></span>

            <span className="text-cyan-200/80">Source {freshRisk.source.provider_id}</span>
          </p>
        )}
      </div>
      {pacific && unavailable.length > 0 && (
        <div role="note" className="border-x border-amber-300 bg-amber-50 px-4 py-2 text-sm text-amber-900">
          <strong>Partial scores.</strong> For this dataset the score uses {freshRisk?.factors_used.map((k) => FACTOR_NAME[k] ?? k).join(" and ")}
          {" "}(species overlap only where OBIS records exist). {unavailable.map(([k]) => FACTOR_NAME[k] ?? k).join(" and ")} are not available yet and are left out of the score; they are not counted as zero.
        </div>
      )}
      {pacific && riskMap.error && <div role="alert" className="border-x border-amber-300 bg-amber-50 px-4 py-2 text-sm text-amber-900">Risk map unavailable: {riskMap.error}</div>}
      <div className="mt-4 grid grid-cols-1 gap-4 xl:grid-cols-[minmax(0,1fr)_22rem]">
        <div>
          <SstMap
            layer={pacific ? layer : legacyMap.data}
            status={pacific ? layer?.status : null}
            statusColors={STATE_COLORS}
            statusLabels={STATE_LABELS}
            legendExtra={
              pacific ? (
                <ul className="mt-1 space-y-0.5 border-t border-white/20 pt-1">
                  <li className="flex items-center gap-1.5"><span aria-hidden className="inline-block h-2.5 w-2.5 rounded-sm ring-1 ring-white/70" style={{ background: "rgb(236,236,236)" }} />Insufficient data (not low risk)</li>
                  <li className="flex items-center gap-1.5"><span aria-hidden className="inline-block h-2.5 w-2.5 rounded-sm ring-1 ring-white/70" style={{ background: "rgb(58,58,58)" }} />Unavailable (not low risk)</li>
                  <li className="text-cyan-100/80">Low &lt; 0.25 · Moderate &lt; 0.5 · High &lt; 0.75 · Critical</li>
                </ul>
              ) : undefined
            }
            lonOrigin={pacific && layer ? axisOrigin(layer.lon) : null}
            fitTo={fitTo}
            showOutline={!pacific}
            unavailable={pacific ? !!riskMap.error : !!legacyMap.error}
            badge={pacific && freshRisk ? `${freshRisk.region.name} · ${freshRisk.date}`: undefined}
            selected={selected}
            onPick={(lat, lon) => setSelected({ lat, lon })}
            initialView={pacific ? "world" : "study"}
            heightClass={pacific ? "h-[calc(100vh-18rem)] min-h-[30rem]" : undefined}
            ariaLabel="Ecological risk map"
          />
          <p className="mt-1 text-xs text-slate-500">Colour = <Term k="risk">project environmental risk indicator</Term> (0–1) per grid cell. Click a cell for the factors and the reasons.</p>
        </div>
        {pacific ? <RiskCellPanel point={selected} dataset={datasetId} date={freshRisk?.date ?? null} /> : <LocationPanel point={selected} />}
      </div>
      <section className="mt-6 rounded-lg bg-white/70 p-4 ring-1 ring-slate-200" aria-labelledby="ra">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <h2 id="ra" className="text-sm font-semibold text-slate-900">Highest-risk 2°×2° areas</h2>
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
                <p>Lower the minimum level or choose a larger region. Areas without enough data are not rated at all; they are not counted as low.</p>
                {!pacific && <p>Risk is only computed inside the NE Pacific study region for this dataset.</p>}
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
                      <td className="py-1.5 pr-3"><button type="button" className="underline" onClick={() => pick(a)}>{latLabel(a.lat)}, {lonLabel(a.lon_180 ?? a.lon)}</button></td>
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
        <Risk embedded />
      </details>
    </div>
  );
}
