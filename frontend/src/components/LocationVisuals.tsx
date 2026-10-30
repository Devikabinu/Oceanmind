import { useId, useRef } from "react";
import type { KeyboardEvent, ReactNode } from "react";

/** Small, dependency-free building blocks of the location report: tabs, metric tiles, scale tracks and the SST trend chart. Every value shown comes from the report that is passed in. */

export interface TabDef { id: string; label: string; hint?: ReactNode }

export function Tabs({ tabs, active, onChange, label, idPrefix = "lr" }: { tabs: TabDef[]; active: string; onChange: (id: string) => void; label: string; idPrefix?: string }) {
  const refs = useRef<Record<string, HTMLButtonElement | null>>({});
  const move = (e: KeyboardEvent, i: number) => {
    const next = e.key === "ArrowRight" ? (i + 1) % tabs.length : e.key === "ArrowLeft" ? (i - 1 + tabs.length) % tabs.length : e.key === "Home" ? 0 : e.key === "End" ? tabs.length - 1 : -1;
    if (next < 0) return;
    e.preventDefault();
    onChange(tabs[next].id);
    refs.current[tabs[next].id]?.focus();
  };
  return (
    <div role="tablist" aria-label={label} className="flex shrink-0 gap-1 overflow-x-auto border-b border-slate-200 bg-white px-2 pt-1.5">
      {tabs.map((t, i) => {
        const on = t.id === active;
        return (
          <button key={t.id} ref={(el) => { refs.current[t.id] = el; }} type="button" role="tab" id={`${idPrefix}-tab-${t.id}`} aria-selected={on} aria-controls={`${idPrefix}-panel-${t.id}`} tabIndex={on ? 0 : -1}
            onClick={() => onChange(t.id)} onKeyDown={(e) => move(e, i)}
            className={`-mb-px flex shrink-0 items-center gap-1.5 whitespace-nowrap rounded-t-lg border-b-2 px-3 py-2 text-sm font-medium transition-colors ${on ? "border-lagoon bg-slate-50 text-tide" : "border-transparent text-slate-600 hover:bg-slate-50 hover:text-slate-900"}`}>
            {t.label}
            {t.hint}
          </button>
        );
      })}
    </div>
  );
}

export function TabPanel({ id, active, children, idPrefix = "lr" }: { id: string; active: string; children: ReactNode; idPrefix?: string }) {
  return (
    <div role="tabpanel" id={`${idPrefix}-panel-${id}`} aria-labelledby={`${idPrefix}-tab-${id}`} hidden={id !== active} className="space-y-4 p-4 sm:p-5">
      {children}
    </div>
  );
}

const TONES = {
  warm: "bg-orange-50 ring-orange-200 text-orange-900", cold: "bg-sky-50 ring-sky-200 text-sky-900", neutral: "bg-white ring-slate-200 text-slate-900",
  alert: "bg-red-50 ring-red-200 text-red-900", ok: "bg-emerald-50 ring-emerald-200 text-emerald-900", info: "bg-teal-50 ring-teal-200 text-teal-900",
} as const;
export type Tone = keyof typeof TONES;

export function MetricTile({ label, value, unit, sub, tone = "neutral", testId }: { label: string; value: ReactNode; unit?: string; sub?: ReactNode; tone?: Tone; testId?: string }) {
  return (
    <div className={`min-w-0 rounded-xl p-3 shadow-sm ring-1 ${TONES[tone]}`} data-testid={testId}>
      <div className="text-xs font-semibold uppercase tracking-wide opacity-75">{label}</div>
      <div className="mt-1 flex items-baseline gap-1 tabular-nums">
        <span className="text-3xl font-semibold leading-none tracking-tight">{value}</span>
        {unit && <span className="text-base font-medium opacity-80">{unit}</span>}
      </div>
      {sub && <div className="mt-1.5 text-sm leading-snug opacity-90">{sub}</div>}
    </div>
  );
}

export function Card({ title, aside, children, className = "" }: { title?: ReactNode; aside?: ReactNode; children: ReactNode; className?: string }) {
  return (
    <section className={`rounded-xl border border-slate-200 bg-white p-4 shadow-sm ${className}`}>
      {(title || aside) && (
        <div className="mb-2.5 flex flex-wrap items-center justify-between gap-2">
          {title && <h3 className="text-sm font-semibold tracking-tight text-slate-900">{title}</h3>}
          {aside}
        </div>
      )}
      {children}
    </section>
  );
}

export function Segmented<T extends string>({ options, value, onChange, label }: { options: { id: T; label: string }[]; value: T; onChange: (v: T) => void; label: string }) {
  return (
    <div role="radiogroup" aria-label={label} className="inline-flex overflow-hidden rounded-lg border border-slate-300 bg-white text-sm">
      {options.map((o) => (
        <button key={o.id} type="button" role="radio" aria-checked={o.id === value} onClick={() => onChange(o.id)}
          className={`px-3 py-1.5 font-medium ${o.id === value ? "bg-tide text-white" : "text-slate-700 hover:bg-slate-50"}`}>
          {o.label}
        </button>
      ))}
    </div>
  );
}

