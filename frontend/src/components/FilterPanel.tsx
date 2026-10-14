import { useState } from "react";

export interface FilterField {
  name: string;
  label: string;
  type: "date" | "number" | "select";
  options?: { value: string; label: string }[];
  min?: number;
  max?: number;
}

interface FilterPanelProps {
  fields: FilterField[];
  onApply: (values: Record<string, string>) => void;
}

const PAIRS: [string, string, string][] = [
  ["start_date", "end_date", "'From' must not be after 'To'"],
  ["min_latitude", "max_latitude", "Min lat must not exceed max lat"],
  ["min_longitude", "max_longitude", "Min lon must not exceed max lon"],
];

function validate(values: Record<string, string>, fields: FilterField[]): string | null {
  for (const f of fields) {
    const v = values[f.name];
    if (f.type !== "number" || v === "") continue;
    const n = Number(v);
    if (Number.isNaN(n) || (f.min !== undefined && n < f.min) || (f.max !== undefined && n > f.max)) {
      return `${f.label} must be between ${f.min} and ${f.max}`;
    }
  }
  for (const [lo, hi, msg] of PAIRS) {
    const a = values[lo];
    const b = values[hi];
    if (!a || !b) continue;
    const bad = lo === "start_date" ? a > b : Number(a) > Number(b);
    if (bad) return msg;
  }
  return null;
}

/** Draft-then-apply filter form, so the table is queried once per Apply rather than per keystroke. */
export default function FilterPanel({ fields, onApply }: FilterPanelProps) {
  const empty = Object.fromEntries(fields.map((f) => [f.name, ""]));
  const [draft, setDraft] = useState<Record<string, string>>(empty);
  const [error, setError] = useState<string | null>(null);

  function apply() {
    const problem = validate(draft, fields);
    setError(problem);
    if (!problem) onApply(draft);
  }

  function reset() {
    setDraft(empty);
    setError(null);
    onApply(empty);
  }

  const inputClass = "mt-1 w-full rounded-md border border-slate-300 bg-white px-2 py-1.5 text-sm";

  return (
    <form
      onSubmit={(e) => {
        e.preventDefault();
        apply();
      }}
      className="mt-6 rounded-lg border border-slate-200 bg-white p-4"
    >
      <div className="grid grid-cols-2 gap-3 sm:grid-cols-4 lg:grid-cols-6">
        {fields.map((f) => (
          <label key={f.name} className="text-xs font-medium text-slate-500">
            {f.label}
            {f.type === "select" ? (
              <select
                aria-label={f.label}
                value={draft[f.name]}
                onChange={(e) => setDraft({ ...draft, [f.name]: e.target.value })}
                className={inputClass}
              >
                <option value="">All</option>
                {f.options?.map((o) => (
                  <option key={o.value} value={o.value}>
                    {o.label}
                  </option>
                ))}
              </select>
            ) : (
              <input
                aria-label={f.label}
                type={f.type}
                step={f.type === "number" ? "any" : undefined}
                min={f.type === "number" ? f.min : undefined}
                max={f.type === "number" ? f.max : undefined}
                value={draft[f.name]}
                onChange={(e) => setDraft({ ...draft, [f.name]: e.target.value })}
                className={inputClass}
              />
            )}
          </label>
        ))}
      </div>
      <div className="mt-3 flex items-center gap-2">
        <button
          type="submit"
          className="rounded-md bg-slate-900 px-3 py-1.5 text-sm font-medium text-white hover:bg-slate-800"
        >
          Apply filters
        </button>
        <button
          type="button"
          onClick={reset}
          className="rounded-md border border-slate-300 px-3 py-1.5 text-sm font-medium text-slate-700 hover:bg-slate-50"
        >
          Reset
        </button>
        {error && <span className="text-sm text-red-600">{error}</span>}
      </div>
    </form>
  );
}
