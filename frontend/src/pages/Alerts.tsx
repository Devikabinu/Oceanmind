import { useState } from "react";
import Badge from "../components/Badge";
import type { BadgeTone } from "../components/Badge";
import DataTable from "../components/DataTable";
import type { Column } from "../components/DataTable";
import FilterPanel from "../components/FilterPanel";
import type { FilterField } from "../components/FilterPanel";
import Pagination from "../components/Pagination";
import { listAlerts, updateAlertStatus } from "../api/modelOutputs";
import { useAuth } from "../contexts/AuthContext";
import { usePagedList } from "../hooks/usePagedList";
import type { Alert, AlertStatus } from "../types";
import { LEVEL_TONE } from "../utils/tones";
import { errorMessage, formatTimestamp } from "../utils/format";
import { toQueryParams } from "../utils/filters";

const PAGE_SIZE = 20;

const toOptions = (values: string[]) => values.map((v) => ({ value: v, label: v }));

const FIELDS: FilterField[] = [
  { name: "status", label: "Status", type: "select", options: toOptions(["NEW", "ACKNOWLEDGED", "RESOLVED"]) },
  { name: "severity", label: "Severity", type: "select", options: toOptions(["LOW", "MEDIUM", "HIGH", "CRITICAL"]) },
  {
    name: "alert_type",
    label: "Alert type",
    type: "select",
    options: toOptions(["SST_FORECAST_HEAT", "SST_ANOMALY", "ECOLOGICAL_RISK"]),
  },
];

const STATUS_TONE: Record<AlertStatus, BadgeTone> = { NEW: "blue", ACKNOWLEDGED: "yellow", RESOLVED: "green" };

// Alerts only move forward (mirrors the backend rule in alert_service.py).
const NEXT_STATUSES: Record<AlertStatus, AlertStatus[]> = {
  NEW: ["ACKNOWLEDGED", "RESOLVED"],
  ACKNOWLEDGED: ["RESOLVED"],
  RESOLVED: [],
};

export default function Alerts() {
  const { user } = useAuth();
  const canUpdate = user?.role === "ADMIN" || user?.role === "RESEARCHER";
  const list = usePagedList(listAlerts, PAGE_SIZE);
  const [updatingId, setUpdatingId] = useState<string | null>(null);
  const [updateError, setUpdateError] = useState<string | null>(null);

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

  const columns: Column<Alert>[] = [
    { header: "Time", cell: (r) => formatTimestamp(r.timestamp) },
    { header: "Type", cell: (r) => r.alert_type },
    { header: "Severity", cell: (r) => <Badge tone={LEVEL_TONE[r.severity]}>{r.severity}</Badge> },
    { header: "Message", cell: (r) => <span className="text-slate-900">{r.message}</span> },
    {
      header: "Status",
      cell: (r) => {
        const next = NEXT_STATUSES[r.status];
        if (!canUpdate || next.length === 0) return <Badge tone={STATUS_TONE[r.status]}>{r.status}</Badge>;
        return (
          <select
            aria-label={`Status for alert ${r.id}`}
            value={r.status}
            disabled={updatingId === r.id}
            onChange={(e) => void changeStatus(r, e.target.value as AlertStatus)}
            className="rounded-md border border-slate-300 bg-white px-2 py-1 text-xs"
          >
            <option value={r.status}>{r.status}</option>
            {next.map((s) => (
              <option key={s} value={s}>
                {s}
              </option>
            ))}
          </select>
        );
      },
    },
    { header: "Resolved", cell: (r) => (r.resolved_at ? formatTimestamp(r.resolved_at) : "-") },
  ];

  return (
    <div>
      <h1 className="text-xl font-semibold text-slate-900">Alerts</h1>
      <p className="mt-1 text-sm text-slate-500">
        Alerts raised from forecasts, anomalies and risk scores (currently placeholder data).
        {!canUpdate && ` Your role (${user?.role}) has read-only access; updating status requires ADMIN or RESEARCHER.`}
      </p>
      <FilterPanel fields={FIELDS} onApply={(v) => list.setFilters(toQueryParams(v))} />
      {updateError && (
        <div className="mt-4 rounded-md bg-red-50 px-3 py-2 text-sm text-red-700">{updateError}</div>
      )}
      <DataTable
        columns={columns}
        rows={list.items}
        rowKey={(r) => r.id}
        isLoading={list.isLoading}
        error={list.error}
        emptyMessage="No alerts match these filters."
      />
      <Pagination page={list.page} pageSize={PAGE_SIZE} total={list.total} isLoading={list.isLoading} onPageChange={list.setPage} />
    </div>
  );
}
