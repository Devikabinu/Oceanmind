"""Historical marine-heatwave events: every event in the record, not only the ones active on the latest day.

The per-cell heatwave state (`mhw`, see heatwaves.detect_runs) is grouped into events by tracking connected heatwave areas from day to day (see `track`), so one
very large warm period does not turn into a single basin-wide event. The Pacific grid is a single contiguous array across the antimeridian, so an event that straddles 180 degrees is
one event by construction. For each event we keep the whole evolution (daily area and mean anomaly), the peak, the duration and the exact footprint on every day
(sparse cell lists), so the application can show any past date without touching the SST record.

Outputs next to heatwave.json: heatwave_history.json (event table) and heatwave_cells.npz (sparse cell-days of the kept events)."""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd
from scipy import ndimage

KEEP_EVENTS = 400                  # largest events by cell-days, plus every event still active on the latest day
MIN_EVENT_DAYS = 5                 # a followed area that lived for fewer days is a fragment that split from or merged into a larger event (a new heatwave cannot be younger than 5 days): not listed
MIN_PEAK_CELLS = 10                # an event needs at least this many cells on its largest day (about 7,000 km2 at 1 degree)
CATEGORY_NAMES = {1: "I (Moderate)", 2: "II (Strong)", 3: "III (Severe)", 4: "IV (Extreme)"}


def _id(prefix, start, lat, lon, taken):
    base = f"{prefix}-h{start:%Y%m%d}-{'n' if lat >= 0 else 's'}{abs(int(round(lat))):02d}e{int(round(lon)) % 360:03d}"
    k, out = 1, base
    while out in taken:
        k += 1
        out = f"{base}-{k}"
    taken.add(out)
    return out


