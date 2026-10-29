import { createContext, useCallback, useContext, useEffect, useMemo, useState } from "react";
import type { ReactNode } from "react";
import { useLocation } from "react-router-dom";

export const DEFAULT_DATASET = "pacific";
export const DEFAULT_REGION = "pacific";

interface ActiveSelection {
  /** Backend dataset id of every dataset-aware page (pacific by default). */
  dataset: string;
  /** Region id from /api/environment/regions. */
  region: string;
  /** YYYY-MM-DD, or null for the dataset's latest date. */
  date: string | null;
  setDataset: (d: string) => void;
  setRegion: (r: string) => void;
  setDate: (d: string | null) => void;
  /** The place picked on the Ocean Map (latitude, longitude in -180..180), shared with the dashboard's historical SST graph; null = the whole region. */
  point: { lat: number; lon: number } | null;
  setPoint: (p: { lat: number; lon: number } | null) => void;
  /** Query string that carries this selection to another page (and optional extras). */
  toQuery: (extra?: Record<string, string | number | undefined>) => string;
}

const Ctx = createContext<ActiveSelection | undefined>(undefined);

/** One dataset / region / date shared by the Ocean Map, Dashboard, Ecological Risk, Marine Heatwaves, Alerts, Forecast and Species pages, so moving between
 *  related pages never changes what is being looked at. Links may also set it with ?dataset=&region=&date=. */
export function ActiveSelectionProvider({ children }: { children: ReactNode }) {
  const [dataset, setDatasetState] = useState(DEFAULT_DATASET);
  const [region, setRegion] = useState(DEFAULT_REGION);
  const [date, setDate] = useState<string | null>(null);
  const [point, setPoint] = useState<{ lat: number; lon: number } | null>(null);
  const { search } = useLocation();

  // apply selection carried by a link
  useEffect(() => {
    const p = new URLSearchParams(search);
    const d = p.get("dataset");
    if (d) {
      setDatasetState(d);
      if (!p.get("date")) setDate(null);
    }
    const r = p.get("region");
    if (r) setRegion(r);
    const dt = p.get("date");
    if (dt) setDate(dt);
    const la = p.get("lat");
    const lo = p.get("lon");
    if (la !== null && lo !== null && la !== "" && lo !== "" && Number.isFinite(Number(la)) && Number.isFinite(Number(lo))) setPoint({ lat: Number(la), lon: Number(lo) });
  }, [search]);

  const setDataset = useCallback((d: string) => {
    setDatasetState(d);
    setDate(null); // every dataset has its own date range
    setPoint(null);
  }, []);

  const toQuery = useCallback(
    (extra: Record<string, string | number | undefined> = {}) => {
      const q = new URLSearchParams({ dataset, region });
      if (date) q.set("date", date);
      if (point) {
        q.set("lat", String(Math.round(point.lat * 1000) / 1000));
        q.set("lon", String(Math.round(point.lon * 1000) / 1000));
      }
      for (const [k, v] of Object.entries(extra)) if (v !== undefined) q.set(k, String(v));
      return `?${q.toString()}`;
    },
    [dataset, region, date, point],
  );

  const value = useMemo(() => ({ dataset, region, date, point, setPoint, setDataset, setRegion, setDate, toQuery }), [dataset, region, date, point, setDataset, toQuery]);
  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}

export function useActive(): ActiveSelection {
  const v = useContext(Ctx);
  if (!v) throw new Error("useActive must be used inside ActiveSelectionProvider");
  return v;
}
