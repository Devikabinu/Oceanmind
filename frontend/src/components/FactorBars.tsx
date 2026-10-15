import type { RiskFactor } from "../api/monitor";

const LABEL: Record<RiskFactor["factor"], string> = {
  anomaly: "SST anomaly",
  persistence: "Heatwave persistence",
  forecast: "Forecast anomaly",
  overlap: "Species overlap",
};
const BAR: Record<string, string> = { LOW: "bg-green-600", MEDIUM: "bg-yellow-500", HIGH: "bg-orange-600" };

/** The individual factors behind a risk score: text label + level in words + bar length (not colour alone). */
export default function FactorBars({ factors }: { factors: RiskFactor[] }) {
  return (
    <ul className="space-y-2" aria-label="Risk factors">
      {factors.map((f) => (
        <li key={f.factor}>
          <div className="flex items-baseline justify-between text-sm">
            <span className="text-slate-800">
              {LABEL[f.factor]} <span className="text-xs text-slate-500">(weight {(f.weight * 100).toFixed(0)}%)</span>
            </span>
            <span className="font-medium text-slate-900">{f.available && f.level ? f.level : "No data"}</span>
          </div>
          <div
            className="mt-1 h-2.5 w-full rounded bg-slate-100"
            role="img"
            aria-label={`${LABEL[f.factor]}: ${f.available ? `${Math.round((f.value ?? 0) * 100)} percent` : "no data"}`}
          >
            {f.available && f.value != null && (
              <div className={`h-2.5 rounded ${BAR[f.level ?? "LOW"]}`} style={{ width: `${Math.max(3, f.value * 100)}%` }} />
            )}
          </div>
        </li>
      ))}
    </ul>
  );
}