/** A horizontal scale with a marker: `pos` is 0..1 along the track. `ticks` are labelled positions. */
export function ScaleTrack({ pos, ticks, label, gradient }: { pos: number; ticks: { at: number; text: string }[]; label: string; gradient?: string }) {
  const p = Math.min(1, Math.max(0, pos));
  return (
    <div className="pt-5" role="img" aria-label={label}>
      <div className="relative h-3 rounded-full ring-1 ring-slate-300" style={{ background: gradient ?? "linear-gradient(90deg,#bae6fd 0%,#f1f5f9 50%,#fed7aa 100%)" }}>
        <div className="absolute -top-5 -translate-x-1/2 text-xs font-semibold text-slate-900" style={{ left: `${p * 100}%` }}>▼</div>
        <div className="absolute top-0 h-3 w-1 -translate-x-1/2 rounded bg-slate-900" style={{ left: `${p * 100}%` }} />
      </div>
      <div className="relative mt-1 h-4 text-[11px] text-slate-600">
        {ticks.map((t) => <span key={t.text} className="absolute -translate-x-1/2 whitespace-nowrap" style={{ left: `${Math.min(1, Math.max(0, t.at)) * 100}%` }}>{t.text}</span>)}
      </div>
    </div>
  );
}

export interface TrendPoint { date: string; value: number | null; lo?: number | null; hi?: number | null }

/** One line chart: the recent observed values, then the forecast with its typical-error band, and the normal as a dashed line. Gaps stay gaps. */
export function TrendChart({ observed, forecast, normal, unit, active, onActive, label, signedValues = false }: {
  observed: TrendPoint[]; forecast: TrendPoint[]; normal?: (number | null)[]; unit: string; active: number | null; onActive: (i: number | null) => void; label: string; signedValues?: boolean;
}) {
  const uid = useId().replace(/:/g, "");
  const all = [...observed, ...forecast];
  const n = all.length;
  const vals = all.flatMap((p) => [p.value, p.lo, p.hi]).concat(normal ?? []).filter((v): v is number => typeof v === "number" && Number.isFinite(v));
  if (n < 2 || vals.length < 2) return null;
  const W = 720, H = 240, L = 46, R = 14, T = 14, B = 34;
  const lo = Math.min(...vals), hi = Math.max(...vals), pad = (hi - lo || 1) * 0.12;
  const y0 = lo - pad, y1 = hi + pad;
  const x = (i: number) => L + (i * (W - L - R)) / (n - 1);
  const y = (v: number) => T + ((y1 - v) * (H - T - B)) / (y1 - y0);
  const path = (pts: (number | null)[], offset: number) => {
    const segs: string[] = []; let cur: string[] = [];
    pts.forEach((v, k) => { if (v == null) { if (cur.length) segs.push(cur.join(" ")); cur = []; } else cur.push(`${cur.length ? "L" : "M"}${x(k + offset).toFixed(1)},${y(v).toFixed(1)}`); });
    if (cur.length) segs.push(cur.join(" "));
    return segs.join(" ");
  };
  const obsPath = path(observed.map((p) => p.value), 0);
  const fcPath = path([observed[observed.length - 1]?.value ?? null, ...forecast.map((p) => p.value)], observed.length - 1);
  const band = forecast.length > 0 && forecast.every((p) => p.lo != null && p.hi != null)
    ? `M${forecast.map((p, k) => `${x(observed.length + k).toFixed(1)},${y(p.hi as number).toFixed(1)}`).join(" L")} L${[...forecast].reverse().map((p, k) => `${x(n - 1 - k).toFixed(1)},${y(p.lo as number).toFixed(1)}`).join(" L")} Z` : null;
  const normPath = normal && normal.some((v) => v != null) ? path(normal, 0) : null;
  const ticks = 4;
  const fmt = (v: number) => `${signedValues && v > 0 ? "+" : ""}${v.toFixed(1)}`;
  const split = x(Math.max(0, observed.length - 1));
  const a = active != null && active >= 0 && active < n ? all[active] : null;
  return (
    <div>
      <svg viewBox={`0 0 ${W} ${H}`} className="h-auto w-full" role="img" aria-label={label} onMouseLeave={() => onActive(null)}>
        <defs><linearGradient id={`${uid}b`} x1="0" x2="0" y1="0" y2="1"><stop offset="0" stopColor="#2563eb" stopOpacity="0.22" /><stop offset="1" stopColor="#2563eb" stopOpacity="0.08" /></linearGradient></defs>
        {Array.from({ length: ticks + 1 }, (_, k) => y0 + ((y1 - y0) * k) / ticks).map((v) => (
          <g key={v}><line x1={L} x2={W - R} y1={y(v)} y2={y(v)} stroke="#d6e4ea" strokeDasharray="3 4" /><text x={L - 6} y={y(v) + 4} textAnchor="end" fontSize="11" fill="#3d5b6d">{fmt(v)}</text></g>
        ))}
        <rect x={split} y={T} width={W - R - split} height={H - T - B} fill="#eff6ff" opacity="0.55" />
        <line x1={split} x2={split} y1={T} y2={H - B} stroke="#64748b" strokeDasharray="4 3" />
        <text x={split - 6} y={T + 11} textAnchor="end" fontSize="11" fontWeight="600" fill="#3d5b6d">observed</text>
        <text x={split + 6} y={T + 11} fontSize="11" fontWeight="600" fill="#1d4ed8">ConvLSTM forecast</text>
        {band && <path d={band} fill={`url(#${uid}b)`} />}
        {normPath && <path d={normPath} fill="none" stroke="#64748b" strokeWidth="1.5" strokeDasharray="5 4" />}
        <path d={obsPath} fill="none" stroke="#0f766e" strokeWidth="2.5" strokeLinejoin="round" />
        <path d={fcPath} fill="none" stroke="#2563eb" strokeWidth="2.5" strokeLinejoin="round" />
        {all.map((p, i) => p.value == null ? null : (
          <circle key={`${p.date}-${i}`} cx={x(i)} cy={y(p.value)} r={active === i ? 6 : 3.5} fill={i < observed.length ? "#0f766e" : "#2563eb"} stroke="#fff" strokeWidth="1.5" />
        ))}
        {all.map((p, i) => (
          <rect key={`h-${p.date}-${i}`} x={x(i) - (W - L - R) / (n - 1) / 2} y={T} width={(W - L - R) / (n - 1)} height={H - T - B} fill="transparent" onMouseEnter={() => onActive(i)} />
        ))}
        {all.map((p, i) => (i % Math.ceil(n / 8) === 0 || i === n - 1) ? <text key={`t-${p.date}-${i}`} x={x(i)} y={H - 14} textAnchor="middle" fontSize="11" fill="#3d5b6d">{p.date.slice(5)}</text> : null)}
        <text x={L} y={H - 1} fontSize="11" fill="#4a6a7f">{unit}</text>
      </svg>
      <div className="mt-1 flex flex-wrap items-center gap-x-4 gap-y-1 text-xs text-slate-600">
        <span className="inline-flex items-center gap-1"><span className="inline-block h-0.5 w-5 bg-teal-700" />observed</span>
        <span className="inline-flex items-center gap-1"><span className="inline-block h-0.5 w-5 bg-blue-600" />forecast</span>
        {band && <span className="inline-flex items-center gap-1"><span className="inline-block h-2.5 w-5 rounded-sm bg-blue-200" />typical forecast error</span>}
        {normPath && <span className="inline-flex items-center gap-1"><span className="inline-block h-0 w-5 border-t-2 border-dashed border-slate-500" />normal for the date</span>}
        <span className="ml-auto min-h-[1.25rem] font-medium text-slate-900" aria-live="polite">{a && a.value != null ? `${a.date}: ${fmt(a.value)} ${unit}${a.lo != null && a.hi != null ? ` (typical error ${fmt(a.lo)} to ${fmt(a.hi)})` : ""}` : "Hover or tap a day for its value"}</span>
      </div>
    </div>
  );
}

