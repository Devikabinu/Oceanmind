import { useMemo, useState } from "react";
import { useSearchParams } from "react-router-dom";
import AlertCard from "../components/AlertCard";
import EmptyState from "../components/EmptyState";
import FilterPanel from "../components/FilterPanel";
import type { FilterField } from "../components/FilterPanel";
import PageHeader from "../components/PageHeader";
import Pagination from "../components/Pagination";
import { apiClient } from "../api/client";
import { listAlerts, updateAlertStatus } from "../api/modelOutputs";
import { useAuth } from "../contexts/AuthContext";
import { useAsync } from "../hooks/useAsync";
import { usePagedList } from "../hooks/usePagedList";
import type { Alert, AlertStatus } from "../types";
import { errorMessage } from "../utils/format";
import { DATE_RANGE_FIELDS, toQueryParams } from "../utils/filters";

const PAGE_SIZE = 12;
const toOptions = (values: string[]) => values.map((v) => ({ value: v, label: v }));
const SEVERITY_RANK: Record<string, number> = { CRITICAL: 3, HIGH: 2, MEDIUM: 1, LOW: 0 };

const FIELDS: FilterField[] = [
  { name: "status", label: "Status", type: "select", options: toOptions(["NEW", "ACKNOWLEDGED", "RESOLVED"]) },
  { name: "severity", label: "Severity", type: "select", options: toOptions(["LOW", "MEDIUM", "HIGH", "CRITICAL"]) },
  {
    name: "alert_type",
    label: "Alert type",
    type: "select",
    options: [
      { value: "MARINE_HEATWAVE", label: "Marine heatwave" },
      { value: "SST_ANOMALY", label: "SST anomaly" },
      { value: "SST_FORECAST_HEAT", label: "Forecast heat (model)" },
      { value: "ECOLOGICAL_RISK", label: "Ecological risk" },
    ],
  },
  ...DATE_RANGE_FIELDS,
];

export default function Alerts() {
  const { user } = useAuth();
  const canUpdate = user?.role === "ADMIN" || user?.role === "RESEARCHER";
  const [params] = useSearchParams();
  const openId = params.get("open");
  const list = usePagedList(listAlerts, PAGE_SIZE);
  const [sort, setSort] = useState<"newest" | "severity">("newest");
  const [updatingId, setUpdatingId] = useState<string | null>(null);
  const [updateError, setUpdateError] = useState<string | null>(null);
  const focused = useAsync(
    () => (openId ? apiClient.get<Alert>(`/alerts/${openId}`).then((r) => r.data) : Promise.resolve(null)),
    [openId],
  );

  async function changeStatus(alert: Alert, status: AlertStatus) {
    setUpdatingId(alert.id);
    setUpdateError(null);
    try {
      const updated = await updateAlertStatus(alert.id, status);
      list.setItems((rows) => rows.map((r) => (r.id === updated.id ? updated : r)));
    } catch (err) {
      setUpdateError(errorMessage(err));
    } finally {
      setUpdatingId(null);
    }
  }

  const items = useMemo(
    () => (sort === "severity" ? [...list.items].sort((a, b) => SEVERITY_RANK[b.severity] - SEVERITY_RANK[a.severity]) : list.items),
    [list.items, sort],
  );

  return (
    <div>
      <PageHeader title="Alerts">
        Alerts raised from marine heatwaves, SST anomalies, model forecasts and species exposure. Each one states its evidence, data sources and whether it is an
        observation, model output or derived metric.
        {!canUpdate && ` Your role (${user?.role}) has read-only access; updating status requires ADMIN or RESEARCHER.`}
      </PageHeader>

      <FilterPanel fields={FIELDS} onApply={(v) => list.setFilters(toQueryParams(v))} />
      <div className="mt-3 flex items-center gap-2 text-sm text-slate-700">
        <label htmlFor="alert-sort">Sort this page by</label>
        <select
          id="alert-sort"
          value={sort}
          onChange={(e) => setSort(e.target.value as "newest" | "severity")}
          className="rounded-md border border-slate-300 bg-white px-2 py-1 text-sm"
        >
          <option value="newest">Newest first</option>
          <option value="severity">Severity (highest first)</option>
        </select>
        <span className="text-slate-500">{list.total} alert{list.total === 1 ? "" : "s"} match</span>
      </div>

      {updateError && <div className="mt-4 rounded-md bg-red-50 px-3 py-2 text-sm text-red-700">{updateError}</div>}
      {focused.data && (
        <div className="mt-4">
          <div className="mb-1 text-xs font-medium uppercase tracking-wide text-slate-600">Selected alert</div>
          <AlertCard alert={focused.data} canUpdate={canUpdate} busy={updatingId === focused.data.id} onStatus={(a, s) => void changeStatus(a, s)} defaultOpen />
        </div>
      )}

      <div className="mt-4 space-y-3" aria-live="polite">
        {list.error && <div className="rounded-md bg-amber-50 px-3 py-2 text-sm text-amber-800">Could not load alerts: {list.error}</div>}
        {list.isLoading && items.length === 0 && <p className="text-sm text-slate-500">Loading alerts…</p>}
        {!list.isLoading && !list.error && items.length === 0 && (
          Object.keys(list.filters).length > 0 ? (
            <EmptyState title="No alerts match the filters you applied">
              <p>Alerts exist, but none has this combination of status, severity, type and dates. Try widening the date range or clearing a filter.</p>
            </EmptyState>
          ) : (
            <EmptyState title="No alerts have been raised yet">
              <p>Alerts are created when the publish job finds a marine heatwave, a strong SST anomaly, a forecast heat signal or a high species exposure.</p>
              <p>To create them from the latest data run: python -m app.jobs publish-outputs</p>
            </EmptyState>
          )
        )}
        {items.map((a) => (
          <AlertCard key={a.id} alert={a} canUpdate={canUpdate} busy={updatingId === a.id} onStatus={(x, s) => void changeStatus(x, s)} />
        ))}
      </div>
      <Pagination page={list.page} pageSize={PAGE_SIZE} total={list.total} isLoading={list.isLoading} onPageChange={list.setPage} />
    </div>
  );
}
