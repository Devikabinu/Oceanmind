import DataTable from "../components/DataTable";
import type { Column } from "../components/DataTable";
import FilterPanel from "../components/FilterPanel";
import type { FilterField } from "../components/FilterPanel";
import Pagination from "../components/Pagination";
import { listForecasts } from "../api/modelOutputs";
import { usePagedList } from "../hooks/usePagedList";
import type { SSTForecast } from "../types";
import { formatCoord, formatTimestamp } from "../utils/format";
import { GEO_TIME_FIELDS, toQueryParams } from "../utils/filters";

const PAGE_SIZE = 20;

const FIELDS: FilterField[] = [
  ...GEO_TIME_FIELDS,
  { name: "forecast_horizon_days", label: "Horizon (days)", type: "number", min: 1, max: 365 },
];

const COLUMNS: Column<SSTForecast>[] = [
  { header: "Forecast for", cell: (r) => formatTimestamp(r.timestamp) },
  { header: "Latitude", cell: (r) => formatCoord(r.latitude) },
  { header: "Longitude", cell: (r) => formatCoord(r.longitude) },
  {
    header: "Predicted SST (°C)",
    cell: (r) => <span className="font-medium text-slate-900">{r.predicted_sst.toFixed(2)}</span>,
  },
  { header: "Horizon", cell: (r) => `${r.forecast_horizon_days} d` },
  { header: "Model version", cell: (r) => r.model_version },
];

export default function Forecast() {
  const list = usePagedList(listForecasts, PAGE_SIZE);

  return (
    <div>
      <h1 className="text-xl font-semibold text-slate-900">SST Forecasts</h1>
      <p className="mt-1 text-sm text-slate-500">
        Sea surface temperature predictions from the forecasting module (currently placeholder data).
      </p>
      <FilterPanel fields={FIELDS} onApply={(v) => list.setFilters(toQueryParams(v))} />
      <DataTable
        columns={COLUMNS}
        rows={list.items}
        rowKey={(r) => r.id}
        isLoading={list.isLoading}
        error={list.error}
        emptyMessage="No forecasts match these filters."
      />
      <Pagination page={list.page} pageSize={PAGE_SIZE} total={list.total} isLoading={list.isLoading} onPageChange={list.setPage} />
    </div>
  );
}
