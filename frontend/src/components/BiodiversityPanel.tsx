import type { ObisBlock, ObisItem, OceanContextBlock, SourceRow } from "../api/environment";

const CONS_TONE: Record<string, string> = {
  CR: "bg-red-100 text-red-900", EN: "bg-orange-100 text-orange-900", VU: "bg-yellow-100 text-yellow-900", NT: "bg-lime-100 text-lime-900", LC: "bg-green-100 text-green-900",
};
const STATUS_NOTE: Record<string, string> = {
  live: "retrieved just now", cached: "from the local cache of an earlier OBIS query", stale_cache: "from an older cached OBIS query (OBIS could not be reached for a refresh)",
};
const STATUS_WORD: Record<string, string> = { CR: "Critically endangered", EN: "Endangered", VU: "Vulnerable", NT: "Near threatened", LC: "Least concern" };

function Chip({ label, value, note }: { label: string; value: string; note?: string }) {
  return (
    <div className="rounded bg-slate-50 px-2 py-1">
      <dt className="text-[11px] text-slate-500">{label}</dt>
      <dd className="text-sm font-semibold text-slate-900">{value}</dd>
      {note && <dd className="text-[10px] text-slate-500">{note}</dd>}
    </div>
  );
}

function SpeciesRow({ s, showExposure }: { s: ObisItem; showExposure: boolean }) {
  return (
    <li className="rounded-md bg-slate-50 p-2 text-sm" data-testid="obis-species">
      <div className="flex flex-wrap items-center gap-2">
        <span className="font-semibold text-slate-900">{s.common_name ?? s.scientific_name}</span>
        <span className={`rounded px-1.5 py-0.5 text-[11px] font-semibold ${CONS_TONE[s.conservation_status] ?? "bg-slate-200 text-slate-800"}`} title={STATUS_WORD[s.conservation_status] ?? "Not assessed in the IUCN Red List category carried by OBIS"}>{s.conservation_status}</span>
        <span className="rounded bg-white px-1.5 py-0.5 text-[10px] font-medium text-slate-600 ring-1 ring-slate-200">{s.recency}</span>
        <span className="rounded bg-white px-1.5 py-0.5 text-[10px] font-medium text-slate-600 ring-1 ring-slate-200">{s.scope_label}</span>
      </div>
      <div className="text-xs italic text-slate-500">{s.scientific_name}{s.group ? ` · ${s.group}` : ""}</div>
      <div className="text-xs text-slate-700">
        {s.records.toLocaleString()} record{s.records === 1 ? "" : "s"}{s.nearest_km != null ? `, nearest ${s.nearest_km.toLocaleString()} km away` : ""}{s.latest_record ? `, latest ${s.latest_record}` : ""}
      </div>
      {showExposure && (s.records_in_heatwave != null || s.records_in_forecast_area != null) && (
        <div className="text-xs font-medium text-slate-800">
          {s.records_in_heatwave != null ? (s.records_in_heatwave > 0 ? `${s.records_in_heatwave} sampled record(s) inside the current marine-heatwave footprint. ` : "No sampled record inside the current marine-heatwave footprint. ") : ""}
          {s.records_in_forecast_area != null ? (s.records_in_forecast_area > 0 ? `${s.records_in_forecast_area} inside the predicted anomaly area (potential forecast exposure).` : "None inside the predicted anomaly area.") : ""}
        </div>
      )}
    </li>
  );
}

