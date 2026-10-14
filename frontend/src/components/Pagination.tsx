interface PaginationProps {
  page: number;
  pageSize: number;
  total: number;
  /** While true the count is replaced by a loading indicator, so old totals never sit next to new rows. */
  isLoading: boolean;
  onPageChange: (page: number) => void;
}

export default function Pagination({ page, pageSize, total, isLoading, onPageChange }: PaginationProps) {
  const totalPages = Math.max(1, Math.ceil(total / pageSize));
  return (
    <div className="mt-4 flex items-center justify-between text-sm text-slate-500">
      <span>{isLoading ? "Loading..." : `Page ${page} of ${totalPages} (${total} total)`}</span>
      <div className="flex gap-2">
        <button
          disabled={isLoading || page <= 1}
          onClick={() => onPageChange(page - 1)}
          className="rounded-md border border-slate-300 px-3 py-1 disabled:opacity-40"
        >
          Previous
        </button>
        <button
          disabled={isLoading || page >= totalPages}
          onClick={() => onPageChange(page + 1)}
          className="rounded-md border border-slate-300 px-3 py-1 disabled:opacity-40"
        >
          Next
        </button>
      </div>
    </div>
  );
}
