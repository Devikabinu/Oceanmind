import { useCallback, useEffect, useState } from "react";
import type { Paginated } from "../types";
import { errorMessage } from "../utils/format";

type Fetcher<T> = (params: Record<string, string | number>) => Promise<Paginated<T>>;

/** The page/filters/loading/error state every list page repeats, in plain useState/useEffect. */
export function usePagedList<T>(fetcher: Fetcher<T>, pageSize: number) {
  const [filters, setFiltersState] = useState<Record<string, string>>({});
  const [page, setPage] = useState(1);
  const [items, setItems] = useState<T[]>([]);
  const [total, setTotal] = useState(0);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    setIsLoading(true);
    setError(null);
    fetcher({ ...filters, page, page_size: pageSize })
      .then((result) => {
        if (cancelled) return;
        setItems(result.items);
        setTotal(result.total);
      })
      .catch((err: unknown) => {
        if (cancelled) return;
        setItems([]);
        setTotal(0);
        setError(errorMessage(err));
      })
      .finally(() => {
        if (!cancelled) setIsLoading(false);
      });
    return () => {
      cancelled = true;
    };
    // fetcher is a stable module-level function
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [filters, page, pageSize]);

  const setFilters = useCallback((next: Record<string, string>) => {
    setPage(1);
    setFiltersState(next);
  }, []);

  return { items, setItems, total, page, setPage, filters, setFilters, isLoading, error };
}
