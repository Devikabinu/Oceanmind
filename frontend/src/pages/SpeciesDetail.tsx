import { useMemo, useState } from "react";
import type { ReactNode } from "react";
import { Link, useParams } from "react-router-dom";
import { getSpecies, getSpeciesDistribution, getSpeciesObservations, getSpeciesRisk } from "../api/intelligence";
import { getMap as getEnvMap } from "../api/environment";
import { getMapLayer } from "../api/monitor";
import { axisOrigin, toMapLayer } from "../utils/mapCoords";
import Badge from "../components/Badge";
import ConservationBadge from "../components/ConservationBadge";
import EmptyState from "../components/EmptyState";
import FactorBars from "../components/FactorBars";
import SeverityBadge from "../components/SeverityBadge";
import SourceTag from "../components/SourceTag";
import SstMap from "../components/SstMap";
import Status from "../components/Status";
import Term from "../components/Term";
import WhyPanel from "../components/WhyPanel";
import { useAsync } from "../hooks/useAsync";
import ContextBar from "../components/ContextBar";
import RelatedLinks from "../components/RelatedLinks";
import { useActive } from "../contexts/ActiveSelection";

type Tag = "observed" | "forecast" | "derived" | "interpretation";

function Section({ title, tag, subtitle, children }: { title: string; tag: Tag; subtitle?: string; children: ReactNode }) {
  return (
    <section className="rounded-lg border border-slate-200 bg-white p-4" aria-label={title}>
      <div className="mb-3 flex flex-wrap items-center gap-2">
        <h2 className="text-base font-semibold uppercase tracking-wide text-slate-800">{title}</h2>
        <SourceTag kind={tag} />
      </div>
      {subtitle && <p className="-mt-2 mb-3 text-sm text-slate-600">{subtitle}</p>}
      {children}
    </section>
  );
}

function Stat({ label, value, note }: { label: ReactNode; value: ReactNode; note?: string }) {
  return (
    <div className="rounded-md bg-slate-50 p-3">
      <div className="text-xs text-slate-600">{label}</div>
      <div className="mt-0.5 text-base font-semibold text-slate-900">{value}</div>
      {note && <div className="text-xs text-slate-500">{note}</div>}
    </div>
  );
}

const plural = (n: number, word: string) => `${n} ${word}${n === 1 ? "" : "s"}`;
const signed = (v: number | null | undefined, d = 1) => (v == null ? "n/a" : `${v > 0 ? "+" : ""}${v.toFixed(d)} °C`);

