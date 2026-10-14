import Badge from "../components/Badge";
import DataTable from "../components/DataTable";
import type { Column } from "../components/DataTable";
import FilterPanel from "../components/FilterPanel";
import type { FilterField } from "../components/FilterPanel";
import Pagination from "../components/Pagination";
import { listAnomalies } from "../api/modelOutputs";
import { usePagedList } from "../hooks/usePagedList";
import type { AnomalyDetection } from "../types";
import { formatCoord, formatTimestamp } from "../utils/format";
import { GEO_TIME_FIELDS, toQueryParams } from "../utils/filters";

const PAGE_SIZE = 20;

const FIELDS: FilterField[] = [
  ...GEO_TIME_FIELDS,
  {
    name: "is_anomaly",
    label: "Show",
    type: "select",
    options: [
      { value: "true", label: "Anomalies only" },
      { value: "false", label: "Normal only" },
    ],
  },
];

const COLUMNS: Column<AnomalyDetection>[] = [
  { header: "Observed", cell: (r) => formatTimestamp(r.timestamp) },
  { header: "Latitude", cell: (r) => formatCoord(r.latitude) },
  { header: "Longitude", cell: (r) => formatCoord(r.longitude) },
  { header: "Anomaly score", cell: (r) => r.anomaly_score.toFixed(3) },
  {
    header: "Result",
    cell: (r) => (r.is_anomaly ? <Badge tone="red">ANOMALY</Badge> : <Badge tone="slate">Normal</Badge>),
  },
  { header: "Model version", cell: (r) => r.model_version },
];

export default function Anomalies() {
  const list = usePagedList(listAnomalies, PAGE_SIZE);

  return (
    <div>
      <h1 className="text-xl font-semibold text-slate-900">Anomaly Detection</h1>
      <p className="mt-1 text-sm text-slate-500">
        Ocean observations scored by the anomaly detector (currently placeholder data).
      </p>
      <FilterPanel fields={FIELDS} onApply={(v) => list.setFilters(toQueryParams(v))} />
      <DataTable
        columns={COLUMNS}
        rows={list.items}
        rowKey={(r) => r.id}
        isLoading={list.isLoading}
        error={list.error}
        emptyMessage="No detections match these filters."
        rowClassName={(r) => (r.is_anomaly ? "bg-red-50" : "")}
      />
      <Pagination page={list.page} pageSize={PAGE_SIZE} total={list.total} isLoading={list.isLoading} onPageChange={list.setPage} />
    </div>
  );
}
