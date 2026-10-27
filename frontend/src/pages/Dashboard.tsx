import { Link, useNavigate } from "react-router-dom";
import { getBiodiversitySummary, getRiskAreas, getSpeciesRanking, listHeatwaves } from "../api/intelligence";
import { getAlertSummary, listAlerts } from "../api/modelOutputs";
import AlertCard from "../components/AlertCard";
import DashSection, { Metric } from "../components/DashSection";
import EmptyState from "../components/EmptyState";
import OceanMap from "../components/OceanMap";
import PageHeader from "../components/PageHeader";
import RegionForecast from "../components/RegionForecast";
import SeverityBadge from "../components/SeverityBadge";
import SourceTag from "../components/SourceTag";
import Status from "../components/Status";
import Term from "../components/Term";
import TrendCharts from "../components/TrendCharts";
import WhyPanel from "../components/WhyPanel";
import { useAsync } from "../hooks/useAsync";
import { cached, useOverview } from "../hooks/useCached";
import type { Alert } from "../types";
import ContextBar from "../components/ContextBar";
import PacificDashboard from "../components/PacificDashboard";
import { useActive } from "../contexts/ActiveSelection";

const signed = (v: number | null, d = 1) => (v == null ? "–" : `${v > 0 ? "+" : ""}${v.toFixed(d)}`);
const km2 = (v: number) => `${Math.round(v).toLocaleString()} km²`;

