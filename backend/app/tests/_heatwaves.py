"""Precomputed heatwave results (heatwave.json + heatwave_state.npz, the format oceanmind_model/heatwaves.py writes) for the synthetic Pacific grid of _pacific.py.
The detector itself is tested on the root side (tests/test_heatwaves_pacific.py); these fixtures let the API tests run without scipy or any SST record."""
import json

import numpy as np

from app.tests import _pacific as P

# (name, rows, cols, duration_days, max_anomaly, mean_anomaly, category)
EVENTS = [
    ("antimeridian", (16, 20), (18, 25), 14, 3.4, 2.6, 3),     # lat 6..18, lon 174..198: crosses 180
    ("west", (10, 14), (3, 7), 9, 2.1, 1.7, 2),                  # lat -18..-6, lon 114..126
    ("east", (25, 29), (36, 41), 6, 1.2, 1.0, 1),                # lat 42..54, lon 246..266
]
NAME_BY_ID = {}


def cell_area(res=4.0):
    return (111.32 * res) ** 2 * np.cos(np.deg2rad(P.LAT))


def build(root, latest=P.LATEST, source=P.PROVIDER):
    d = root / "model" / "dashboard"
    d.mkdir(parents=True, exist_ok=True)
    area = cell_area()[:, None] * np.ones((1, P.W))
    label = np.zeros((P.H, P.W), dtype="int16")
    active = np.zeros((P.H, P.W), dtype=bool)
    run_len = np.zeros((P.H, P.W), dtype="int16")
    events = []
    order = sorted(EVENTS, key=lambda e: -((e[1][1] - e[1][0]) * (e[2][1] - e[2][0])))
    for k, (name, (r0, r1), (c0, c1), dur, peak, mean, cat) in enumerate(order, 1):
        m = np.zeros((P.H, P.W), dtype=bool)
        m[r0:r1, c0:c1] = True
        label[m], active[m], run_len[m] = k, True, dur
        ii, jj = np.where(m)
        lon = P.LON[jj]
        ev = {
            "id": f"mhw-pacific-{latest}-{k}", "dataset": "pacific", "status": "ACTIVE", "start_date": str((np.datetime64(latest) - dur + 1)),
            "last_observed_date": latest, "duration_days": dur, "cells": int(m.sum()), "area_km2": round(float(area[m].sum()), 0),
            "centroid": {"lat": round(float(P.LAT[ii].mean()), 2), "lon": round(float(lon.mean()), 2), "lon_180": round(float(((lon.mean() + 180) % 360) - 180), 2)},
            "bbox": {"lat_min": float(P.LAT[ii].min()) - 2, "lat_max": float(P.LAT[ii].max()) + 2, "lon_min": float(lon.min()) - 2, "lon_max": float(lon.max()) + 2},
            "current_anomaly_c": mean, "max_anomaly_c": peak, "category": cat, "category_name": {1: "I (Moderate)", 2: "II (Strong)", 3: "III (Severe)"}[cat],
            "cumulative_intensity_c_days": round(mean * dur, 1), "max_cumulative_intensity_c_days": round(peak * dur, 1),
            "timeline": [{"date": latest, "area_km2": round(float(area[m].sum()), 0), "mean_anomaly_c": mean}],
            "historical_percentile": 97.0, "forecast_still_above_p90_day7": None,
        }
        events.append(ev)
        NAME_BY_ID[ev["id"]] = name
    total = float(np.where(P.land_mask(), 0, area).sum())
    info = {
        "dataset": "pacific", "method": "Simplified Hobday et al. (2016): SST above a seasonally varying 90th percentile for >= 5 days (gaps <= 2 days bridged). "
                                         "Baseline 2012-2023 (12 years, not the recommended 30). Project-level indicator, not an official classification.",
        "baseline": ["2012-01-01", "2023-12-31"],
        "threshold": {"method": "seasonal percentile", "percentile": 90.0, "window_days": 11, "smoothing_days": 31}, "min_duration_days": 5, "max_gap_days": 2,
        "data_source": source["provider_id"], "source": source, "is_observational": source["is_observational"],
        "grid": {"resolution_deg": 4.0, "lat_min": float(P.LAT[0]), "lat_max": float(P.LAT[-1]), "lon_min": float(P.LON[0]), "lon_max": float(P.LON[-1]),
                 "lon_convention": "east longitude, continuous"},
        "latest_date": latest, "ocean_area_km2": round(total, 0), "active_area_km2": round(float(area[active].sum()), 0),
        "active_share": round(float(area[active].sum()) / total, 4), "active_area_historical_rank_pct": 90.0, "min_event_cells": 10,
        "events": events, "yearly": {"2020": {"days": 20, "max_area_km2": 1.0, "mean_area_km2": 0.5, "days_with_heatwave_area_over_5pct": 0}},
        "daily": {"dates": [latest], "mean_sst": [20.0], "mean_anomaly": [0.5], "heatwave_area_km2": [1.0]},
    }
    (d / "heatwave.json").write_text(json.dumps(info))
    np.savez_compressed(d / "heatwave_state.npz", run_len=run_len, active=active, event_label=label, cur_anom=np.where(active, 1.0, np.nan).astype("float32"))
    build_history(d, latest, area, {name: ev for ev, (name, *_rest) in zip(events, order)}, {e[0]: k for k, e in enumerate(order, 1)})
    return d


