import { useState } from "react";
import { Link } from "react-router-dom";
import { listSpecies, searchObis, trackSpecies } from "../api/intelligence";
import type { SearchHit } from "../api/intelligence";
import Badge from "../components/Badge";
import ConservationBadge from "../components/ConservationBadge";
import EmptyState from "../components/EmptyState";
import PageHeader from "../components/PageHeader";
import Pagination from "../components/Pagination";
import SourceTag from "../components/SourceTag";
import Status from "../components/Status";
import { useAuth } from "../contexts/AuthContext";
import { useAsync } from "../hooks/useAsync";
import { errorMessage } from "../utils/format";

const GROUPS = ["Marine mammals", "Sea turtles", "Sharks & rays", "Fish", "Seabirds", "Corals", "Other marine organisms"];
const PAGE_SIZE = 18;
const STATUSES: [string, string][] = [
  ["CR", "Critically Endangered"],
  ["EN", "Endangered"],
  ["VU", "Vulnerable"],
  ["NT", "Near Threatened"],
  ["LC", "Least Concern"],
  ["DD", "Data Deficient"],
  ["NE", "Not Evaluated"],
  ["UNCONFIRMED", "Status not confirmed"],
];

export default function SpeciesList() {
  const { user } = useAuth();
  const canAdd = user?.role === "ADMIN" || user?.role === "RESEARCHER";
  const [q, setQ] = useState("");
  const [applied, setApplied] = useState("");
  const [group, setGroup] = useState("");
  const [threatened, setThreatened] = useState(false);
  const [status, setStatus] = useState("");
  const [page, setPage] = useState(1);
  const [hits, setHits] = useState<SearchHit[] | null>(null);
  const [searchError, setSearchError] = useState<string | null>(null);
  const [adding, setAdding] = useState<number | null>(null);
  const [version, setVersion] = useState(0);

  const list = useAsync(
    () => listSpecies({ q: applied || undefined, group: group || undefined, threatened: threatened || undefined, status: status || undefined, page, page_size: PAGE_SIZE }),
    [applied, group, threatened, status, page, version],
  );

  async function searchRemote() {
    setSearchError(null);
    setHits(null);
    try {
      setHits(await searchObis(applied));
    } catch (err) {
      setSearchError(errorMessage(err));
    }
  }

  async function add(hit: SearchHit) {
    setAdding(hit.aphia_id);
    try {
      await trackSpecies(hit.aphia_id);
      setVersion((v) => v + 1);
      setHits((h) => h?.map((x) => (x.aphia_id === hit.aphia_id ? { ...x, in_catalogue: true } : x)) ?? null);
    } catch (err) {
      setSearchError(errorMessage(err));
    } finally {
      setAdding(null);
    }
  }

  const data = list.data;
  return (
    <div>
      <PageHeader title="Marine biodiversity: species">
        Browse marine species with real occurrence records from OBIS. Taxonomy comes from OBIS/WoRMS. Conservation status is the IUCN Red List category reported by GBIF
        (with the OBIS threatened-species checklist as a fallback); where no source reports one, the species shows “Status not confirmed”. Nothing is typed in by hand.
      </PageHeader>

      <form
        className="mt-4 flex flex-wrap items-end gap-3 rounded-lg border border-slate-200 bg-white p-3"
        onSubmit={(e) => {
          e.preventDefault();
          setApplied(q.trim());
          setPage(1);
          setHits(null);
        }}
        role="search"
      >
        <label className="flex min-w-60 flex-1 flex-col gap-1 text-xs font-medium text-slate-600">
          Search by common name, scientific name or taxonomy
          <input value={q} onChange={(e) => setQ(e.target.value)} placeholder="e.g. humpback, Chelonia mydas, Cheloniidae" className="rounded-md border border-slate-300 px-3 py-1.5 text-sm text-slate-900" />
        </label>
        <label className="flex flex-col gap-1 text-xs font-medium text-slate-600">
          Group
          <select value={group} onChange={(e) => { setGroup(e.target.value); setPage(1); }} className="rounded-md border border-slate-300 bg-white px-2 py-1.5 text-sm">
            <option value="">All groups</option>
            {GROUPS.map((g) => (
              <option key={g} value={g}>
                {g} {data?.groups[g] != null ? `(${data.groups[g]})` : ""}
              </option>
            ))}
          </select>
        </label>
        <label className="flex flex-col gap-1 text-xs font-medium text-slate-600">
          Conservation status
          <select value={status} onChange={(e) => { setStatus(e.target.value); setPage(1); }} className="rounded-md border border-slate-300 bg-white px-2 py-1.5 text-sm" aria-label="Conservation status">
            <option value="">Any status</option>
            {STATUSES.map(([code, label]) => (
              <option key={code} value={code}>
                {label} {data?.statuses[code] != null ? `(${data.statuses[code]})` : ""}
              </option>
            ))}
          </select>
        </label>
        <label className="flex items-center gap-1.5 pb-1.5 text-sm text-slate-700">
          <input type="checkbox" checked={threatened} onChange={(e) => { setThreatened(e.target.checked); setPage(1); }} />
          Threatened only (VU/EN/CR)
        </label>
        <button type="submit" className="rounded-md bg-slate-900 px-4 py-1.5 text-sm font-medium text-white hover:bg-slate-700">Search</button>
      </form>

      <Status isLoading={list.isLoading} error={list.error} hasData={!!data}>
        {data && data.items.length === 0 ? (
          <div className="mt-4">
            <EmptyState
              title={!applied && !group && !threatened && !status ? "The species catalogue is empty" : "No catalogued species match"}
              action={
                applied.length >= 3 ? (
                  <button type="button" onClick={() => void searchRemote()} className="rounded-md border border-slate-300 px-3 py-1.5 text-sm font-medium hover:bg-slate-50">
                    Search all of OBIS for “{applied}”
                  </button>
                ) : undefined
              }
            >
              {!applied && !group && !threatened && !status ? (
                <p>No species have been loaded. Load species and real OBIS records with: python -m app.jobs sync-biodiversity</p>
              ) : (
                <>
                  <p>
                    {applied ? `Nothing in the catalogue matches “${applied}”` : "No catalogued species fit this combination of filters"}
                    {group || status || threatened ? " with the selected group / status filters" : ""}. The filters may simply be too restrictive: try “Any status” or “All groups”.
                  </p>
                  <p>The catalogue holds only species that have been added; OBIS covers many more{applied.length >= 3 ? ", so you can search it directly" : ""}.</p>
                </>
              )}
            </EmptyState>
          </div>
        ) : (
          <>
            <p className="mt-3 text-sm text-slate-600" aria-live="polite">{data?.total} species</p>
            <ul className="mt-2 grid grid-cols-1 gap-3 sm:grid-cols-2 xl:grid-cols-3">
              {data?.items.map((s) => (
                <li key={s.aphia_id}>
                  <Link to={`/species/${s.aphia_id}`} className="block h-full rounded-lg border border-slate-200 bg-white p-4 hover:border-slate-400">
                    <div className="flex items-start justify-between gap-2">
                      <div>
                        <div className="text-base font-semibold text-slate-900">{s.common_name ?? s.scientific_name}</div>
                        <div className="text-sm italic text-slate-600">{s.scientific_name}</div>
                      </div>
                      <Badge tone="blue">{s.taxon_group}</Badge>
                    </div>
                    <div className="mt-3 flex flex-wrap items-center gap-2 text-xs text-slate-600">
                      <ConservationBadge category={s.iucn_category} label={s.iucn_label} source={s.iucn_source} />
                      <span>
                        {s.n_observations > 0 ? `${s.n_observations.toLocaleString()} stored records` : "No stored records yet"}
                        {s.last_observation ? ` · latest ${s.last_observation.slice(0, 10)}` : ""}
                      </span>
                    </div>
                  </Link>
                </li>
              ))}
            </ul>
            <Pagination page={page} pageSize={PAGE_SIZE} total={data?.total ?? 0} isLoading={list.isLoading} onPageChange={setPage} />
          </>
        )}
      </Status>

      {applied.length >= 3 && data && data.items.length > 0 && !hits && (
        <p className="mt-4 text-sm text-slate-600">
          Not what you are looking for?{" "}
          <button type="button" className="font-medium underline" onClick={() => void searchRemote()}>Search all of OBIS</button>
        </p>
      )}
      {searchError && <div className="mt-3 rounded-md bg-amber-50 px-3 py-2 text-sm text-amber-800">OBIS search failed: {searchError}</div>}
      {hits && (
        <section className="mt-4 rounded-lg border border-slate-200 bg-white p-4" aria-label="OBIS search results">
          <div className="flex items-center gap-2 text-sm font-semibold text-slate-900">Results from OBIS <SourceTag kind="observed" /></div>
          {hits.length === 0 ? (
            <p className="mt-2 text-sm text-slate-600">OBIS has no species matching “{applied}”.</p>
          ) : (
            <ul className="mt-2 divide-y divide-slate-100">
              {hits.map((h) => (
                <li key={h.aphia_id} className="flex items-center justify-between gap-3 py-2 text-sm">
                  <span>
                    <em>{h.scientific_name}</em> <span className="text-xs text-slate-500">{h.taxon_group}{h.family ? ` · ${h.family}` : ""}</span>
                  </span>
                  {h.in_catalogue ? (
                    <Link to={`/species/${h.aphia_id}`} className="text-xs font-medium underline">In catalogue</Link>
                  ) : canAdd ? (
                    <button type="button" disabled={adding === h.aphia_id} onClick={() => void add(h)} className="rounded-md bg-slate-900 px-2.5 py-1 text-xs font-medium text-white disabled:opacity-50">
                      {adding === h.aphia_id ? "Adding…" : "Add to catalogue"}
                    </button>
                  ) : (
                    <span className="text-xs text-slate-500">Adding needs the RESEARCHER or ADMIN role</span>
                  )}
                </li>
              ))}
            </ul>
          )}
        </section>
      )}
    </div>
  );
}