function NeDashboard() {
  const navigate = useNavigate();
  const overview = useOverview();
  const alerts = useAsync(() => listAlerts({ status: "NEW", page_size: 4 }), []);
  const alertSummary = useAsync(() => cached("alert-summary", getAlertSummary), []);
  const heatwaves = useAsync(() => cached("heatwaves", () => listHeatwaves()), []);
  const riskAreas = useAsync(() => getRiskAreas("HIGH", 5), []);
  const speciesRank = useAsync(() => getSpeciesRanking(), []);
  const bio = useAsync(() => cached("bio-summary", getBiodiversitySummary), []);
  const o = overview.data;
  const lastIdx = o ? o.forecast_sst.length - 1 : 0;
  const events = heatwaves.data?.items ?? [];
  const maxIntensity = events.length ? Math.max(...events.map((e) => e.max_anomaly_c)) : null;
  const largest = events.length ? events.reduce((a, b) => (b.area_km2 > a.area_km2 ? b : a)) : null;
  const topSpecies = (speciesRank.data?.items ?? []).filter((s) => s.available && s.level).slice(0, 3);
  const dataLoaded = !!o;

  return (
    <div>
      <PageHeader title="Ocean Environmental Intelligence Dashboard">
        Start here. This page summarises what the ocean is doing, what the model expects, where marine heatwaves are, which species have records in those areas and which
        alerts need attention. Every card links to the detailed page.
      </PageHeader>

      <div className="mt-3">
        <ContextBar showRegion={false} note="NE Pacific study-region dashboard (observed SST, ConvLSTM forecast). Switch the dataset to see the Pacific-wide overview." />
      </div>
      <div className="on-deep mt-4 rounded-lg bg-gradient-to-r from-deep via-abyss to-tide px-4 py-3 text-sm leading-relaxed text-cyan-50" role="note">
        {o ? (
          <>
            <strong>Latest available data (not a live feed):</strong> observations to <strong>{o.data_status.observed_date}</strong> ({o.data_status.data_age_days} days ago).{" "}
            Forecast issued from {o.data_status.observed_date} for {o.data_status.forecast_dates[0]} → {o.data_status.forecast_dates[o.data_status.forecast_dates.length - 1]}
            {o.data_status.export_generated_at ? ` (computed ${o.data_status.export_generated_at.slice(0, 10)})` : ""}.
          </>
        ) : (
          <>Checking the latest available data…</>
        )}
        <br />
        <strong>Coverage:</strong> the environmental model (SST, forecast, heatwaves, risk) covers the NE Pacific study region (20–50°N, 160–120°W) only. Biodiversity records
        come from OBIS, which is global where observations exist; this installation stores a time-spread selection of records for the study region.{" "}
        <Link to="/ocean-map" className="font-semibold text-white underline">Open the Pacific Ocean map (SST and anomaly across the whole Pacific) →</Link>
      </div>

      <section className="mt-4" aria-label="Summary">
        <Status isLoading={overview.isLoading} error={overview.error} hasData={dataLoaded} emptyMessage="No forecast export was found. Generate it with: python -m oceanmind_model export-dashboard">
          {o && (
            <div className="grid grid-cols-1 gap-4 md:grid-cols-2 xl:grid-cols-3">
              <DashSection title="Ocean conditions" to="/anomaly" linkLabel="Open anomalies" tag="observed">
                <Metric
                  label={<Term k="sst">Sea surface temperature</Term>}
                  value={o.current_sst == null ? "–" : `${o.current_sst.toFixed(1)} °C`}
                  note="Average over the study region."
                  meta={`Date ${o.data_status.observed_date} · Source NOAA OISST v2.1`}
                />
                <Metric
                  label={<Term k="anomaly">SST anomaly</Term>}
                  value={`${signed(o.current_anomaly)} °C`}
                  note={
                    o.current_anomaly == null
                      ? undefined
                      : `The sea is ${Math.abs(o.current_anomaly).toFixed(1)} °C ${o.current_anomaly >= 0 ? "above" : "below"} the expected value for this date; ${(o.hotspot_share_now * 100).toFixed(1)}% of the area is at least ${o.hotspot_threshold.toFixed(0)} °C from normal.`
                  }
                  meta={`Date ${o.data_status.observed_date} · Derived from NOAA OISST`}
                />
              </DashSection>

              <DashSection title="Forecast" to="/forecast" linkLabel="Open forecast" tag="forecast">
                <Metric
                  label={`Forecast SST, +${o.snapshot.latest.target_dates.length} days`}
                  value={o.forecast_sst[lastIdx] == null ? "–" : `${o.forecast_sst[lastIdx]!.toFixed(1)} °C`}
                  note={`${signed(o.forecast_change_c)} °C versus the last observation (trend: ${o.forecast_trend}).`}
                  meta={`For ${o.data_status.forecast_dates[o.data_status.forecast_dates.length - 1]} · ConvLSTM model output`}
                />
                <Metric
                  label="Forecast anomaly"
                  value={`${signed(o.forecast_anomaly[lastIdx])} °C`}
                  note={`Expected difference from normal at a horizon of ${o.snapshot.latest.target_dates.length} days. Typical forecast error is about ${o.improvement.convlstm_mae.toFixed(2)} °C.`}
                />
              </DashSection>

              <DashSection title="Marine heatwaves" to="/heatwaves" linkLabel="Open marine heatwaves" tag="derived">
                <Metric
                  label={<Term k="heatwave">Active events</Term>}
                  value={heatwaves.data ? String(events.length) : "…"}
                  note={o.heatwave ? `${(o.heatwave.active_share * 100).toFixed(1)}% of the ocean area (${km2(o.heatwave.active_area_km2)}) is in a heatwave state.` : "Heatwave export not found."}
                  meta={`Date ${o.data_status.observed_date} · project definition`}
                />
                <Metric label="Largest affected area" value={largest ? km2(largest.area_km2) : "–"} note={largest ? `${largest.category_name}, ${largest.duration_days} days so far.` : "No active event."} />
                <Metric label="Maximum intensity" value={maxIntensity == null ? "–" : `${signed(maxIntensity)} °C`} note="Strongest anomaly reached within any active event." />
              </DashSection>

              <DashSection title="Biodiversity" to="/species" linkLabel="Open species" tag="observed">
                <Metric
                  label="Species observed"
                  value={bio.data ? String(bio.data.species_with_records) : "…"}
                  note={bio.data ? `${bio.data.n_species} species catalogued; ${bio.data.n_records.toLocaleString()} OBIS records stored.` : undefined}
                  meta="Source OBIS (time-spread selection of records for the study region)"
                />
                <Metric
                  label="Recent observations"
                  value={bio.data ? bio.data.records_last_90_days.toLocaleString() : "…"}
                  note={bio.data?.latest_observation ? `Records in the 90 days up to the latest record (${bio.data.latest_observation.slice(0, 10)}).` : "No records loaded yet."}
                />
                <Metric
                  label="Conservation-sensitive species"
                  value={bio.data ? String(bio.data.conservation_sensitive_with_records) : "…"}
                  note="Species with records that a source lists as Vulnerable, Endangered or Critically Endangered."
                />
              </DashSection>

              <DashSection title="Ecological risk" to="/ecological-risk" linkLabel="Open ecological risk" tag="derived">
                <Metric
                  label={<Term k="risk">Cells rated HIGH or CRITICAL</Term>}
                  value={`${(o.risk.share_high_or_critical * 100).toFixed(1)}%`}
                  note="Share of ocean cells where anomaly, heatwave persistence, forecast and species overlap combine to a high score."
                />
                <div>
                  <div className="text-xs font-medium text-slate-600">Highest-risk areas</div>
                  {riskAreas.data && riskAreas.data.items.length > 0 ? (
                    <ul className="mt-1 space-y-1 text-sm">
                      {riskAreas.data.items.slice(0, 3).map((r) => (
                        <li key={`${r.lat}-${r.lon}`} className="flex items-center justify-between gap-2">
                          <span>{r.lat.toFixed(1)}°N, {Math.abs(r.lon).toFixed(1)}°W</span>
                          <SeverityBadge level={r.level} />
                        </li>
                      ))}
                    </ul>
                  ) : (
                    <p className="text-sm text-slate-600">{riskAreas.isLoading ? "Loading…" : "No 2°×2° area is rated HIGH or above."}</p>
                  )}
                </div>
                <div>
                  <div className="text-xs font-medium text-slate-600">Species with the highest potential exposure</div>
                  {topSpecies.length > 0 ? (
                    <ul className="mt-1 space-y-1 text-sm">
                      {topSpecies.map((s) => (
                        <li key={s.aphia_id} className="flex items-center justify-between gap-2">
                          <Link to={`/species/${s.aphia_id}`} className="underline">{s.common_name ?? s.scientific_name}</Link>
                          {s.level && <SeverityBadge level={s.level} />}
                        </li>
                      ))}
                    </ul>
                  ) : (
                    <p className="text-sm text-slate-600">{speciesRank.isLoading ? "Loading…" : "No species with recent records."}</p>
                  )}
                </div>
              </DashSection>

              <DashSection title="Alerts" to="/alerts" linkLabel="Open alerts" tag="derived">
                <Metric label="Open alerts" value={alertSummary.data ? String(alertSummary.data.open) : "…"} note="New or acknowledged, not yet resolved." />
                <Metric
                  label="High-severity open alerts"
                  value={alertSummary.data ? String(alertSummary.data.open_high_or_critical) : "…"}
                  note="Severity HIGH or CRITICAL. Each alert explains its evidence."
                />
              </DashSection>
            </div>
          )}
        </Status>
      </section>

      {o && (
        <section className="mt-6">
          <WhyPanel title="What does this mean?" reasons={o.interpretation} classification="Plain-language reading of observations, model output and derived metrics" />
        </section>
      )}

      <section className="mt-8" aria-labelledby="map-h">
        <div className="mb-3 flex items-baseline justify-between">
          <h2 id="map-h" className="border-l-4 border-lagoon pl-3 text-lg font-semibold text-slate-900">NE Pacific study-region map</h2>
          <Link to="/ocean-map" className="text-sm font-semibold text-tide hover:underline">Open the full Pacific map →</Link>
        </div>
        <OceanMap initialLayer="observed_anomaly" events={events} onEventClick={(id) => navigate(`/heatwaves?event=${id}`)} />
      </section>

      <div className="mt-8">
        <RegionForecast />
      </div>

      <section className="mt-8" aria-labelledby="alerts-h">
        <div className="mb-3 flex items-baseline justify-between">
          <h2 id="alerts-h" className="border-l-4 border-orange-500 pl-3 text-lg font-semibold text-slate-900">Newest open alerts</h2>
          <Link to="/alerts" className="text-sm font-medium text-slate-700 underline">All alerts →</Link>
        </div>
        <Status isLoading={alerts.isLoading} error={alerts.error} hasData={!!alerts.data}>
          {alerts.data && alerts.data.items.length === 0 ? (
            <EmptyState title="No new alerts">
              <p>Alerts are created when a marine heatwave, a strong anomaly, a forecast heat signal or a high species exposure is found.</p>
              <p>If you expect alerts, run: python -m app.jobs publish-outputs</p>
            </EmptyState>
          ) : (
            <div className="grid grid-cols-1 gap-3 lg:grid-cols-2">
              {alerts.data?.items.map((a: Alert) => (
                <Link key={a.id} to={`/alerts?open=${a.id}`} className="block rounded-lg" aria-label={`Open alert: ${a.message}`}>
                  <AlertCard alert={a} compact />
                </Link>
              ))}
            </div>
          )}
        </Status>
      </section>

      <div className="mt-8">
        <TrendCharts />
      </div>

      {o && (
        <p className="mt-6 flex flex-wrap items-center gap-2 text-sm text-slate-700">
          <SourceTag kind="evaluation" />
          The forecast model had a {(o.improvement.relative * 100).toFixed(1)}% lower mean absolute error than the persistence baseline on the held-out test period.{" "}
          <Link to="/performance" className="font-medium text-slate-900 underline">See model performance →</Link>
        </p>
      )}
    </div>
  );
}

/** The Dashboard of the active dataset: the NE Pacific study-region overview, or the Pacific-wide overview built from the environment API. */
export default function Dashboard() {
  const act = useActive();
  return act.dataset === "ne_pacific" ? <NeDashboard /> : <PacificDashboard />;
}
