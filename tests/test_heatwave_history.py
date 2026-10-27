"""Historical marine-heatwave events: tracking connected areas from day to day, antimeridian continuity, merging/splitting, evolution and the stored footprints.
Deterministic, no network: the heatwave state is injected directly as a boolean array."""
import json

import numpy as np
import pandas as pd

from oceanmind_model import heatwave_history as hh

LAT = np.arange(-9.5, 10.0, 1.0)
LON = np.arange(172.5, 189.0, 1.0)                 # crosses 180 inside the array
T, H, W = 60, len(LAT), len(LON)
DATES = pd.date_range("2020-01-01", periods=T)


def blank():
    return np.zeros((T, H, W), bool)


def run(mhw, tmp_path, anom_value=2.0):
    anom = np.where(mhw, np.float32(anom_value), np.float32(0.1))
    thr = np.full((366, H, W), 21.0, "float32")
    clim = np.full((366, H, W), 20.0, "float32")
    doy = DATES.dayofyear.to_numpy()
    area = np.full((H, W), 10000.0)
    return hh.build(mhw, anom, thr, clim, doy, DATES, LAT, LON, area, "pacific", "mhw", tmp_path)


def test_an_event_crossing_180_degrees_is_one_event(tmp_path):
    m = blank()
    m[5:35, 4:14, 5:12] = True                     # columns 5..11 are 177.5 .. 183.5 east: straddles the antimeridian
    ev = run(m, tmp_path)
    assert len(ev) == 1
    e = ev[0]
    assert e["start_date"] == "2020-01-06" and e["end_date"] == "2020-02-04" and e["duration_days"] == 30
    assert e["peak_cells"] == 10 * 7 and e["peak_area_km2"] == 70 * 10000
    assert e["max_anomaly_c"] == 2.0 and e["status"] == "ENDED"
    assert e["bbox"]["lon_min"] < 180 < e["bbox"]["lon_max"]           # one event, on the continuous east-longitude axis


def test_two_separate_areas_are_two_events_and_evolution_is_recorded(tmp_path):
    m = blank()
    m[0:20, 2:7, 0:5] = True
    m[10:40, 12:17, 10:16] = True
    for d in range(10, 20):                          # the second grows by one row over time
        m[d + 0, 17:18, 10:16] = d > 14
    ev = run(m, tmp_path)
    assert [e["start_date"] for e in ev] == ["2020-01-01", "2020-01-11"]
    second = ev[1]
    assert second["duration_days"] == 30 and len(second["evolution"]["dates"]) == 30
    assert max(second["evolution"]["area_km2"]) == second["peak_area_km2"]


def test_active_event_is_flagged_and_small_clusters_are_ignored(tmp_path):
    m = blank()
    m[40:, 3:9, 3:9] = True                          # still running on the last day
    m[10:25, 15, 2:5] = True                         # 3 cells: below the minimum event size
    ev = run(m, tmp_path)
    assert len(ev) == 1 and ev[0]["status"] == "ACTIVE" and ev[0]["end_date"] == str(DATES[-1].date())


def test_a_large_area_that_splits_keeps_one_event_per_branch(tmp_path):
    m = blank()
    m[0:10, 6:12, 0:16] = True                       # one wide area ...
    m[10:25, 6:12, 0:6] = True                       # ... then two separate ones
    m[10:25, 6:12, 10:16] = True
    ev = run(m, tmp_path)
    assert len(ev) == 2                              # the original continues in the larger branch, the other starts its own
    assert ev[0]["start_date"] == "2020-01-01" and ev[1]["start_date"] == "2020-01-11"


def test_cell_days_are_stored_per_day_and_reproduce_the_footprint(tmp_path):
    m = blank()
    m[5:15, 4:10, 4:10] = True
    ev = run(m, tmp_path)
    z = np.load(tmp_path / "heatwave_cells.npz")
    off = z["offsets"]
    assert len(off) == T + 1 and off[-1] == len(z["t"])
    day = 7
    lo, hi = off[day], off[day + 1]
    assert hi - lo == 36 and set(z["ev"][lo:hi].tolist()) == {1}
    grid = np.zeros((H, W), bool)
    grid[z["i"][lo:hi], z["j"][lo:hi]] = True
    assert (grid == m[day]).all()
    assert (z["anom"][lo:hi] == 200).all()           # centi-degrees
    meta = json.loads((tmp_path / "heatwave_history.json").read_text())
    assert meta["n_kept"] == 1 and meta["events"][0]["id"] == ev[0]["id"]


def test_no_heatwaves_gives_an_empty_history(tmp_path):
    assert run(blank(), tmp_path) == []
    assert json.loads((tmp_path / "heatwave_history.json").read_text())["events"] == []


def test_days_bridged_over_missing_data_keep_the_footprint_but_have_no_anomaly_value(tmp_path):
    m = blank()
    m[5:25, 4:10, 4:10] = True
    anom = np.where(m, np.float32(2.0), np.float32(0.1))
    anom[12:14] = np.nan                                           # two days of missing data inside the event (bridged by the detector)
    thr = np.full((366, H, W), 21.0, "float32")
    clim = np.full((366, H, W), 20.0, "float32")
    ev = hh.build(m, anom, thr, clim, DATES.dayofyear.to_numpy(), DATES, LAT, LON, np.full((H, W), 10000.0), "pacific", "mhw", tmp_path)
    assert len(ev) == 1 and ev[0]["duration_days"] == 20 and ev[0]["max_anomaly_c"] == 2.0
    evo = ev[0]["evolution"]
    assert evo["mean_anomaly_c"][12 - 5] is None and evo["mean_anomaly_c"][0] == 2.0       # unknown, not zero
    assert evo["area_km2"][12 - 5] == 36 * 10000                                           # the area is still the event's footprint
    z = np.load(tmp_path / "heatwave_cells.npz")
    day = z["offsets"][12], z["offsets"][13]
    assert (z["anom"][day[0]:day[1]] == -32768).all()                                      # missing marker, never 0.00


def test_a_fragment_that_lived_less_than_five_days_is_not_listed(tmp_path):
    m = blank()
    m[10:13, 4:10, 4:10] = True                      # 3 days, ended: not an event
    m[30:34, 12:18, 4:10] = True                     # 4 days, ended: not an event
    m[T - 2:, 3:9, 12:18] = True                     # 2 days and still running: a piece that split off a larger area, not a new heatwave
    m[T - 8:, 14:20, 12:18] = True                   # 8 days and still running: a real current event
    ev = run(m, tmp_path)
    assert [(e["status"], e["duration_days"]) for e in ev] == [("ACTIVE", 8)]
