import { useEffect, useMemo, useRef, useState } from "react";
import type { ReactNode } from "react";
import L from "leaflet";
import "leaflet/dist/leaflet.css";
import type { HeatwaveEvent, Hotspot, MapLayer, Severity } from "../api/monitor";
import { cssGradient, makeScale } from "../utils/colormap";
import { shiftGeoJson, toAxisLon } from "../utils/mapCoords";

const SEVERITY_COLOR: Record<Severity, string> = { MEDIUM: "#ca8a04", HIGH: "#ea580c", CRITICAL: "#b91c1c" };

/** A clickable marker (species point, alert...) drawn on top of the grid. lon is on the same axis as `lonOrigin` data or plain -180..180. */
export interface MapMarker {
  key: string;
  lat: number;
  lon: number;
  color: string;
  radius?: number;
  /** Dark outer ring: e.g. the marker is inside a current marine heatwave. */
  ring?: boolean;
  label: string;
  onClick?: () => void;
}

export interface MapObservation {
  lat: number;
  lon: number;
  label: string;
}

interface Props {
  layer: MapLayer | null;
  hotspots?: Hotspot[];
  events?: HeatwaveEvent[];
  observations?: MapObservation[];
  distribution?: GeoJSON.FeatureCollection | null;
  alertMarkers?: { lat: number; lon: number; label: string }[];
  selected?: { lat: number; lon: number } | null;
  onPick?: (lat: number, lon: number) => void;
  onEventClick?: (id: string) => void;
  /** Fly to these bounds ([[south, west], [north, east]]) whenever the value changes. */
  fitTo?: [[number, number], [number, number]] | null;
  initialView?: "study" | "world";
  /** Start of the continuous longitude axis of `layer` (e.g. 100 for the Pacific). When set, points given in -180..180 are drawn on that axis. */
  lonOrigin?: number | null;
  /** Text for the data-coverage outline and legend; defaults to the NE Pacific wording. */
  coverageLabel?: string;
  /** The request for `layer` failed: say so instead of "Loading". */
  unavailable?: boolean;
  /** Per-cell state codes aligned with layer.values (row 0 = southernmost). Cells without a value are painted with statusColors[code] instead of left empty. */
  status?: number[][] | null;
  statusColors?: Record<number, [number, number, number, number]>;
  statusLabels?: Record<number, string>;
  /** Extra legend content (state swatches). */
  legendExtra?: ReactNode;
  markers?: MapMarker[];
  /** A second grid drawn over the base layer as footprints (filled with a darker rim where the area ends), e.g. active marine-heatwave cells. */
  overlay?: MapLayer | null;
  /** Fade the outermost n cells of the grid so the end of the data does not show as a hard rectangle. */
  edgeFade?: number;
  /** Draw the dashed data-coverage outline (useful for a small study region; hidden for the Pacific-wide dataset). */
  showOutline?: boolean;
  /** Small context chip at the top right of the map (region, date, data state). */
  badge?: string;
  heightClass?: string;
  ariaLabel?: string;
}

function valueAt(layer: MapLayer, lat: number, lon: number): number | null {
  const dLat = layer.lat[1] - layer.lat[0];
  const dLon = layer.lon[1] - layer.lon[0];
  const i = Math.round((lat - layer.lat[0]) / dLat);
  const j = Math.round((lon - layer.lon[0]) / dLon);
  return layer.values[i]?.[j] ?? null;
}

function inside(layer: MapLayer, lat: number, lon: number): boolean {
  const c = layer.coverage;
  return lat >= c.lat_min && lat <= c.lat_max && lon >= c.lon_min && lon <= c.lon_max;
}

const legendUnit = (l: MapLayer) => (l.unit === "degC" ? (l.diverging ? "°C from baseline (expected value)" : "°C") : l.unit);
const wrapLon = (lng: number) => ((((lng + 180) % 360) + 360) % 360) - 180;

/** Leaflet map: model grid as a pixel-exact canvas overlay, an explicit data-coverage outline, and optional
 *  hotspot / heatwave rectangles, species observation points and a gridded OBIS distribution. */
