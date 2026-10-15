import type { ReactNode } from "react";

export default function PageHeader({ title, children, actions }: { title: string; children?: ReactNode; actions?: ReactNode }) {
  return (
    <div className="flex flex-wrap items-end justify-between gap-3">
      <div className="max-w-3xl">
        <h1 className="text-xl font-semibold text-slate-900">{title}</h1>
        {children && <p className="mt-1 text-sm text-slate-600">{children}</p>}
      </div>
      {actions}
    </div>
  );
}