def track(mhw):
    """Follow heatwave areas from day to day. Each day's connected areas (8 neighbours) continue the previous day's event they overlap most
    (overlap of at least a quarter of the smaller area); an area that overlaps nothing starts a new event; when areas merge or split only the largest overlap continues the
    original event and the others start their own. Returns (t, i, j, event number) of every cell-day that belongs to an event, and the number of events."""
    T, H, W = mhw.shape
    st = np.ones((3, 3), bool)
    ts, iis, jjs, ids = [], [], [], []
    prev = np.zeros((H, W), np.int32)
    prev_size = np.zeros(1, np.int64)
    next_id = 1
    for t in range(T):
        lab, n = ndimage.label(mhw[t], structure=st)
        cur = np.zeros((H, W), np.int32)
        if n:
            sizes = np.bincount(lab.ravel(), minlength=n + 1)
            comps = np.arange(1, n + 1)                                  # every area is followed, however small, so an event's start is its true first day
            lut = np.zeros(n + 1, np.int32)
            used_prev: set = set()
            if comps.size and prev.any():
                m = (lab > 0) & (prev > 0)
                key = lab[m].astype(np.int64) * (len(prev_size) + 1) + prev[m]
                u, c = np.unique(key, return_counts=True)
                cand = []
                for kk, cnt in zip(u, c):
                    comp, ev = int(kk // (len(prev_size) + 1)), int(kk % (len(prev_size) + 1))
                    if cnt >= 0.25 * min(sizes[comp], prev_size[ev]):
                        cand.append((int(cnt), comp, ev))
                cand.sort(reverse=True)
                for cnt, comp, ev in cand:
                    if lut[comp] == 0 and ev not in used_prev:
                        lut[comp] = ev
                        used_prev.add(ev)
            for comp in comps:
                if lut[comp] == 0:
                    lut[comp] = next_id
                    next_id += 1
            cur = lut[lab]
            if comps.size:
                ii, jj = np.nonzero(cur)
                ts.append(np.full(len(ii), t, np.int16)); iis.append(ii.astype(np.int16)); jjs.append(jj.astype(np.int16)); ids.append(cur[ii, jj])
        prev = cur
        prev_size = np.bincount(cur.ravel(), minlength=next_id + 1).astype(np.int64)
    if not ts:
        z = np.zeros(0, np.int32)
        return z, z, z, z, 0
    return np.concatenate(ts), np.concatenate(iis), np.concatenate(jjs), np.concatenate(ids), next_id - 1


def build(mhw, anom, thr, clim, doy, dates, lat, lon, area, dataset, id_prefix, out_dir: Path, current_label=None):
    """mhw (T,H,W) bool, anom (T,H,W) float32 degC. thr/clim (366,H,W). Returns the event table (also written to heatwave_history.json)."""
    T, H, W = mhw.shape
    t, i, j, L, n = track(mhw)
    if n == 0:
        events = []
        (out_dir / "heatwave_history.json").write_text(json.dumps({"dataset": dataset, "events": []}))
        np.savez_compressed(out_dir / "heatwave_cells.npz", t=np.zeros(0, "int16"), i=np.zeros(0, "uint16"), j=np.zeros(0, "uint16"), ev=np.zeros(0, "int16"),
                            anom=np.zeros(0, "int16"), offsets=np.zeros(T + 1, "int64"))
        return events
    order = np.argsort(L, kind="stable")
    t, i, j, L = t[order], i[order], j[order], L[order]
    a = anom[t, i, j]
    cell_area = area[i, j]
    d = np.maximum(thr[doy[t] - 1, i, j] - clim[doy[t] - 1, i, j], 0.1)
    ratio = a / d
    bounds = np.flatnonzero(np.diff(L)) + 1
    starts = np.concatenate([[0], bounds])
    ends = np.concatenate([bounds, [len(L)]])
    cell_days = ends - starts
    last_t = T - 1
    rows = []
    for s, e in zip(starts, ends):
        tt = t[s:e]
        if tt.max() == last_t or e - s >= MIN_PEAK_CELLS * 5:
            rows.append((s, e))
    rows.sort(key=lambda r: -(r[1] - r[0]))
    keep = []
    for s, e in rows:
        tt = t[s:e]
        active = bool(tt.max() == last_t)
        if not active and len(keep) >= KEEP_EVENTS:
            continue
        per_day = np.bincount(tt - tt.min())
        if per_day.max() < MIN_PEAK_CELLS or int(tt.max() - tt.min()) + 1 < MIN_EVENT_DAYS:
            continue
        keep.append((s, e, active))
    taken: set = set()
    events = []
    for s, e, active in keep:
        tt, ii, jj = t[s:e], i[s:e], j[s:e]
        t0, t1 = int(tt.min()), int(tt.max())
        days = np.arange(t0, t1 + 1)
        aa, ar, rr = a[s:e], cell_area[s:e], ratio[s:e]
        fin = np.isfinite(aa)                                  # a day bridged across missing data counts for the footprint but has no anomaly value
        area_by_day = np.bincount(tt - t0, weights=ar, minlength=len(days))
        cnt_by_day = np.bincount(tt - t0, minlength=len(days))
        cnt_fin = np.bincount(tt - t0, weights=fin, minlength=len(days))
        mean_anom = np.where(cnt_fin > 0, np.bincount(tt - t0, weights=np.where(fin, aa, 0), minlength=len(days)) / np.maximum(cnt_fin, 1), np.nan)
        mean_ratio = np.where(cnt_fin > 0, np.bincount(tt - t0, weights=np.where(fin, rr, 0), minlength=len(days)) / np.maximum(cnt_fin, 1), np.nan)
        pk = int(np.argmax(area_by_day))
        sel = tt == (t0 + pk)
        cat = int(np.clip(np.floor(np.nanmax(mean_ratio)), 1, 4)) if np.isfinite(mean_ratio).any() else 1
        lat_c, lon_c = float(lat[ii[sel]].mean()), float(lon[jj[sel]].mean())
        res = float(lat[1] - lat[0]) if len(lat) > 1 else 1.0
        ev = {
            "id": _id(id_prefix, dates[t0], lat_c, lon_c, taken), "dataset": dataset, "status": "ACTIVE" if active else "ENDED",
            "start_date": str(dates[t0].date()), "end_date": str(dates[t1].date()), "duration_days": int(t1 - t0 + 1),
            "peak_date": str(dates[t0 + pk].date()), "peak_area_km2": round(float(area_by_day[pk]), 0), "peak_cells": int(cnt_by_day[pk]),
            "max_area_km2": round(float(area_by_day.max()), 0), "cell_days": int(e - s),
            "mean_anomaly_c": round(float(np.nanmean(aa)), 2) if fin.any() else None, "max_anomaly_c": round(float(np.nanmax(aa)), 2) if fin.any() else None,
            "category": cat, "category_name": CATEGORY_NAMES[cat],
            "cumulative_intensity_c_days": round(float(np.nansum(aa) / len(np.unique(ii.astype("int64") * W + jj))), 1),   # per cell, degC-days
            "centroid": {"lat": round(lat_c, 2), "lon": round(lon_c, 2), "lon_180": round(((lon_c + 180) % 360) - 180, 2)},
            "bbox": {"lat_min": round(float(lat[ii].min()) - res / 2, 3), "lat_max": round(float(lat[ii].max()) + res / 2, 3),
                     "lon_min": round(float(lon[jj].min()) - res / 2, 3), "lon_max": round(float(lon[jj].max()) + res / 2, 3)},
            "evolution": {"dates": [str(dates[t0 + k].date()) for k in range(len(days))], "area_km2": np.round(area_by_day, 0).tolist(),
                          "mean_anomaly_c": [None if not np.isfinite(x) else round(float(x), 2) for x in mean_anom]},
            "_range": (int(s), int(e)),
        }
        if active and current_label is not None:
            on_last = tt == last_t
            lbl = current_label[ii[on_last], jj[on_last]]
            lbl = lbl[lbl > 0]
            ev["current_event_numbers"] = sorted(set(int(x) for x in lbl))
        events.append(ev)
    events.sort(key=lambda x: (x["start_date"], x["id"]))
    # sparse cell-days of the kept events, grouped by day (offsets[t]:offsets[t+1])
    parts = [(np.arange(*ev.pop("_range")), k + 1) for k, ev in enumerate(events)]
    idx = np.concatenate([p[0] for p in parts]) if parts else np.zeros(0, int)
    evn = np.concatenate([np.full(len(p[0]), p[1]) for p in parts]) if parts else np.zeros(0, int)
    srt = np.argsort(t[idx], kind="stable")
    idx, evn = idx[srt], evn[srt]
    tt_all = t[idx]
    offsets = np.concatenate([[0], np.cumsum(np.bincount(tt_all, minlength=T))]).astype("int64")
    np.savez_compressed(out_dir / "heatwave_cells.npz", t=tt_all.astype("int16"), i=i[idx].astype("uint16"), j=j[idx].astype("uint16"), ev=evn.astype("int16"),
                        anom=np.where(np.isfinite(a[idx]), np.round(np.nan_to_num(a[idx]) * 100), -32768).astype("int16"), offsets=offsets, dates=np.asarray([str(x.date()) for x in dates], dtype="U10"))
    (out_dir / "heatwave_history.json").write_text(json.dumps({"dataset": dataset, "first_date": str(dates[0].date()), "last_date": str(dates[-1].date()),
                                                               "n_detected": int(n), "n_kept": len(events), "events": events}))
    return events