const CATS = [{ n: "I", name: "Moderate" }, { n: "II", name: "Strong" }, { n: "III", name: "Severe" }, { n: "IV", name: "Extreme" }];
const CAT_TONE = ["bg-yellow-200 text-yellow-950", "bg-orange-300 text-orange-950", "bg-red-400 text-red-950", "bg-rose-700 text-white"];

/** The four marine-heatwave categories with the current one highlighted. */
export function CategoryScale({ category }: { category: string | null | undefined }) {
  const m = /^(IV|III|II|I)\b/.exec(category ?? "");
  const idx = m ? CATS.findIndex((c) => c.n === m[1]) : -1;
  return (
    <ol className="grid grid-cols-4 gap-1.5" aria-label="Marine heatwave category scale">
      {CATS.map((c, i) => (
        <li key={c.n} aria-current={i === idx ? "true" : undefined} className={`rounded-lg px-2 py-1.5 text-center text-xs font-semibold ${i === idx ? `${CAT_TONE[i]} ring-2 ring-slate-900` : "bg-slate-100 text-slate-500"}`}>
          <div className="text-base leading-none">{c.n}</div>{c.name}
        </li>
      ))}
    </ol>
  );
}

export function BarMeter({ value, max, label, display, tone = "bg-lagoon", mark }: { value: number; max: number; label: string; display: string; tone?: string; mark?: { at: number; text: string } }) {
  const pct = Math.min(100, Math.max(2, (value / max) * 100));
  return (
    <div>
      <div className="flex items-baseline justify-between gap-2 text-sm"><span className="text-slate-600">{label}</span><span className="font-semibold tabular-nums text-slate-900">{display}</span></div>
      <div className="relative mt-1 h-2.5 rounded-full bg-slate-100" role="img" aria-label={`${label}: ${display}`}>
        <div className={`h-2.5 rounded-full ${tone}`} style={{ width: `${pct}%` }} />
        {mark && <div className="absolute -top-1 h-4 w-px bg-slate-700" style={{ left: `${Math.min(100, (mark.at / max) * 100)}%` }} title={mark.text} />}
      </div>
      {mark && <div className="mt-0.5 text-[11px] text-slate-500">| {mark.text}</div>}
    </div>
  );
}
