import Badge from "../components/Badge";
import DataTable from "../components/DataTable";
import type { Column } from "../components/DataTable";
import FilterPanel from "../components/FilterPanel";
import type { FilterField } from "../components/FilterPanel";
import Pagination from "../components/Pagination";
import { listRiskScores } from "../api/modelOutputs";
import { usePagedList } from "../hooks/usePagedList";
import type { EcologicalRiskScore } from "../types";
import { LEVEL_TONE } from "../utils/tones";
import { emptyListMessage, formatCoord, formatTimestamp } from "../utils/format";
import { GEO_TIME_FIELDS, toQueryParams } from "../utils/filters";

const PAGE_SIZE = 20;

const FIELDS: FilterField[] = [
  ...GEO_TIME_FIELDS,
  {
    name: "risk_level",
    label: "Risk level",
    type: "select",
    options: ["LOW", "MEDIUM", "HIGH", "CRITICAL"].map((v) => ({ value: v, label: v === "MEDIUM" ? "MODERATE" : v })),
  },
];

const COLUMNS: Column<EcologicalRiskScore>[] = [
  { header: "Observed", cell: (r) => formatTimestamp(r.timestamp) },
  {
    header: "Species",
    cell: (r) => <em>{typeof r.contributing_factors.species === "string" ? r.contributing_factors.species : "-"}</em>,
  },
  { header: "Latitude", cell: (r) => formatCoord(r.latitude) },
  { header: "Longitude", cell: (r) => formatCoord(r.longitude) },
  { header: "Risk score", cell: (r) => r.risk_score.toFixed(3) },
  { header: "Risk level", cell: (r) => <Badge tone={LEVEL_TONE[r.risk_level]}>{r.risk_level}</Badge> },
];

export default function Risk({ embedded = false }: { embedded?: boolean }) {
  const list = usePagedList(listRiskScores, PAGE_SIZE);

  return (
    <div>
      {embedded ? <h2 className="text-lg font-semibold text-slate-900">Risk scores for recorded species</h2> : <h1 className="text-2xl font-semibold tracking-tight text-slate-900">Ecological Risk</h1>}
      <p className="mt-1 text-sm text-slate-500">
        Project risk indicator for recorded marine species occurrences (potential exposure, computed by the publish-outputs job).
      </p>
      <FilterPanel fields={FIELDS} onApply={(v) => list.setFilters(toQueryParams(v))} />
      <DataTable
        columns={COLUMNS}
        rows={list.items}
        rowKey={(r) => r.id}
        isLoading={list.isLoading}
        error={list.error}
        emptyMessage={emptyListMessage("per-record risk scores", Object.keys(list.filters).length > 0, "Run: python -m app.jobs publish-outputs")}
      />
      <Pagination page={list.page} pageSize={PAGE_SIZE} total={list.total} isLoading={list.isLoading} onPageChange={list.setPage} />
    </div>
  );
}
