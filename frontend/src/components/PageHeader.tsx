import type { ReactNode } from "react";

/** Page title block: a marine accent rule, the title, and one short explanatory paragraph. */
export default function PageHeader({ title, children, actions }: { title: string; children?: ReactNode; actions?: ReactNode }) {
  return (
    <div className="flex flex-wrap items-end justify-between gap-3 border-l-4 border-lagoon pl-4">
      <div className="max-w-3xl">
        <h1 className="text-2xl font-semibold tracking-tight text-slate-900">{title}</h1>
        {children && <p className="mt-1 text-sm leading-relaxed text-slate-600">{children}</p>}
      </div>
      {actions}
    </div>
  );
}