export default function SstMap({
  layer,
  hotspots,
  events,
  observations,
  distribution,
  alertMarkers,
  selected,
  onPick,
  onEventClick,
  fitTo,
  initialView = "study",
  lonOrigin = null,
  coverageLabel = "study region only",
  unavailable = false,
  status = null,
  statusColors,
  statusLabels,
  legendExtra,
  markers,
  overlay = null,
  edgeFade = 0,
  showOutline = true,
  badge,
  heightClass = "h-[28rem]",
  ariaLabel = "Interactive ocean map",
}: Props) {
  const host = useRef<HTMLDivElement>(null);
  const mapRef = useRef<L.Map | null>(null);
  const overlayRef = useRef<L.ImageOverlay | null>(null);
  const coverageRef = useRef<L.Rectangle | null>(null);
  const vectorGroup = useRef<L.LayerGroup | null>(null);
  const obsGroup = useRef<L.LayerGroup | null>(null);
  const distGroup = useRef<L.LayerGroup | null>(null);
  const alertGroup = useRef<L.LayerGroup | null>(null);
  const markerGroup = useRef<L.LayerGroup | null>(null);
  const footRef = useRef<L.ImageOverlay | null>(null);
  const markerRef = useRef<L.CircleMarker | null>(null);
  const pickRef = useRef(onPick);
  const eventRef = useRef(onEventClick);
  const layerRef = useRef(layer);
  const statusRef = useRef({ status, statusLabels });
  const originRef = useRef(lonOrigin);
  const didFit = useRef(false);
  const [hover, setHover] = useState<string | null>(null);

  useEffect(() => {
    pickRef.current = onPick;
    eventRef.current = onEventClick;
    layerRef.current = layer;
    statusRef.current = { status, statusLabels };
    originRef.current = lonOrigin;
  });
  const onAxis = (lon: number) => (lonOrigin == null ? lon : toAxisLon(lon, lonOrigin));

  const scale = useMemo(() => {
    if (!layer || layer.min == null || layer.max == null) return null;
    return makeScale(layer.min, layer.max, layer.diverging);
  }, [layer]);

  useEffect(() => {
    if (!host.current) return;
    const world = initialView === "world";
    const map = L.map(host.current, {
      center: world ? [20, -150] : [35, -140],
      zoom: world ? 2 : 4,
      zoomSnap: 0.25,
      zoomDelta: 0.5,
      minZoom: 1,   // a phone-width map needs zoom 1 to show the whole Pacific
      maxZoom: 9,
      worldCopyJump: true,
      scrollWheelZoom: false, // opt-in: otherwise scrolling the page while the pointer is over the map zooms the map
    });
    // Basemap tiles need internet; if they fail the data grid still draws on the plain blue background.
    L.tileLayer("https://tile.openstreetmap.org/{z}/{x}/{y}.png", {
      attribution: "&copy; OpenStreetMap contributors",
      maxZoom: 19,
    }).addTo(map);
    vectorGroup.current = L.layerGroup().addTo(map);
    distGroup.current = L.layerGroup().addTo(map);
    obsGroup.current = L.layerGroup().addTo(map);
    alertGroup.current = L.layerGroup().addTo(map);
    markerGroup.current = L.layerGroup().addTo(map);
    map.on("click", (e: L.LeafletMouseEvent) => {
      map.scrollWheelZoom.enable();
      pickRef.current?.(e.latlng.lat, wrapLon(e.latlng.lng));
    });
    map.on("mousemove", (e: L.LeafletMouseEvent) => {
      const l = layerRef.current;
      if (!l) return;
      const o = originRef.current;
      const lon = o == null ? wrapLon(e.latlng.lng) : toAxisLon(e.latlng.lng, o);
      const where = `${e.latlng.lat.toFixed(2)}°, ${wrapLon(lon).toFixed(2)}°`;
      if (!inside(l, e.latlng.lat, lon)) {
        setHover(`${where} · outside data coverage`);
        return;
      }
      const v = valueAt(l, e.latlng.lat, lon);
      const sg = statusRef.current;
      const code = sg.status ? sg.status[Math.round((e.latlng.lat - l.lat[0]) / (l.lat[1] - l.lat[0]))]?.[Math.round((lon - l.lon[0]) / (l.lon[1] - l.lon[0]))] : undefined;
      setHover(v == null ? `${where} · ${code != null && sg.statusLabels?.[code] ? sg.statusLabels[code] : "no data (land, missing, or outside the selected area)"}` : `${where} · ${l.diverging && v > 0 ? "+" : ""}${v.toFixed(2)} ${l.unit}`);
    });
    map.on("mouseout", () => {
      setHover(null);
      map.scrollWheelZoom.disable();
    });
    mapRef.current = map;
    return () => {
      map.remove();
      mapRef.current = null;
      overlayRef.current = null;
      coverageRef.current = null;
      vectorGroup.current = null;
      obsGroup.current = null;
      distGroup.current = null;
      alertGroup.current = null;
      markerGroup.current = null;
      footRef.current = null;
      markerRef.current = null;
    };
  }, [initialView]);

  // grid overlay + coverage outline
  useEffect(() => {
    const map = mapRef.current;
    if (!map) return;
    if (!layer || !scale) {
      // never leave the previous layer on screen while another one loads or after a failed request
      overlayRef.current?.remove();
      overlayRef.current = null;
      return;
    }
    const H = layer.lat.length;
    const W = layer.lon.length;
    const canvas = document.createElement("canvas");
    canvas.width = W;
    canvas.height = H;
    const ctx = canvas.getContext("2d");
    if (!ctx) return;
    const img = ctx.createImageData(W, H);
    for (let i = 0; i < H; i++) {
      const row = layer.values[H - 1 - i]; // canvas row 0 = northernmost latitude
      for (let j = 0; j < W; j++) {
        const v = row[j];
        const o = (i * W + j) * 4;
        if (v == null) {
          const code = status?.[H - 1 - i]?.[j];
          const c = code == null ? undefined : statusColors?.[code];
          if (c) {
            img.data[o] = c[0];
            img.data[o + 1] = c[1];
            img.data[o + 2] = c[2];
            img.data[o + 3] = c[3];
          }
          continue; // land / missing without a state colour stays transparent
        }
        const [r, g, b] = scale.color(v);
        img.data[o] = r;
        img.data[o + 1] = g;
        img.data[o + 2] = b;
        img.data[o + 3] = 215;
        if (edgeFade > 0) {
          const d = Math.min(i, H - 1 - i, j, W - 1 - j);
          if (d < edgeFade) img.data[o + 3] = Math.round(215 * ((d + 1) / (edgeFade + 1)));
        }
      }
    }
    ctx.putImageData(img, 0, 0);
    const dLat = layer.lat[1] - layer.lat[0];
    const dLon = layer.lon[1] - layer.lon[0];
    const bounds = L.latLngBounds(
      [layer.lat[0] - dLat / 2, layer.lon[0] - dLon / 2],
      [layer.lat[H - 1] + dLat / 2, layer.lon[W - 1] + dLon / 2],
    );
    const url = canvas.toDataURL();
    if (overlayRef.current) {
      overlayRef.current.setUrl(url);
      overlayRef.current.setBounds(bounds);
    } else {
      overlayRef.current = L.imageOverlay(url, bounds, { opacity: 1, className: "sst-overlay" }).addTo(map);
      if (initialView === "study" && !didFit.current) map.fitBounds(bounds);
      didFit.current = true;
    }
    if (!showOutline) {
      coverageRef.current?.remove();
      coverageRef.current = null;
    } else {
      if (!coverageRef.current) {
        coverageRef.current = L.rectangle(bounds, { color: "#0e5a73", weight: 1.5, dashArray: "6 5", fill: false, interactive: false }).addTo(map);
      } else {
        coverageRef.current.setBounds(bounds);
      }
      coverageRef.current.unbindTooltip().bindTooltip(`Data coverage: ${coverageLabel}`, { sticky: true });
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [layer, scale, initialView, coverageLabel, showOutline, status, statusColors, edgeFade]);

  // fly to requested bounds
  useEffect(() => {
    if (mapRef.current && fitTo) mapRef.current.fitBounds(fitTo, { maxZoom: 7, padding: [8, 8] });
  }, [fitTo]);

  // hotspot + heatwave rectangles
  useEffect(() => {
    const group = vectorGroup.current;
    if (!group) return;
    group.clearLayers();
    for (const h of hotspots ?? []) {
      L.rectangle(
        [
          [h.lat_min, h.lon_min],
          [h.lat_max, h.lon_max],
        ],
        { color: SEVERITY_COLOR[h.severity], weight: 2, fill: false },
      )
        .bindTooltip(
          `${h.severity} · ${h.direction} anomaly ${h.mean_anomaly > 0 ? "+" : ""}${h.mean_anomaly.toFixed(2)} °C (${h.lat.toFixed(1)}°, ${h.lon.toFixed(1)}°)`,
        )
        .addTo(group);
    }
    for (const ev of events ?? []) {
      L.rectangle(
        [
          [ev.bbox.lat_min, ev.bbox.lon_min],
          [ev.bbox.lat_max, ev.bbox.lon_max],
        ],
        { color: "#7c2d12", weight: 2.5, dashArray: "2 4", fillColor: "#fb923c", fillOpacity: 0.08 },
      )
        .bindTooltip(`Marine heatwave · ${ev.category_name} · ${ev.duration_days} days · ${Math.round(ev.area_km2).toLocaleString()} km²`)
        .on("click", () => eventRef.current?.(ev.id))
        .addTo(group);
    }
  }, [hotspots, events]);

  // species observations
  useEffect(() => {
    const group = obsGroup.current;
    if (!group) return;
    group.clearLayers();
    for (const o of observations ?? []) {
      L.circleMarker([o.lat, onAxis(o.lon)], { radius: 3.5, color: "#0f172a", weight: 1, fillColor: "#fde047", fillOpacity: 0.95 })
        .bindTooltip(o.label)
        .addTo(group);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [observations, lonOrigin]);

  // open alerts
  useEffect(() => {
    const group = alertGroup.current;
    if (!group) return;
    group.clearLayers();
    for (const a of alertMarkers ?? []) {
      L.circleMarker([a.lat, onAxis(a.lon)], { radius: 8, color: "#7f1d1d", weight: 3, fillColor: "#ffffff", fillOpacity: 0.6 }).bindTooltip(a.label).addTo(group);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [alertMarkers, lonOrigin]);

  // footprint overlay (e.g. active marine-heatwave cells): follows the cells, so it never shows as a rectangle
  useEffect(() => {
    const map = mapRef.current;
    if (!map) return;
    if (!overlay) {
      footRef.current?.remove();
      footRef.current = null;
      return;
    }
    const H = overlay.lat.length;
    const W = overlay.lon.length;
    const canvas = document.createElement("canvas");
    canvas.width = W;
    canvas.height = H;
    const ctx = canvas.getContext("2d");
    if (!ctx) return;
    const img = ctx.createImageData(W, H);
    const has = (r: number, c: number) => r >= 0 && r < H && c >= 0 && c < W && overlay.values[r][c] != null;
    for (let i = 0; i < H; i++) {
      const r = H - 1 - i;
      for (let j = 0; j < W; j++) {
        if (!has(r, j)) continue;
        const edge = !has(r + 1, j) || !has(r - 1, j) || !has(r, j + 1) || !has(r, j - 1);
        const o = (i * W + j) * 4;
        img.data[o] = edge ? 88 : 124;
        img.data[o + 1] = edge ? 20 : 45;
        img.data[o + 2] = edge ? 4 : 18;
        img.data[o + 3] = edge ? 235 : 70;
      }
    }
    ctx.putImageData(img, 0, 0);
    const dLat = overlay.lat[1] - overlay.lat[0];
    const dLon = overlay.lon[1] - overlay.lon[0];
    const b = L.latLngBounds([overlay.lat[0] - dLat / 2, overlay.lon[0] - dLon / 2], [overlay.lat[H - 1] + dLat / 2, overlay.lon[W - 1] + dLon / 2]);
    const url = canvas.toDataURL();
    if (footRef.current) {
      footRef.current.setUrl(url);
      footRef.current.setBounds(b);
    } else {
      footRef.current = L.imageOverlay(url, b, { opacity: 1, className: "sst-overlay", interactive: false }).addTo(map);
    }
  }, [overlay]);

  // clickable markers (species, alerts)
  useEffect(() => {
    const group = markerGroup.current;
    if (!group) return;
    group.clearLayers();
    for (const m of markers ?? []) {
      const lon = onAxis(m.lon);
      if (m.ring) L.circleMarker([m.lat, lon], { radius: (m.radius ?? 6) + 4, color: "#111827", weight: 2, fillOpacity: 0, interactive: false }).addTo(group);
      const mk = L.circleMarker([m.lat, lon], { radius: m.radius ?? 6, color: "#0f172a", weight: 1.5, fillColor: m.color, fillOpacity: 0.95 }).bindTooltip(m.label).addTo(group);
      if (m.onClick) mk.on("click", (e) => {
        L.DomEvent.stopPropagation(e);
        m.onClick?.();
      });
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [markers, lonOrigin]);

  // gridded OBIS distribution (counts per cell, log-scaled)
  useEffect(() => {
    const group = distGroup.current;
    if (!group) return;
    group.clearLayers();
    if (!distribution) return;
    const nOf = (props: unknown) => Number((props as { n?: number } | null)?.n ?? 0);
    const max = Math.max(1, ...distribution.features.map((f) => nOf(f.properties)));
    L.geoJSON(lonOrigin == null ? distribution : shiftGeoJson(distribution, lonOrigin), {
      style: (f) => {
        const t = Math.log10(1 + nOf(f?.properties)) / Math.log10(1 + max);
        return { color: "#1e3a8a", weight: 0.3, fillColor: "#2563eb", fillOpacity: 0.15 + 0.6 * t };
      },
      onEachFeature: (f, lyr) => lyr.bindTooltip(`${nOf(f.properties).toLocaleString()} OBIS records`),
    }).addTo(group);
  }, [distribution, lonOrigin]);

  // selected-point marker
  useEffect(() => {
    const map = mapRef.current;
    if (!map) return;
    markerRef.current?.remove();
    markerRef.current = null;
    if (selected) {
      markerRef.current = L.circleMarker([selected.lat, onAxis(selected.lon)], {
        radius: 7,
        color: "#0f172a",
        weight: 2,
        fillColor: "#ffffff",
        fillOpacity: 1,
      }).addTo(map);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selected, lonOrigin]);

  return (
    <div className="relative overflow-hidden rounded-b-xl border border-slate-300 bg-sky-100">
      <div ref={host} className={`${heightClass} w-full`} role="application" aria-label={ariaLabel} />
      {!layer && (
        <div className="pointer-events-none absolute inset-0 z-[500] flex items-center justify-center bg-white/60 text-sm text-slate-500">
          {unavailable ? "Map data unavailable" : "Loading map data…"}
        </div>
      )}
      {badge && (
        <div className="pointer-events-none absolute right-2 top-2 z-[500] rounded-md bg-deep/85 px-2.5 py-1 text-xs font-medium text-white shadow">{badge}</div>
      )}
      {hover && (
        <div className="pointer-events-none absolute left-12 top-2 z-[500] max-w-[60%] rounded bg-white/90 px-2 py-1 text-xs text-slate-800 shadow">
          {hover}
        </div>
      )}
      {layer && scale && (
        <div className="pointer-events-none absolute bottom-3 left-3 z-[500] w-56 rounded-md bg-deep/85 p-2.5 text-xs text-white shadow">
          <div className="mb-1 font-semibold leading-tight">{layer.label}</div>
          <div className="h-2.5 rounded-sm ring-1 ring-white/40" style={{ background: cssGradient(scale) }} />
          <div className="mt-0.5 flex justify-between tabular-nums">
            <span>{scale.min.toFixed(1)}</span>
            {layer.diverging && <span className="text-cyan-100/90">0 = normal</span>}
            <span>{scale.max.toFixed(1)}</span>
          </div>
          <div className="mt-0.5 text-cyan-100/90">{legendUnit(layer)}</div>
          {layer.diverging && <div className="text-cyan-100/90">◀ colder than normal · warmer than normal ▶</div>}
          {legendExtra}
          <div className="mt-1 border-t border-white/20 pt-1 text-cyan-100/80">
            {showOutline ? "Dashed outline = area with data. " : ""}Transparent = no data (land, missing, or outside the selected area).
          </div>
        </div>
      )}
    </div>
  );
}
