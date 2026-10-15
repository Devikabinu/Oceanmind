import { getOverview } from "../api/monitor";
import type { Overview } from "../api/monitor";
import { useAsync } from "./useAsync";

const TTL_MS = 60_000;
const store = new Map<string, { at: number; value: Promise<unknown> }>();

/** De-duplicates identical requests made by several components within a minute (e.g. the overview). */
export function cached<T>(key: string, load: () => Promise<T>): Promise<T> {
  const hit = store.get(key);
  if (hit && Date.now() - hit.at < TTL_MS) return hit.value as Promise<T>;
  const value = load();
  store.set(key, { at: Date.now(), value });
  value.catch(() => store.delete(key)); // never cache a failure
  return value;
}

export function useOverview() {
  return useAsync<Overview>(() => cached("overview", getOverview), []);
}