export default function SpeciesDetail() {
  const { aphiaId } = useParams();
  const id = Number(aphiaId);
  const [showDist, setShowDist] = useState(false);
  const sp = useAsync(() => getSpecies(id), [id]);
  const obs = useAsync(() => getSpeciesObservations(id), [id]);
  const act = useActive();
  const envDataset = act.dataset === "ne_pacific" ? undefined : act.dataset;
  const risk = useAsync(() => getSpeciesRisk(id, envDataset), [id, envDataset]);
  // background layer: the NE export for the NE dataset, otherwise the active dataset's anomaly from the environment API (never the other one)
  const legacyCtx = useAsync(() => (envDataset ? Promise.resolve(null) : getMapLayer("observed_anomaly", 1)), [envDataset]);
  const envCtx = useAsync(() => (envDataset ? getEnvMap({ dataset: envDataset, layer: "anomaly", date: act.date ?? "latest", region: "pacific" }) : Promise.resolve(null)), [envDataset, act.date]);
  const ctxLayer = envDataset ? (envCtx.data && !envCtx.isLoading && envCtx.data.dataset.id === envDataset ? toMapLayer(envCtx.data) : null) : legacyCtx.data;
  const ctxError = envDataset ? envCtx.error : legacyCtx.error;
  const dist = useAsync(() => (showDist ? getSpeciesDistribution(id) : Promise.resolve(null)), [id, showDist]);
  const s = sp.data;
  const r = risk.data && (risk.data.dataset ?? "ne_pacific") === act.dataset ? risk.data : null;
  const fitTo = useMemo<[[number, number], [number, number]] | null>(() => {
    const pts = obs.data?.items ?? [];
    if (pts.length === 0) return null;
    const lats = pts.map((p) => p.latitude);
    const lons = pts.map((p) => p.longitude);
    return [
      [Math.min(...lats) - 1, Math.min(...lons) - 1],
      [Math.max(...lats) + 1, Math.max(...lons) + 1],
    ];
  }, [obs.data]);

  if (Number.isNaN(id)) return <EmptyState title="Unknown species">The address does not contain a valid species identifier.</EmptyState>;

  return (
    <div>
      <Link to="/species" className="text-sm text-slate-700 underline">← All species</Link>
      <Status isLoading={sp.isLoading} error={sp.error} hasData={!!s} emptyMessage="This species is not in the catalogue.">
        {s && (
          <div className="mt-2 space-y-6">
            <Section title="Species" tag="observed">
              <div className="flex flex-wrap items-start justify-between gap-4">
                <div>
                  <h1 className="text-2xl font-semibold text-slate-900">{s.common_name ?? s.scientific_name}</h1>
                  <p className="text-base italic text-slate-700">{s.scientific_name}</p>
                  <p className="mt-1 text-sm text-slate-600">
                    <Badge tone="blue">{s.taxon_group}</Badge>{" "}
                    <span className="text-xs text-slate-500">{[s.class_name, s.order_name, s.family].filter(Boolean).join(" › ")} · AphiaID {s.aphia_id}</span>
                  </p>
                  {s.sources.common_name && <p className="mt-1 text-xs text-slate-500">Common name: {s.sources.common_name}</p>}
                </div>
                <div className="max-w-sm rounded-md bg-slate-50 p-3 text-sm">
                  <div className="text-xs font-medium uppercase text-slate-600">Conservation status</div>
                  <div className="mt-1"><ConservationBadge category={s.iucn_category} label={s.iucn_label} source={s.iucn_source} /></div>
                  <div className="mt-1 text-xs text-slate-600">
                    Source: {s.iucn_source ?? "no source used by this project reports an IUCN category for this species"}
                    {s.sources.conservation && s.iucn_category && (
                      <> · <a href={s.sources.conservation} target="_blank" rel="noreferrer" className="underline">IUCN Red List entry</a></>
                    )}
                  </div>
                  {s.sources.conservation_alt && (
                    <div className="mt-1 rounded bg-amber-50 px-2 py-1 text-xs text-amber-900">
                      Another source ({s.sources.conservation_alt.source}) lists {s.sources.conservation_alt.category}. Sources can disagree when an assessment has been updated; the
                      status shown above comes from the source named.
                    </div>
                  )}
                  {!s.iucn_category && <div className="mt-1 text-xs text-slate-600">This is not the same as Least Concern: the status is simply not confirmed here.</div>}
                </div>
              </div>
            </Section>

            <Section title="Observations" tag="observed" subtitle="Real occurrence records from OBIS (a time-spread selection of records). Points show where the species was recorded.">
              <Status isLoading={obs.isLoading} error={obs.error} hasData={!!obs.data}>
                {obs.data && obs.data.total === 0 ? (
                  <EmptyState title="No available observations for this species in the loaded region">
                    <p>No OBIS records for this species are stored for the study region. The species may well occur elsewhere: use the observed-distribution toggle below to see global OBIS record density.</p>
                  </EmptyState>
                ) : (
                  <>
                    <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
                      <Stat label="Total observations (stored)" value={s.n_observations.toLocaleString()} />
                      <Stat label="Recent observations" value={r?.recent_records_90d != null ? r.recent_records_90d.toLocaleString() : "n/a"} note="within 90 days of the latest record" />
                      <Stat label="Latest observation" value={s.last_observation?.slice(0, 10) ?? "n/a"} />
                      <Stat label="First stored observation" value={s.first_observation?.slice(0, 10) ?? "n/a"} />
                    </div>
                    <div className="mt-4">
                      <SstMap
                        layer={ctxLayer}
                        lonOrigin={envDataset && ctxLayer ? axisOrigin(ctxLayer.lon) : null}
                        showOutline={!envDataset}
                        unavailable={!!ctxError}
                        observations={(obs.data?.items ?? []).map((o) => ({ lat: o.latitude, lon: o.longitude, label: `${o.timestamp.slice(0, 10)}${o.max_depth != null ? ` · depth ≤ ${o.max_depth} m` : ""}` }))}
                        distribution={showDist ? dist.data?.geojson : null}
                        fitTo={fitTo}
                        heightClass="h-96"
                        ariaLabel={`Observed distribution of ${s.scientific_name}`}
                      />
                      <p className="mt-1 text-xs text-slate-600">
                        Yellow dots: <strong>observation points</strong> ({obs.data?.total.toLocaleString()} stored records). Background: SST anomaly of the selected dataset ({act.dataset}). Sampling effort is uneven.
                      </p>
                    </div>
                  </>
                )}
              </Status>
              <label className="mt-3 flex items-start gap-1.5 text-sm text-slate-800">
                <input type="checkbox" className="mt-1" checked={showDist} onChange={(e) => setShowDist(e.target.checked)} />
                <span>
                  Show global <strong>observed distribution</strong> (OBIS record density, live). This is where records exist, <strong>not</strong> a species range: no verified range dataset is loaded.
                </span>
              </label>
              {dist.error && <p className="mt-1 text-sm text-amber-900">OBIS distribution unavailable: {dist.error}</p>}
              {showDist && dist.data && <p className="mt-1 text-xs text-slate-600">{dist.data.note}</p>}

              {obs.data && obs.data.items.length > 0 && (
                <div className="mt-4 overflow-x-auto">
                  <table className="w-full text-left text-sm">
                    <caption className="sr-only">Most recent stored observations</caption>
                    <thead className="text-xs uppercase text-slate-600">
                      <tr>
                        <th scope="col" className="py-1 pr-3">Date</th>
                        <th scope="col" className="py-1 pr-3">Latitude</th>
                        <th scope="col" className="py-1 pr-3">Longitude</th>
                        <th scope="col" className="py-1 pr-3">Depth (m)</th>
                        <th scope="col" className="py-1">Recorded as</th>
                      </tr>
                    </thead>
                    <tbody>
                      {obs.data.items.slice(0, 12).map((o) => (
                        <tr key={o.id} className="border-t border-slate-100">
                          <td className="py-1 pr-3">{o.timestamp.slice(0, 10)}</td>
                          <td className="py-1 pr-3">{o.latitude.toFixed(3)}</td>
                          <td className="py-1 pr-3">{o.longitude.toFixed(3)}</td>
                          <td className="py-1 pr-3">{o.max_depth ?? o.min_depth ?? "–"}</td>
                          <td className="py-1 italic text-slate-600">{o.scientific_name}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                  <p className="mt-1 text-xs text-slate-500">Showing 12 of {obs.data.total.toLocaleString()} stored records. Source: OBIS.</p>
                </div>
              )}
            </Section>

            <ContextBar showRegion={false} note="Environmental exposure below is computed for the selected dataset." />
            <Section
              title="Potential environmental exposure"
              tag="derived"
              subtitle="How current conditions compare at the places this species was recorded in the last two years. This is exposure, not confirmed ecological damage."
            >
              <Status isLoading={risk.isLoading} error={risk.error} hasData={!!r}>
                {r && !r.available ? (
                  <EmptyState title="Exposure cannot be assessed">
                    <p>{r.message}</p>
                  </EmptyState>
                ) : (
                  r && (
                    <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
                      <Stat label="Observed locations" value={plural(r.observed_locations ?? 0, "grid cell")} note={`${r.n_records.toLocaleString()} records, grid cells of the selected dataset`} />
                      <Stat
                        label={<Term k="anomaly">Locations overlapping an SST anomaly</Term>}
                        value={`${r.overlapping_locations ?? 0} of ${r.observed_locations ?? 0}`}
                        note={`${r.exposure_pct_locations?.toFixed(0) ?? "0"}% of locations ≥ 1 °C from normal (${r.exposed_share != null ? (r.exposed_share * 100).toFixed(0) : "0"}% of records)`}
                      />
                      <Stat label="Average SST anomaly" value={signed(r.mean_anomaly_c)} note="record-weighted, latest observed day" />
                      <Stat label="Maximum SST anomaly" value={signed(r.max_anomaly_c)} note="strongest at any recorded location" />
                      <Stat
                        label={<><Term k="heatwave">Marine heatwave</Term> overlap</>}
                        value={r.heatwave_locations == null ? "n/a" : plural(r.heatwave_locations, "location")}
                        note={r.heatwave_days_max != null ? `heatwave day ${r.heatwave_days_mean} on average (up to ${r.heatwave_days_max})` : "no recorded location is currently in a heatwave"}
                      />
                      <Stat
                        label="Forecast exposure (7 days)"
                        value={r.forecast_exposure ? <SeverityBadge level={r.forecast_exposure} /> : "n/a"}
                        note={`mean forecast anomaly ${signed(r.forecast_mean_anomaly_c)} (model output)`}
                      />
                      <Stat
                        label={<>Typical <Term k="sst">SST</Term> at records</>}
                        value={r.thermal_range_c ? `${r.thermal_range_c.p10}–${r.thermal_range_c.p90} °C` : "n/a"}
                        note={r.thermal_range_c ? `median ${r.thermal_range_c.median} °C, ${r.thermal_range_c.n} records` : "needs 5+ records in the last 2 years of SST history"}
                      />
                      <Stat label="Latest record used" value={r.latest_record ?? "n/a"} />
                    </div>
                  )
                )}
              </Status>
            </Section>

            <Section title="Ecological risk" tag="derived">
              {r?.available && r.level ? (
                <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
                  <div>
                    <div className="flex flex-wrap items-center gap-3">
                      <SeverityBadge level={r.level} />
                      <span className="text-sm text-slate-800">score <strong>{r.score?.toFixed(2)}</strong> of 1 · <Term k="risk">project environmental risk indicator</Term></span>
                    </div>
                    <div className="mt-3"><FactorBars factors={r.factors} /></div>
                    <p className="mt-3 text-xs text-slate-600">
                      Modelled <strong>potential exposure</strong> / monitoring priority from {r.n_records.toLocaleString()} OBIS records in the last {r.window_days} days. It is not a
                      measurement of confirmed ecological damage. <Link to="/ecological-risk?tab=method" className="underline">How the score is calculated</Link>
                    </p>
                  </div>
                  <WhyPanel title={`Why is exposure ${r.level}?`} reasons={r.reasons} classification={r.labels.score} sources={["OBIS (records)", r.labels.conditions]} />
                  <RelatedLinks to={["map", "heatwaves", "risk"]} />
                </div>
              ) : (
                <EmptyState title="Insufficient evidence for a risk indicator">
                  <p>{r?.message ?? "A risk indicator needs recent observations inside the study region."}</p>
                </EmptyState>
              )}
            </Section>

            <Section title="Not included, and sources" tag="interpretation">
              <p className="text-sm text-slate-700">
                Threat descriptions, habitat classification and range polygons are <strong>not loaded</strong>: no authoritative dataset is connected (they would need the IUCN Red
                List API with a key or curated range data). Nothing here is inferred to fill that gap.
              </p>
              <ul className="mt-2 list-disc space-y-1 pl-5 text-sm text-slate-700">
                <li><strong>Observation:</strong> species records (OBIS) and SST (NOAA OISST v2.1).</li>
                <li><strong>Model output:</strong> the 7-day forecast (ConvLSTM) used in the forecast factor.</li>
                <li><strong>Derived metric:</strong> anomaly, heatwave state, exposure and the risk indicator.</li>
                <li><strong>Interpretation:</strong> the plain-language explanations; they describe potential exposure, not proven effects.</li>
              </ul>
              <p className="mt-2 text-xs text-slate-600">
                Taxonomy:{" "}
                {s.sources.taxonomy && <a href={s.sources.taxonomy} className="underline" target="_blank" rel="noreferrer">OBIS</a>}
                {s.sources.worms && <> · <a href={s.sources.worms} className="underline" target="_blank" rel="noreferrer">WoRMS</a></>}
                {" "}· Conservation: {s.iucn_source ?? "none reported"}
                {s.last_synced_at && <> · Catalogue refreshed {s.last_synced_at.slice(0, 10)}</>}
              </p>
            </Section>
          </div>
        )}
      </Status>
    </div>
  );
}
