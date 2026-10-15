import type { ReactNode } from "react";

interface Props {
  isLoading: boolean;
  error: string | null;
  hasData: boolean;
  /** Shown when the request succeeded but there is nothing to show: say why and how to get data. */
  emptyMessage?: string;
  children: ReactNode;
}

/**
 * The four states of every data panel, kept visually distinct:
 *   LOADING          - request in flight
 *   DATA UNAVAILABLE - request failed (backend, source or session problem)
 *   NO DATA          - request succeeded but nothing exists for this view
 *   SUCCESS          - children
 */
export default function Status({ isLoading, error, hasData, emptyMessage = "No data is available for this view.", children }: Props) {
  if (!hasData && isLoading) {
    return (
      <div role="status" aria-live="polite" className="rounded-lg border border-slate-200 bg-white p-6 text-sm text-slate-600">
        Loading data…
      </div>
    );
  }
  if (error && !hasData) {
    return (
      <div role="alert" className="rounded-lg border border-amber-300 bg-amber-50 p-4 text-sm text-amber-900">
        <div className="font-semibold">Data unavailable</div>
        <div className="mt-0.5">{error}</div>
        <div className="mt-1 text-xs text-amber-800">This is a loading problem, not an empty result. Reload the page; if it continues, check that the backend is running.</div>
      </div>
    );
  }
  if (!hasData) {
    return (
      <div className="rounded-lg border border-dashed border-slate-300 bg-white p-6 text-sm text-slate-700">
        <div className="font-medium text-slate-900">No data available</div>
        <div className="mt-0.5">{emptyMessage}</div>
      </div>
    );
  }
  return <>{children}</>;
}
