import type { ReactNode } from "react";

/** An empty result that explains why, what coverage exists and what to try, instead of a bare "no results". */
export default function EmptyState({ title, children, action }: { title: string; children?: ReactNode; action?: ReactNode }) {
  return (
    <div className="rounded-lg border border-dashed border-slate-300 bg-slate-50/70 p-5 text-sm text-slate-700">
      <div className="font-semibold text-slate-900">{title}</div>
      {children && <div className="mt-1 space-y-1 text-slate-600">{children}</div>}
      {action && <div className="mt-3">{action}</div>}
    </div>
  );
}