# (name, rows, cols, first day index, last day index, mean anomaly, max anomaly, category); days index P.DATES. "past" ended before the latest day.
HISTORY = [
    ("past", (2, 6), (30, 35), 0, 7, 1.6, 2.2, 1),
    ("west", (10, 14), (3, 7), 11, 19, 1.7, 2.1, 2),
    ("antimeridian", (16, 20), (18, 25), 6, 19, 2.6, 3.4, 3),
    ("east", (25, 29), (36, 41), 14, 19, 1.0, 1.2, 1),
]
HISTORY_IDS = {}


def build_history(d, latest, area, current, number_of):
    """heatwave_history.json + heatwave_cells.npz in the format oceanmind_model/heatwave_history.py writes: tracked events with their evolution and per-day cells."""
    dates = [str(x.date()) for x in P.DATES]
    cells, events = [], []
    for name, (r0, r1), (c0, c1), a, b, mean, peak, cat in sorted(HISTORY, key=lambda h: (h[3], h[0])):
        ii, jj = np.meshgrid(np.arange(r0, r1), np.arange(c0, c1), indexing="ij")
        ii, jj = ii.ravel(), jj.ravel()
        one_day = float(area[ii, jj].sum())
        lon = P.LON[jj]
        active = b == len(dates) - 1
        ev = {
            "id": f"mhw-pacific-h{dates[a].replace('-', '')}-{'n' if P.LAT[ii].mean() >= 0 else 's'}{abs(int(round(P.LAT[ii].mean()))):02d}e{int(round(lon.mean())) % 360:03d}", "dataset": "pacific",
            "status": "ACTIVE" if active else "ENDED", "start_date": dates[a], "end_date": dates[b], "duration_days": b - a + 1, "peak_date": dates[(a + b) // 2],
            "peak_area_km2": round(one_day, 0), "peak_cells": len(ii), "max_area_km2": round(one_day, 0), "cell_days": len(ii) * (b - a + 1), "mean_anomaly_c": mean, "max_anomaly_c": peak,
            "category": cat, "category_name": {1: "I (Moderate)", 2: "II (Strong)", 3: "III (Severe)"}[cat], "cumulative_intensity_c_days": round(mean * (b - a + 1), 1),
            "centroid": {"lat": round(float(P.LAT[ii].mean()), 2), "lon": round(float(lon.mean()), 2), "lon_180": round(float(((lon.mean() + 180) % 360) - 180), 2)},
            "bbox": {"lat_min": float(P.LAT[ii].min()) - 2, "lat_max": float(P.LAT[ii].max()) + 2, "lon_min": float(lon.min()) - 2, "lon_max": float(lon.max()) + 2},
            "evolution": {"dates": dates[a:b + 1], "area_km2": [round(one_day, 0)] * (b - a + 1), "mean_anomaly_c": [mean] * (b - a + 1)},
        }
        if active:
            ev["current_event_numbers"] = [number_of[name]]
        HISTORY_IDS[name] = ev["id"]
        events.append(ev)
        for t in range(a, b + 1):
            cells.append((t, ii, jj, len(events)))
    t_all = np.concatenate([np.full(len(ii), t) for t, ii, _, _ in cells])
    order = np.argsort(t_all, kind="stable")
    cat = lambda k: np.concatenate([k(c) for c in cells])[order]  # noqa: E731
    t_s = t_all[order]
    offsets = np.concatenate([[0], np.cumsum(np.bincount(t_s, minlength=len(dates)))])
    np.savez_compressed(d / "heatwave_cells.npz", t=t_s.astype("int16"), i=cat(lambda c: c[1]).astype("uint16"), j=cat(lambda c: c[2]).astype("uint16"),
                        ev=cat(lambda c: np.full(len(c[1]), c[3])).astype("int16"), anom=np.full(len(t_s), 200, "int16"), offsets=offsets.astype("int64"), dates=np.asarray(dates, dtype="U10"))
    (d / "heatwave_history.json").write_text(json.dumps({"dataset": "pacific", "first_date": dates[0], "last_date": dates[-1], "n_detected": len(events) + 3, "n_kept": len(events), "events": events}))
