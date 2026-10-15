import type { ReactNode } from "react";

export interface Column<T> {
  header: string;
  cell: (row: T) => ReactNode;
}

interface DataTableProps<T> {
  columns: Column<T>[];
  rows: T[];
  rowKey: (row: T) => string;
  isLoading: boolean;
  error?: string | null;
  emptyMessage: string;
  rowClassName?: (row: T) => string;
}

export default function DataTable<T>({
  columns,
  rows,
  rowKey,
  isLoading,
  error,
  emptyMessage,
  rowClassName,
}: DataTableProps<T>) {
  const message = isLoading ? "Loading…" : error ? `Data unavailable: ${error}` : rows.length === 0 ? emptyMessage : null;
  return (
    <div className="mt-4 overflow-x-auto rounded-lg border border-slate-200 bg-white">
      <table className="min-w-full divide-y divide-slate-200 text-sm">
        <thead className="bg-slate-50 text-left text-xs font-medium uppercase tracking-wide text-slate-500">
          <tr>
            {columns.map((c) => (
              <th key={c.header} className="px-4 py-2">
                {c.header}
              </th>
            ))}
          </tr>
        </thead>
        <tbody className="divide-y divide-slate-100">
          {message ? (
            <tr>
              <td
                colSpan={columns.length}
                className={`px-4 py-6 text-center ${error && !isLoading ? "text-amber-800" : "text-slate-600"}`}
              >
                {message}
              </td>
            </tr>
          ) : (
            rows.map((row) => (
              <tr key={rowKey(row)} className={rowClassName?.(row)}>
                {columns.map((c) => (
                  <td key={c.header} className="px-4 py-2 text-slate-600">
                    {c.cell(row)}
                  </td>
                ))}
              </tr>
            ))
          )}
        </tbody>
      </table>
    </div>
  );
}