/** Live OBIS biodiversity of the place: what was counted, where (local, nearby or regional), when, and the species with their conservation status and distance. */
export function ObisPanel({ o }: { o: ObisBlock }) {
  const c = o.counts!;
  return (
    <div className="space-y-2" data-testid="obis-panel">
      <p className="text-xs font-medium text-slate-800" data-testid="species-counted">{o.label}</p>
      <div className="flex flex-wrap items-center gap-2 text-[11px]">
        <span className="rounded bg-indigo-100 px-1.5 py-0.5 font-semibold text-indigo-900" data-testid="obis-scope">{o.scope_label}</span>
        <span className="text-slate-500">Search area ±{o.half_width_deg}° · {o.window?.start ? `${o.window.start} to ${o.window.end}` : "all years"} · {STATUS_NOTE[o.status ?? ""] ?? o.status}</span>
      </div>
      <dl className="grid grid-cols-2 gap-1 sm:grid-cols-4">
        <Chip label="Observations" value={c.observations.toLocaleString()} note={o.historical ? "older records included" : "last 2 years"} />
        <Chip label="Distinct species" value={c.distinct_species.toLocaleString()} />
        <Chip label="Threatened (CR/EN/VU)" value={c.threatened_species.toLocaleString()} />
        <Chip label="Observation density" value={`${c.density_per_1000_km2.toLocaleString()} /1000 km²`} note={`all time: ${c.observations_all_time.toLocaleString()}`} />
      </dl>
      {o.groups && o.groups.length > 0 && (
        <p className="text-xs text-slate-700"><strong>Groups recorded:</strong> {o.groups.map((g) => `${g.group} (${g.species} species)`).join(", ")}.</p>
      )}
      {o.threatened && o.threatened.length > 0 && (
        <div>
          <div className="text-[11px] font-semibold uppercase tracking-wide text-slate-600">Threatened species recorded here</div>
          <ul className="mt-1 space-y-1.5">{o.threatened.slice(0, 8).map((s) => <SpeciesRow key={s.scientific_name} s={s} showExposure />)}</ul>
        </div>
      )}
      <details className="rounded-md bg-slate-50 p-2">
        <summary className="cursor-pointer text-xs font-semibold text-tide">Most recorded species ({o.items?.length ?? 0} shown)</summary>
        <ul className="mt-1 space-y-1.5">{o.items?.filter((s) => !s.threatened).slice(0, 12).map((s) => <SpeciesRow key={s.scientific_name} s={s} showExposure={false} />)}</ul>
      </details>
      <details className="rounded-md bg-slate-50 p-2" data-testid="obis-trail">
        <summary className="cursor-pointer text-xs font-semibold text-tide">How the search area was chosen</summary>
        <ul className="mt-1 list-disc pl-5 text-xs text-slate-700">
          {o.trail?.map((t) => <li key={`${t.half_width_deg}-${t.window}`}>±{t.half_width_deg}° ({t.scope}, {t.window}): {t.records.toLocaleString()} records{t.half_width_deg === o.half_width_deg && t.records > 0 ? " ← used (smallest area with useful data)" : ""}</li>)}
        </ul>
      </details>
      <ul className="list-disc pl-5 text-[11px] text-slate-500">{o.caveats?.map((t) => <li key={t}>{t}</li>)}</ul>
    </div>
  );
}

/** Potential exposure of the recorded species to the observed heatwave and to the predicted anomaly area. Potential exposure only: never evidence of damage. */
export function ExposurePanel({ o }: { o: ObisBlock }) {
  const e = o.exposure;
  if (!e || !e.records_in_domain) return <p className="text-sm text-slate-700">The recorded places could not be matched to the SST grid, so no overlap with the heatwave or the forecast is stated.</p>;
  const cards: { title: string; x: typeof e.heatwave; tag: string }[] = [
    { title: "Biodiversity exposure: current marine heatwave", x: e.heatwave, tag: "observed footprint" },
    { title: "Potential forecast exposure", x: e.forecast, tag: `predicted |anomaly| ≥ ${e.forecast.threshold_c ?? 1} °C` },
  ];
  return (
    <div className="space-y-2" data-testid="exposure-panel">
      <div className="grid gap-2 sm:grid-cols-2">
        {cards.map((c) => (
          <div key={c.title} className="rounded-md bg-slate-50 p-2 ring-1 ring-slate-200">
            <div className="text-xs font-semibold text-slate-900">{c.title}</div>
            <div className="text-[10px] text-slate-500">{c.tag}</div>
            {c.x.available ? (
              <dl className="mt-1 grid grid-cols-4 gap-1 text-center">
                <div><dd className="text-sm font-semibold">{c.x.species}</dd><dt className="text-[10px] text-slate-500">species{c.x.species_share_pct != null ? ` (${c.x.species_share_pct}%)` : ""}</dt></div>
                <div><dd className="text-sm font-semibold">{c.x.cells ?? "–"}</dd><dt className="text-[10px] text-slate-500">grid cells{c.x.cells_share_pct != null ? ` (${c.x.cells_share_pct}%)` : ""}</dt></div>
                <div><dd className="text-sm font-semibold">{c.x.records}</dd><dt className="text-[10px] text-slate-500">records ({c.x.share_pct}%)</dt></div>
                <div><dd className="text-sm font-semibold">{c.x.threatened_species}</dd><dt className="text-[10px] text-slate-500">threatened</dt></div>
              </dl>
            ) : <p className="mt-1 text-xs text-slate-600">This footprint is not available for the selected date.</p>}
          </div>
        ))}
      </div>
      {o.exposure_text && <p className="text-sm text-slate-800" data-testid="exposure-text">{o.exposure_text}</p>}
      <p className="text-[11px] text-slate-500">Based on {e.records_in_domain.toLocaleString()} sampled records at {e.cells_in_domain ?? "?"} grid cells ({e.species_in_domain ?? "?"} species) of {o.counts?.observations.toLocaleString()} observations in the search area. Records show where animals were observed, not where they are today; observers cluster, so shares by grid cell and by species are the better guide than shares of records.</p>
    </div>
  );
}

