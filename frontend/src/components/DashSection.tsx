import type { ReactNode } from "react";
import { Link } from "react-router-dom";
import SourceTag from "./SourceTag";
import type { DataKind } from "./SourceTag";

/** A group of related metrics on the dashboard that links to its detail page. A light panel with a marine header rule rather than a boxed white card. */
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
    <section className="flex flex-col rounded-lg bg-white/70 p-4 ring-1 ring-slate-200" aria-label={title}>
      <div className="flex items-center justify-between gap-2 border-b-2 border-lagoon/60 pb-2">
        <h2 className="text-sm font-semibold uppercase tracking-[0.1em] text-slate-800">{title}</h2>
        {tag && <SourceTag kind={tag} />}
      </div>
      <div className="mt-3 flex-1 space-y-3">{children}</div>
      <Link to={to} className="mt-3 text-sm font-semibold text-tide hover:underline">
        {linkLabel} →
      </Link>
    </section>
  );
}

/** One metric: title, value + unit, short explanation, optional date/source line. */
export function Metric({ label, value, note, meta }: { label: ReactNode; value: string; note?: string; meta?: string }) {
  return (
    <div>
      <div className="text-xs font-semibold uppercase tracking-wide text-slate-600">{label}</div>
      <div className="text-3xl font-semibold leading-tight tracking-tight text-slate-900">{value}</div>
      {note && <div className="mt-0.5 text-sm text-slate-700">{note}</div>}
      {meta && <div className="mt-0.5 text-xs text-slate-500">{meta}</div>}
    </div>
  );
}
