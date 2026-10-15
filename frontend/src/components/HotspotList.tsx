import type { Hotspot, Severity } from "../api/monitor";
import Badge from "./Badge";
import { LEVEL_TONE } from "../utils/tones";

const BAR: Record<Severity, string> = { MEDIUM: "bg-yellow-400", HIGH: "bg-orange-500", CRITICAL: "bg-red-600" };

function place(h: Hotspot): string {
  return `${h.lat.toFixed(1)}°N, ${Math.abs(h.lon).toFixed(1)}°W`;
}

/** Ranked list of anomalous 2°x2° blocks from the forecast. */
export default function HotspotList({ items, limit }: { items: Hotspot[]; limit?: number }) {
  const rows = limit ? items.slice(0, limit) : items;
  if (rows.length === 0) {
    return <p className="text-sm text-slate-500">No areas exceed the selected threshold.</p>;
  }
  return (
    <ul className="divide-y divide-slate-100">
      {rows.map((h) => (
        <li key={`${h.lat}-${h.lon}`} className="flex items-center gap-3 py-2">
          <span className={`h-8 w-1.5 shrink-0 rounded ${BAR[h.severity]}`} />
          <div className="min-w-0 flex-1">
            <div className="text-sm font-medium text-slate-900">{place(h)}</div>
            <div className="text-xs text-slate-500">
              {h.direction === "warm" ? "Warmer" : "Colder"} than normal · peak {h.max_anomaly > 0 ? "+" : ""}
              {h.max_anomaly.toFixed(2)} °C · {h.date}
            </div>
          </div>
          <div className="text-right">
            <div className="text-sm font-semibold text-slate-900">
              {h.mean_anomaly > 0 ? "+" : ""}
              {h.mean_anomaly.toFixed(2)} °C
            </div>
            <Badge tone={LEVEL_TONE[h.severity]}>{h.severity}</Badge>
          </div>
        </li>
      ))}
    </ul>
  );
}
