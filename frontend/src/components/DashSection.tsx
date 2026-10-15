import type { ReactNode } from "react";
import { Link } from "react-router-dom";
import SourceTag from "./SourceTag";
import type { DataKind } from "./SourceTag";

/** A labelled group of related metrics on the dashboard that links to its detail page. */
export default function DashSection({
  title,
  to,
  linkLabel,
  tag,
  children,
}: {
  title: string;
  to: string;
  linkLabel: string;
  tag?: DataKind;
  children: ReactNode;
}) {
  return (
    <section className="flex flex-col rounded-lg border border-slate-200 bg-white p-4" aria-label={title}>
      <div className="flex items-center justify-between gap-2">
        <h2 className="text-sm font-semibold uppercase tracking-wide text-slate-700">{title}</h2>
        {tag && <SourceTag kind={tag} />}
      </div>
      <div className="mt-3 flex-1 space-y-3">{children}</div>
      <Link to={to} className="mt-3 text-sm font-medium text-slate-800 underline">
        {linkLabel} →
      </Link>
    </section>
  );
}

/** One metric: title, value + unit, short explanation, optional date/source line. */
export function Metric({ label, value, note, meta }: { label: ReactNode; value: string; note?: string; meta?: string }) {
  return (
    <div>
      <div className="text-xs font-medium text-slate-600">{label}</div>
      <div className="text-2xl font-semibold leading-tight text-slate-900">{value}</div>
      {note && <div className="text-xs text-slate-700">{note}</div>}
      {meta && <div className="text-xs text-slate-500">{meta}</div>}
    </div>
  );
}
