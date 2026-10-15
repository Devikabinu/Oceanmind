import { useEffect, useMemo, useRef, useState } from "react";
import L from "leaflet";
import "leaflet/dist/leaflet.css";
import type { HeatwaveEvent, Hotspot, MapLayer, Severity } from "../api/monitor";
import { cssGradient, makeScale } from "../utils/colormap";

const SEVERITY_COLOR: Record<Severity, string> = { MEDIUM: "#ca8a04", HIGH: "#ea580c", CRITICAL: "#b91c1c" };

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
  const markerRef = useRef<L.CircleMarker | null>(null);
  const pickRef = useRef(onPick);
  const eventRef = useRef(onEventClick);
  const layerRef = useRef(layer);
  const [hover, setHover] = useState<string | null>(null);

  useEffect(() => {
    pickRef.current = onPick;
    eventRef.current = onEventClick;
    layerRef.current = layer;
  });

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
      minZoom: 2,
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
    map.on("click", (e: L.LeafletMouseEvent) => {
      map.scrollWheelZoom.enable();
      pickRef.current?.(e.latlng.lat, wrapLon(e.latlng.lng));
    });
    map.on("mousemove", (e: L.LeafletMouseEvent) => {
      const l = layerRef.current;
      if (!l) return;
      const lon = wrapLon(e.latlng.lng);
      const where = `${e.latlng.lat.toFixed(2)}°, ${lon.toFixed(2)}°`;
      if (!inside(l, e.latlng.lat, lon)) {
        setHover(`${where} · outside data coverage`);
        return;
      }
      const v = valueAt(l, e.latlng.lat, lon);
      setHover(v == null ? `${where} · land / no data` : `${where} · ${l.diverging && v > 0 ? "+" : ""}${v.toFixed(2)} ${l.unit}`);
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
      markerRef.current = null;
    };
  }, [initialView]);

  // grid overlay + coverage outline
  useEffect(() => {
    const map = mapRef.current;
    if (!map || !layer || !scale) return;
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
        if (v == null) continue; // land / missing stays transparent
        const [r, g, b] = scale.color(v);
        img.data[o] = r;
        img.data[o + 1] = g;
        img.data[o + 2] = b;
        img.data[o + 3] = 215;
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
    } else {
      overlayRef.current = L.imageOverlay(url, bounds, { opacity: 1, className: "sst-overlay" }).addTo(map);
      if (initialView === "study") map.fitBounds(bounds);
    }
    if (!coverageRef.current) {
      coverageRef.current = L.rectangle(bounds, { color: "#334155", weight: 1.5, dashArray: "6 5", fill: false, interactive: false })
        .bindTooltip("Data coverage: study region only", { sticky: true })
        .addTo(map);
    }
  }, [layer, scale, initialView]);

  // fly to requested bounds
  useEffect(() => {
    if (mapRef.current && fitTo) mapRef.current.fitBounds(fitTo, { maxZoom: 7 });
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
      L.circleMarker([o.lat, o.lon], { radius: 3.5, color: "#0f172a", weight: 1, fillColor: "#fde047", fillOpacity: 0.95 })
        .bindTooltip(o.label)
        .addTo(group);
    }
  }, [observations]);

  // open alerts
  useEffect(() => {
    const group = alertGroup.current;
    if (!group) return;
    group.clearLayers();
    for (const a of alertMarkers ?? []) {
      L.circleMarker([a.lat, a.lon], { radius: 8, color: "#7f1d1d", weight: 3, fillColor: "#ffffff", fillOpacity: 0.6 }).bindTooltip(a.label).addTo(group);
    }
  }, [alertMarkers]);

  // gridded OBIS distribution (counts per cell, log-scaled)
  useEffect(() => {
    const group = distGroup.current;
    if (!group) return;
    group.clearLayers();
    if (!distribution) return;
    const nOf = (props: unknown) => Number((props as { n?: number } | null)?.n ?? 0);
    const max = Math.max(1, ...distribution.features.map((f) => nOf(f.properties)));
    L.geoJSON(distribution, {
      style: (f) => {
        const t = Math.log10(1 + nOf(f?.properties)) / Math.log10(1 + max);
        return { color: "#1e3a8a", weight: 0.3, fillColor: "#2563eb", fillOpacity: 0.15 + 0.6 * t };
      },
      onEachFeature: (f, lyr) => lyr.bindTooltip(`${nOf(f.properties).toLocaleString()} OBIS records`),
    }).addTo(group);
  }, [distribution]);

  // selected-point marker
  useEffect(() => {
    const map = mapRef.current;
    if (!map) return;
    markerRef.current?.remove();
    markerRef.current = null;
    if (selected) {
      markerRef.current = L.circleMarker([selected.lat, selected.lon], {
        radius: 7,
        color: "#0f172a",
        weight: 2,
        fillColor: "#ffffff",
        fillOpacity: 1,
      }).addTo(map);
    }
  }, [selected]);

  return (
    <div className="relative overflow-hidden rounded-lg border border-slate-200 bg-sky-100">
      <div ref={host} className={`${heightClass} w-full`} role="application" aria-label={ariaLabel} />
      {!layer && (
        <div className="pointer-events-none absolute inset-0 z-[500] flex items-center justify-center bg-white/60 text-sm text-slate-500">
          Loading map data…
        </div>
      )}
      {hover && (
        <div className="pointer-events-none absolute left-12 top-2 z-[500] rounded bg-white/90 px-2 py-1 text-xs text-slate-700 shadow">
          {hover}
        </div>
      )}
      {layer && scale && (
        <div className="pointer-events-none absolute bottom-2 left-2 z-[500] w-56 rounded bg-white/90 p-2 text-xs text-slate-700 shadow">
          <div className="mb-1 font-medium">{layer.label}</div>
          <div className="h-2.5 rounded" style={{ background: cssGradient(scale) }} />
          <div className="mt-0.5 flex justify-between">
            <span>
              {scale.min.toFixed(1)} {layer.unit}
            </span>
            <span>
              {scale.max.toFixed(1)} {layer.unit}
            </span>
          </div>
          <div className="mt-1 text-slate-500">Dashed outline = area with data. Elsewhere: no data.</div>
        </div>
      )}
    </div>
  );
}
