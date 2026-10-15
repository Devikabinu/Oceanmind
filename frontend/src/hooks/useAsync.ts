import { useEffect, useState } from "react";
import { errorMessage } from "../utils/format";

export interface AsyncState<T> {
  data: T | null;
  error: string | null;
  isLoading: boolean;
}

/** Runs `load` whenever `deps` change; ignores stale results. Keeps the previous data while reloading. */
export function useAsync<T>(load: () => Promise<T>, deps: readonly unknown[]): AsyncState<T> {
  const [state, setState] = useState<AsyncState<T>>({ data: null, error: null, isLoading: true });

  useEffect(() => {
    let cancelled = false;
    setState((s) => ({ ...s, error: null, isLoading: true }));
    load()
      .then((data) => !cancelled && setState({ data, error: null, isLoading: false }))
      .catch((err: unknown) => !cancelled && setState({ data: null, error: errorMessage(err), isLoading: false }));
    return () => {
      cancelled = true;
    };
    // `load` is rebuilt every render; callers list the values it depends on in `deps`
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, deps);

  return state;
}
