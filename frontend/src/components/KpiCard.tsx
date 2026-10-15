import { Link } from "react-router-dom";
import type { ReactNode } from "react";
import SourceTag from "./SourceTag";
import type { DataKind } from "./SourceTag";

interface Props {
  label: ReactNode;
  value: string;
  hint: string;
  tag: DataKind;
  to?: string;
  tone?: "default" | "warn";
}

/** One headline number with its meaning, provenance tag and an optional link to the detail page. */
export default function KpiCard({ label, value, hint, tag, to, tone = "default" }: Props) {
  const body = (
    <div
      className={`h-full rounded-lg border bg-white p-4 transition-colors hover:border-slate-400 ${tone === "warn" ? "border-orange-300" : "border-slate-200"}`}
    >
      <div className="flex items-start justify-between gap-2">
        <div className="text-xs font-medium uppercase tracking-wide text-slate-600">{label}</div>
        <SourceTag kind={tag} />
      </div>
      <div className="mt-1 text-2xl font-semibold text-slate-900">{value}</div>
      <div className="mt-1 text-xs text-slate-600">{hint}</div>
    </div>
  );
  return to ? (
    <Link to={to} className="block rounded-lg">
      {body}
    </Link>
  ) : (
    body
  );
}