/** Chlorophyll-a and surface currents: context from NOAA, not inputs of the forecast model and not part of the risk score. */
export function ContextPanel({ ctx }: { ctx: OceanContextBlock | null | undefined }) {
  if (!ctx) return <p className="text-sm text-slate-700">NOAA ocean-colour and current context is not available for this place right now.</p>;
  if (ctx.status === "refreshing" && !ctx.chlorophyll && !ctx.currents) return <p role="status" className="text-sm text-slate-600">Retrieving NOAA chlorophyll-a and surface-current data for this place…</p>;
  const chl = ctx.chlorophyll;
  const cur = ctx.currents;
  return (
    <div className="space-y-2" data-testid="context-panel">
      {chl && (
        <div className="rounded-md bg-emerald-50/60 p-2 ring-1 ring-emerald-100">
          <div className="text-xs font-semibold text-emerald-900">Chlorophyll-a (ecological context)</div>
          <p className="text-sm text-slate-800" data-testid="chl-text">{chl.available ? chl.text : chl.message}</p>
          <p className="text-[10px] text-slate-500">{chl.dataset} · {chl.source} · {chl.spatial_resolution} · {chl.temporal_resolution}{chl.latest ? ` · latest valid ${chl.latest.date}` : ""} · dataset ends {chl.dataset_end}</p>
        </div>
      )}
      {cur && (
        <div className="rounded-md bg-sky-50/60 p-2 ring-1 ring-sky-100">
          <div className="text-xs font-semibold text-sky-900">Surface currents (physical context)</div>
          <p className="text-sm text-slate-800" data-testid="current-text">{cur.available ? cur.text : cur.message}</p>
          {cur.caveat && <p className="text-[11px] text-slate-600">{cur.caveat}</p>}
          <p className="text-[10px] text-slate-500">{cur.dataset} · {cur.source} · {cur.spatial_resolution} · {cur.temporal_resolution}{cur.latest ? ` · ${cur.latest.date}` : ""}</p>
        </div>
      )}
      {!chl && !cur && <p className="text-sm text-slate-700">NOAA ocean-colour and current context is not available for this place right now.</p>}
      <p className="text-[11px] text-slate-500">These variables are shown as context only: they are not inputs of the ConvLSTM, they are not part of the risk score, and they do not explain the forecast.</p>
    </div>
  );
}

export function SourcesTable({ rows }: { rows: SourceRow[] }) {
  return (
    <div className="overflow-x-auto" data-testid="sources">
      <table className="w-full text-left text-xs">
        <caption className="sr-only">Data sources of this report</caption>
        <thead className="text-slate-500"><tr><th scope="col" className="pr-2">For</th><th scope="col" className="pr-2">Source</th><th scope="col" className="pr-2">Observed</th><th scope="col" className="pr-2">Resolution</th><th scope="col">Retrieved</th></tr></thead>
        <tbody>
          {rows.map((r) => (
            <tr key={r.topic} className="border-t border-slate-100 align-top">
              <td className="pr-2 font-medium text-slate-900">{r.topic}</td>
              <td className="pr-2">{r.source}{r.dataset ? <div className="text-[10px] text-slate-500">{r.dataset}</div> : null}</td>
              <td className="pr-2">{r.observation_date ?? "–"}</td>
              <td className="pr-2">{[r.spatial_resolution, r.temporal_resolution].filter(Boolean).join(" · ") || "–"}</td>
              <td>{r.retrieved ?? "–"}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
