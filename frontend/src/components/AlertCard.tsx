import { useState } from "react";
import { Link } from "react-router-dom";
import type { Alert, AlertStatus } from "../types";
import Badge from "./Badge";
import type { BadgeTone } from "./Badge";
import SeverityBadge from "./SeverityBadge";
import WhyPanel from "./WhyPanel";

export const ALERT_TYPE_LABEL: Record<string, string> = {
  MARINE_HEATWAVE: "Marine heatwave",
  SST_ANOMALY: "SST anomaly",
  SST_FORECAST_HEAT: "Forecast heat (model)",
  ECOLOGICAL_RISK: "Ecological risk",
};

const STATUS_TONE: Record<AlertStatus, BadgeTone> = { NEW: "blue", ACKNOWLEDGED: "yellow", RESOLVED: "green" };
const NEXT: Record<AlertStatus, { to: AlertStatus; label: string }[]> = {
  NEW: [
    { to: "ACKNOWLEDGED", label: "Acknowledge" },
    { to: "RESOLVED", label: "Resolve" },
  ],
  ACKNOWLEDGED: [{ to: "RESOLVED", label: "Resolve" }],
  RESOLVED: [],
};

interface Props {
  alert: Alert;
  canUpdate?: boolean;
  busy?: boolean;
  onStatus?: (a: Alert, s: AlertStatus) => void;
  defaultOpen?: boolean;
  compact?: boolean;
}

/** One alert: what, where, when, severity, status and (expandable) the evidence behind it. */
export default function AlertCard({ alert, canUpdate = false, busy = false, onStatus, defaultOpen = false, compact = false }: Props) {
  const [open, setOpen] = useState(defaultOpen);
  const d = alert.details;
  return (
    <article id={`alert-${alert.id}`} className="rounded-lg border border-slate-200 bg-white p-4" aria-label={`${ALERT_TYPE_LABEL[alert.alert_type] ?? alert.alert_type} alert`}>
      <div className="flex flex-wrap items-center gap-2">
        <SeverityBadge level={alert.severity} />
        <span className="text-sm font-semibold text-slate-900">{ALERT_TYPE_LABEL[alert.alert_type] ?? alert.alert_type}</span>
        <Badge tone={STATUS_TONE[alert.status]}>{alert.status}</Badge>
        <span className="ml-auto text-xs text-slate-500">{alert.timestamp.slice(0, 10)}</span>
      </div>
      <p className="mt-2 text-sm text-slate-800">{alert.message}</p>
      {!compact && (
        <dl className="mt-2 grid grid-cols-1 gap-x-6 gap-y-1 text-xs text-slate-600 sm:grid-cols-2">
          <div>
            <dt className="inline font-medium text-slate-700">Region: </dt>
            <dd className="inline">{d?.region ?? `${alert.latitude.toFixed(2)}°, ${alert.longitude.toFixed(2)}°`}</dd>
          </div>
          {d?.driver && (
            <div>
              <dt className="inline font-medium text-slate-700">Environmental driver: </dt>
              <dd className="inline">{d.driver}</dd>
            </div>
          )}
          {d?.species && d.species.length > 0 && (
            <div className="sm:col-span-2">
              <dt className="inline font-medium text-slate-700">Species with records in the area: </dt>
              <dd className="inline">
                {d.species.slice(0, 5).map((s, i) => (
                  <span key={`${s.scientific_name}-${i}`}>
                    {i > 0 && ", "}
                    {s.aphia_id ? (
                      <Link to={`/species/${s.aphia_id}`} className="underline">
                        {s.common_name ?? s.scientific_name}
                      </Link>
                    ) : (
                      s.scientific_name
                    )}
                  </span>
                ))}
              </dd>
            </div>
          )}
          {alert.resolved_at && (
            <div>
              <dt className="inline font-medium text-slate-700">Resolved: </dt>
              <dd className="inline">{alert.resolved_at.slice(0, 16).replace("T", " ")}</dd>
            </div>
          )}
        </dl>
      )}
      {!compact && (
      <div className="mt-3 flex flex-wrap items-center gap-2">
        {d ? (
          <button
            type="button"
            aria-expanded={open}
            onClick={() => setOpen((o) => !o)}
            className="rounded-md border border-slate-300 px-2.5 py-1 text-xs font-medium text-slate-800 hover:bg-slate-50"
          >
            {open ? "Hide explanation" : "Why this alert?"}
          </button>
        ) : (
          <span className="text-xs text-slate-500">No stored explanation for this alert (created by an older batch job).</span>
        )}
        {canUpdate &&
          onStatus &&
          NEXT[alert.status].map((n) => (
            <button
              key={n.to}
              type="button"
              disabled={busy}
              onClick={() => onStatus(alert, n.to)}
              className="rounded-md bg-slate-900 px-2.5 py-1 text-xs font-medium text-white hover:bg-slate-700 disabled:opacity-50"
            >
              {n.label}
            </button>
          ))}
      </div>
      )}
      {open && d && !compact && (
        <div className="mt-3 space-y-3">
          {d.evidence_summary && d.evidence_summary.length > 0 && (
            <div>
              <div className="text-sm font-semibold text-slate-900">Evidence</div>
              <dl className="mt-1 grid grid-cols-1 gap-2 sm:grid-cols-2 lg:grid-cols-3">
                {d.evidence_summary.map((e) => (
                  <div key={e.label} className="rounded-md bg-slate-50 px-3 py-2">
                    <dt className="text-xs text-slate-600">{e.label}</dt>
                    <dd className="text-sm font-semibold text-slate-900">{e.value}</dd>
                  </div>
                ))}
              </dl>
            </div>
          )}
          <WhyPanel title="Why this alert?" reasons={d.reasons} sources={d.data_sources} classification={d.classification} recommendation={d.recommendation} />
        </div>
      )}
    </article>
  );
}
