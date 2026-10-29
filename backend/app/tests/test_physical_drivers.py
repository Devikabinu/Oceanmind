"""Physical-driver retrieval and assessment. No test reaches the network: every HTTP call is replaced by canned data."""
import json
import math
import time
from datetime import date, datetime, timedelta, timezone

import numpy as np
import pytest

from app.services import ocean_context as oc
from app.services import physical_analysis as pa
from app.services import physical_drivers as pdv
from app.tests.test_pacific_product import h, pac  # noqa: F401  (fixtures)
from app.tests import _pacific as P


# ------------------------------------------------------------------------------------------------ units and derived quantities
def test_wind_stress_uses_the_large_and_pond_drag_and_keeps_the_wind_direction():
    tx, ty = pdv.wind_stress(5.0, 0.0)
    assert tx == pytest.approx(1.22 * 1.2e-3 * 25, rel=1e-6) and ty == 0.0                               # 0.0366 N/m² for a 5 m/s wind
    assert pdv.drag_coefficient(5) == 1.2e-3 and pdv.drag_coefficient(15) == pytest.approx((0.49 + 0.065 * 15) * 1e-3)
    assert pdv.drag_coefficient(40) == pdv.drag_coefficient(25)                                            # capped
    tx2, ty2 = pdv.wind_stress(-3.0, 4.0)
    assert tx2 < 0 < ty2 and math.hypot(tx2, ty2) == pytest.approx(1.22 * 1.2e-3 * 25, rel=1e-6)


def test_ekman_transport_has_the_right_sign_and_is_undefined_at_the_equator():
    mx, my = pdv.ekman_transport(30.0, 0.0, 0.1)                                                           # northward stress in the northern hemisphere: transport to the east (right of the wind)
    assert mx > 0 and abs(my) < 1e-12
    sx, sy = pdv.ekman_transport(-30.0, 0.0, 0.1)
    assert sx < 0                                                                                          # to the left of the wind in the southern hemisphere
    assert pdv.ekman_transport(1.0, 0.05, 0.0) is None


def test_wind_direction_is_the_direction_the_wind_comes_from():
    assert pdv.bearing_from(0.0, -5.0) == pytest.approx(0.0)                                               # wind blowing toward the south comes from the north
    assert pdv.bearing_from(-5.0, 0.0) == pytest.approx(90.0)                                              # blowing toward the west: from the east
    assert pdv.bearing_from(5.0, 0.0) == pytest.approx(270.0)


def test_longitude_conventions_and_the_dateline():
    assert pdv.lon360(-150) == 210 and pdv.lon360(179) == 179 and pdv.lon360(-179) == 181 and pdv.lon180(181) == -179 and pdv.lon180(210) == -150
    assert pdv._key(10.0, 179.0) != pdv._key(10.0, -179.0) and pdv._key(10.0, 181.0) == pdv._key(10.0, -179.0)


def test_wind_queries_use_each_datasets_own_longitude_axis(monkeypatch):
    seen = []
    monkeypatch.setattr(oc, "_csv", lambda url: seen.append(url) or [])
    for lon in (-179.0, 179.0, -150.0):
        pdv._wind_query(10.0, lon, "2026-10-20T00:00:00Z", "2026-10-27T18:00:00Z")
    assert "(180.7500):1:(181.2500)" in seen[0] and "(178.7500):1:(179.2500)" in seen[1] and "(209.7500):1:(210.2500)" in seen[2]          # CCMP is 0-360 east
    seen.clear()
    monkeypatch.setattr(oc, "_last_time", lambda base, ds: date(2026, 10, 27))
    pdv.sea_level(10.0, 181.0)
    assert "(-179.1250):1:(-178.8750)" in seen[0]                                                          # the altimetry products are -180..180


# ------------------------------------------------------------------------------------------------ winds
def _rows(day_values):
    """ERDDAP-style rows: for each (date, [(u, v), ...4 analyses]) one row per analysis and cell."""
    out = []
    for d, steps in day_values:
        for k, (u, v) in enumerate(steps):
            for _ in range(4):
                out.append({"time": f"{d}T{6 * k:02d}:00:00Z", "uwnd": str(u), "vwnd": str(v)})
    return out


def test_daily_means_need_three_of_four_analyses_and_missing_cells_are_not_zero():
    rows = _rows([("2026-10-20", [(3, 4)] * 4), ("2026-10-21", [(3, 4)] * 2)])                              # the second day has only two analyses
    rows.append({"time": "2026-10-20T00:00:00Z", "uwnd": "NaN", "vwnd": "NaN"})
    days = pdv._daily(pdv._time_rows(rows))
    assert [d["date"] for d in days] == ["2026-10-20"] and days[0]["speed"] == pytest.approx(5.0)


def test_winds_report_the_recent_week_against_the_baseline_and_flag_a_missing_week(monkeypatch):
    end = "2026-10-27T18:00:00Z"
    monkeypatch.setattr(oc, "_csv", lambda url: [{"time": end}])
    days = [{"date": f"2026-10-{14 + k}", "speed": 4.0 if k >= 7 else 6.0, "u": -4.0 if k >= 7 else -6.0, "v": 0.0, "taux": 0.01 if k >= 7 else -0.04, "tauy": 0.0} for k in range(14)]
    monkeypatch.setattr(pdv, "_wind_query", lambda *a: days)
    base = {"fetched_at": "2026-10-28T00:00:00+00:00", "years": list(range(2016, 2026)), "window": "the 7 days ending 27 October", "dataset": "ccmp",
            "speed": {"mean": 6.0, "sd": 1.0}, "u": {"mean": -6.0, "sd": 1.0}, "v": {"mean": 0.0, "sd": 1.0}, "taux": {"mean": -0.04, "sd": 0.02}, "tauy": {"mean": 0.0, "sd": 0.02}}
    monkeypatch.setattr(pdv, "_wind_baseline", lambda lat, lon, e: base)
    w = pdv.winds(0.0, -150.0)
    assert w["available"] and w["recent"]["speed"] == pytest.approx(4.0) and w["previous"]["speed"] == pytest.approx(6.0) and w["dataset_end"] == "2026-10-27"
    assert w["anomaly"]["speed"] == pytest.approx(-2.0) and w["anomaly"]["speed_z"] == -2.0 and w["anomaly"]["taux_z"] == pytest.approx(2.5)
    assert w["recent"]["direction_from_deg"] == 90
    monkeypatch.setattr(pdv, "_wind_query", lambda *a: days[:5])                                            # not a full week: no recent mean is invented
    assert pdv.winds(0.0, -150.0)["available"] is False


def test_the_baseline_needs_enough_years_and_is_cached(monkeypatch):
    calls = {"n": 0}

    def q(lat, lon, t0, t1):
        calls["n"] += 1
        return [{"date": "x", "speed": 6.0 + 0.1 * calls["n"], "u": -6.0, "v": 0.0, "taux": -0.04, "tauy": 0.0}] * 7
    monkeypatch.setattr(pdv, "_wind_query", q)
    end = datetime(2026, 10, 27, 18)
    b = pdv._wind_baseline(1.0, -150.0, end)
    assert len(b["years"]) == 10 and b["speed"]["sd"] > 0 and "insufficient" not in b
    n = calls["n"]
    assert pdv._wind_baseline(1.0, -150.0, end)["years"] == b["years"] and calls["n"] == n                  # served from the cache, not downloaded again
    monkeypatch.setattr(pdv, "_wind_query", lambda *a: [])
    poor = pdv._wind_baseline(2.0, -150.0, end)
    assert "speed" not in poor and "only 0 of 10" in poor["insufficient"]


# ------------------------------------------------------------------------------------------------ heat-flux climatology
def test_net_heat_flux_follows_the_stated_sign_convention(monkeypatch):
    vals = {"dswrf": 200.0, "uswrf": 20.0, "dlwrf": 400.0, "ulwrf": 440.0, "lhtfl": 100.0, "shtfl": 10.0}
    monkeypatch.setattr(pdv, "_dap_axis", lambda f, name: np.array([10.0, 5.0, 0.0]) if name == "lat" else np.arange(0.0, 360.0, 2.0))

    def dap(url):
        v = url.split("?")[1].split("[")[0]
        return f"Dataset {{}}\n---\n{v}.{v}[2][1][1]\n[0][0], {vals[v]}\n[1][0], {vals[v]}\n\n{v}.time[2]\n1, 2\n"
    monkeypatch.setattr(pdv, "_dap", dap)
    h = pdv.heat_flux_climatology(4.0, -150.0, date(2026, 6, 15), days=2)
    assert h["net"][0] == pytest.approx(30.0) and h["kind"].startswith("climatology") and "positive = heat gained by the ocean" in h["sign"]
    assert h["grid_point"] == {"lat": 5.0, "lon": -150.0} and "not this year's flux" in h["text"] and "gaining about 30" in h["text"]


def test_the_day_of_year_index_ignores_the_leap_day():
    assert pdv._doy_index(date(2026, 1, 1)) == 0 and pdv._doy_index(date(2026, 12, 31)) == 364 and pdv._doy_index(date(2024, 2, 29)) == pdv._doy_index(date(2024, 2, 28))


# ------------------------------------------------------------------------------------------------ ENSO
def test_the_cpc_nino_file_is_parsed_and_the_latest_month_used(monkeypatch):
    text = "YR MON  NINO1+2   ANOM   NINO3    ANOM   NINO4    ANOM NINO3.4    ANOM\n" + "\n".join(f"2025 {m:2d}  24.0 0.1 26.0 0.2 28.0 0.3 27.{m % 10} 0.{m % 10}" for m in range(1, 13)) + "\n2026  1  25.0 1.0 27.0 1.0 29.0 1.0 28.50 1.40\n"

    class R:
        status_code, text_ = 200, text
    R.text = text
    monkeypatch.setattr(pdv.requests, "get", lambda *a, **k: R())
    e = pdv.enso()
    assert e["latest_month"] == "2026-01" and e["nino34_anomaly"] == 1.40 and len(e["recent"]) == 6 and e["kind"] == "contextual climate index"
    assert pdv.parse_sstoi("junk\nnot numbers here at all x x x x x x\n") == []


# ------------------------------------------------------------------------------------------------ independent sources, cache, background
def _fake_ok(name):
    return lambda *a, **k: {"available": True, "dataset_end": "2026-10-27", "latest": {"date": "2026-10-27"}, "name": name}


def test_one_failing_source_leaves_the_others_in_place(monkeypatch):
    monkeypatch.setattr(pdv, "winds", _fake_ok("w"))
    monkeypatch.setattr(pdv, "heat_flux_climatology", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("PSL down")))
    monkeypatch.setattr(pdv, "sea_level", _fake_ok("s"))
    monkeypatch.setattr(pdv, "power_met", _fake_ok("r"))
    monkeypatch.setattr(oc, "currents", _fake_ok("c"))
    monkeypatch.setattr(pdv, "enso", lambda: {"available": False, "message": "no file"})
    p = pdv.build(0.0, -150.0, date(2026, 10, 27))
    assert {k: v["status"] for k, v in p["sources"].items()} == {"winds": "ok", "heat_flux": "unavailable", "radiation": "ok", "sea_level": "ok", "currents": "ok", "enso": "no_data"}
    assert p["heat_flux"]["available"] is False and "PSL down" in p["heat_flux"]["message"] and p["winds"]["available"]
    monkeypatch.setattr(pdv, "winds", lambda *a: (_ for _ in ()).throw(RuntimeError("x")))
    monkeypatch.setattr(pdv, "power_met", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("x")))
    for n in ("sea_level",):
        monkeypatch.setattr(pdv, n, lambda *a: (_ for _ in ()).throw(RuntimeError("x")))
    monkeypatch.setattr(oc, "currents", lambda *a: (_ for _ in ()).throw(RuntimeError("x")))
    monkeypatch.setattr(pdv, "enso", lambda: (_ for _ in ()).throw(RuntimeError("x")))
    with pytest.raises(RuntimeError, match="no physical-driver source"):
        pdv.build(0.0, -150.0, date(2026, 10, 27))


@pytest.fixture
def live(monkeypatch):
    monkeypatch.setattr(pdv, "ENABLED", True)
    calls = {"n": 0}

    def fake(lat, lon, d=None):
        calls["n"] += 1
        return {"schema": pdv.SCHEMA, "fetched_at": datetime.now(timezone.utc).isoformat(timespec="seconds"), "query": {"lat": lat, "lon": lon}, "sources": {"winds": {"status": "ok"}}, "winds": {"available": True}}
    monkeypatch.setattr(pdv, "build", fake)
    return calls


def test_a_miss_fetches_once_then_serves_from_the_cache(live):
    assert pdv.location_drivers(0.0, -150.0, wait_s=5)["status"] == "live" and live["n"] == 1
    assert pdv.location_drivers(0.1, -150.1, wait_s=5)["status"] == "cached" and live["n"] == 1


def test_a_slow_fetch_does_not_block_and_a_failed_one_is_not_hammered(monkeypatch, live):
    def slow(lat, lon, d=None):
        time.sleep(0.5)
        return {"schema": pdv.SCHEMA, "fetched_at": datetime.now(timezone.utc).isoformat(timespec="seconds"), "query": {}, "sources": {"winds": {"status": "ok"}}, "winds": {"available": True}}
    monkeypatch.setattr(pdv, "build", slow)
    t = time.monotonic()
    r = pdv.location_drivers(5.0, 5.0, wait_s=0.05)
    assert time.monotonic() - t < 0.4 and r["status"] == "refreshing"
    time.sleep(0.9)
    assert pdv.location_drivers(5.0, 5.0, wait_s=0.05)["status"] == "cached"
    n = {"n": 0}

    def boom(lat, lon, d=None):
        n["n"] += 1
        raise RuntimeError("down")
    monkeypatch.setattr(pdv, "build", boom)
    assert pdv.location_drivers(40.0, 40.0, wait_s=5)["status"] == "unavailable"
    pdv.location_drivers(40.0, 40.0, wait_s=5)
    assert n["n"] == 1


def test_a_stale_cache_is_used_when_the_refresh_fails(monkeypatch, live):
    pdv.location_drivers(0.0, -150.0, wait_s=5)
    f = pdv._file(pdv.cache_key(0.0, -150.0, date.today()))
    old = json.loads(f.read_text())
    old["fetched_at"] = (datetime.now(timezone.utc) - timedelta(days=3)).isoformat(timespec="seconds")
    f.write_text(json.dumps(old))
    monkeypatch.setattr(pdv, "build", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("down")))
    assert pdv.location_drivers(0.0, -150.0, wait_s=5)["status"] == "stale_cache"
    monkeypatch.setattr(pdv, "ENABLED", False)
    assert pdv.location_drivers(0.0, -150.0) is None


# ------------------------------------------------------------------------------------------------ the assessment rules
def W(speed_z=-2.0, taux_z=2.5, speed=4.0, **over):
    base = {"speed": {"mean": 6.0, "sd": 1.0}, "taux": {"mean": -0.04, "sd": 0.02}, "tauy": {"mean": 0.0, "sd": 0.02}, "years": list(range(2016, 2026)), "window": "w", "dataset": "ccmp"}
    return {"available": True, "latest_date": "2026-10-27", "dataset_end": "2026-10-27", "window": {"start": "2026-10-21", "end": "2026-10-27"}, "recent": {"speed": speed, "u": -speed, "v": 0.0, "taux": 0.01, "tauy": 0.0, "direction_from_deg": 90},
            "baseline": base, "anomaly": {"speed": speed - 6.0, "speed_z": speed_z, "taux": 0.05, "taux_z": taux_z, "tauy": 0.0, "tauy_z": 0.0}, "series": [{"date": f"2026-10-{14 + k}", "speed": speed, "taux": 0.01} for k in range(14)], **over}


def test_weaker_winds_are_consistent_with_a_warm_anomaly_and_not_with_a_cold_one():
    warm = pa.wind_mechanism(W(speed_z=-2.0), +2.0)
    assert warm["verdict"] == "consistent" and warm["favours"] == "warming" and "weaker winds reduce turbulent mixing" in " ".join(warm["evidence_for"]).lower()
    cold = pa.wind_mechanism(W(speed_z=-2.0), -2.0)
    assert cold["verdict"] == "not consistent" and cold["evidence_for"] == [] and cold["evidence_against"]
    assert pa.wind_mechanism(W(speed_z=2.0, speed=8.0), -2.0)["verdict"] == "consistent"
    assert pa.wind_mechanism(W(speed_z=0.3), 2.0)["verdict"] == "inconclusive"
    assert pa.wind_mechanism(W(speed_z=-2.0), 0.2)["verdict"] == "inconclusive"                              # nothing to explain
    assert pa.wind_mechanism({"available": False, "message": "m"}, 2.0)["verdict"] == "not assessable" and pa.wind_mechanism(None, 2.0)["verdict"] == "not assessable"


def test_equatorial_upwelling_is_judged_from_the_zonal_stress_against_its_normal():
    m = pa.upwelling_mechanism(W(taux_z=2.5), +2.0, 0.5, None)
    assert m["verdict"] == "consistent" and m["favours"] == "warming" and "weaker upwelling" in " ".join(m["evidence_for"])
    assert pa.upwelling_mechanism(W(taux_z=-2.5), +2.0, 0.5, None)["verdict"] == "not consistent"
    assert pa.upwelling_mechanism(W(taux_z=0.2), +2.0, 0.5, None)["verdict"] == "inconclusive"
    off = pa.upwelling_mechanism(W(), +2.0, 20.0, None)
    assert off["verdict"] == "not assessable" and "curl" in off["caveat"] and any(d["label"] == "Ekman transport" for d in off["data"])


def test_coastal_upwelling_compares_the_offshore_ekman_transport_with_normal():
    w = W()
    w["recent"].update(taux=0.0, tauy=-0.08)                                                                   # equatorward stress in the northern hemisphere
    w["baseline"]["taux"]["mean"], w["baseline"]["tauy"]["mean"] = 0.0, -0.16
    coast = {"near_coast": True, "offshore": (-1.0, 0.0), "land_fraction": 0.2}                                # the ocean lies to the west of the coast
    m = pa.upwelling_mechanism(w, +1.5, 35.0, coast)
    assert m["verdict"] in ("consistent", "inconclusive", "not consistent") and any("away from the coast" in d["label"] for d in m["data"])
    w["recent"]["tauy"] = -0.16
    assert pa.upwelling_mechanism(w, +1.5, 35.0, coast)["verdict"] == "inconclusive"                           # equal to normal


def test_advection_is_compared_with_the_observed_trend_and_refused_at_the_equator():
    cur = {"available": True, "latest": {"u": 0.3, "v": 0.0, "date": "2026-10-26"}}
    adv = {"dTdx_c_per_m": 1e-5, "dTdy_c_per_m": 0.0, "date": "2026-10-27"}                                       # warmer to the east, current flowing east: warmer water is carried away, cooler arrives: cooling
    m = pa.advection_mechanism(cur, adv, -0.05, 30.0, -1.0)
    assert m["verdict"] == "consistent" and m["favours"] == "cooling" and any("same sign" in t for t in m["evidence_for"])
    assert pa.advection_mechanism(cur, adv, +0.05, 30.0, +1.0)["verdict"] == "not consistent"
    warm_adv = {"dTdx_c_per_m": -1e-5, "dTdy_c_per_m": 0.0, "date": "d"}                                           # colder to the east: the eastward current brings warmer water from the west
    assert pa.advection_mechanism(cur, warm_adv, +0.05, 30.0, +1.0)["favours"] == "warming" and pa.advection_mechanism(cur, warm_adv, +0.05, 30.0, +1.0)["verdict"] == "consistent"
    assert pa.advection_mechanism(cur, {"dTdx_c_per_m": -1e-8, "dTdy_c_per_m": 0.0, "date": "d"}, 0.05, 30.0, 1.0)["verdict"] == "inconclusive"
    assert pa.advection_mechanism(cur, adv, -0.05, 1.0, -1.0)["verdict"] == "not assessable"
    assert pa.advection_mechanism(cur, None, -0.05, 30.0, -1.0)["verdict"] == "not assessable" and pa.advection_mechanism({"available": False}, adv, 0.0, 30.0, 1.0)["verdict"] == "not assessable"


def test_sea_level_and_enso_rules_and_their_regions():
    s = {"available": True, "recent_mean_m": 0.12, "change_m": 0.02, "latest": {"date": "2026-10-27"}, "window": {"start": "2026-10-21", "end": "2026-10-27"},
         "baseline": {"years": list(range(2016, 2026)), "mean_m": 0.05, "sd_m": 0.03}, "departure_m": 0.07, "departure_z": 2.3}
    assert pa.sea_level_mechanism(s, +2.0)["verdict"] == "consistent" and pa.sea_level_mechanism(s, -2.0)["verdict"] == "not consistent"
    assert pa.sea_level_mechanism({**s, "departure_m": 0.01, "departure_z": 0.3}, +2.0)["verdict"] == "inconclusive"
    e = {"available": True, "nino34_anomaly": 2.8, "latest_month": "2026-09", "oni": {"value": 2.16, "season": "JAS 2026"}}
    assert pa.enso_mechanism(e, +2.0, 0.0, -150.0)["verdict"] == "consistent" and pa.enso_mechanism(e, -2.0, 0.0, -150.0)["verdict"] == "not consistent"
    remote = pa.enso_mechanism(e, +2.0, 35.0, -125.0)
    assert remote["verdict"] == "inconclusive" and "teleconnection" in " ".join(remote["evidence_against"])
    assert pa.enso_mechanism({**e, "nino34_anomaly": 0.1}, +2.0, 0.0, -150.0)["verdict"] == "inconclusive"
    assert pa.enso_mechanism({"available": False}, 1.0, 0.0, 0.0)["verdict"] == "not assessable"


def test_enso_acts_directly_only_in_the_central_and_eastern_tropical_pacific():
    assert pa.enso_region(0, -150) and pa.enso_region(10, 170) and pa.enso_region(-10, -100) and pa.enso_region(0, 179) and pa.enso_region(0, -179)       # across the dateline
    assert not pa.enso_region(0, 150) and not pa.enso_region(30, -150) and not pa.enso_region(0, -70) and not pa.enso_region(-47.6, -165.6)                # western Pacific, mid-latitudes, South America


def test_heat_flux_is_never_judged_without_a_current_flux_anomaly():
    h = {"available": True, "net": [96.0] * 8, "start_date": "2026-10-27"}
    m = pa.heat_flux_mechanism(h, +2.0, None)
    assert m["verdict"] == "not assessable" and m["favours"] == "warming" and "is unresolved" in m["caveat"] and m["kind"] == "climatology"
    assert pa.heat_flux_mechanism({"available": False, "message": "x"}, 2.0, None)["verdict"] == "not assessable"


def _ctx(a=2.0, reading=None, lat=0.0, lon=-150.0, **over):
    rd = reading or fr_reading()
    return {"date": "2026-10-27", "lat": lat, "lon": lon, "sst": 30.0, "anomaly": a, "recent": [{"date": f"2026-10-{14 + k}", "anomaly_c": 2.0, "sst_c": 30.0} for k in range(14)],
            "trends": {"days": 7, "sst_7d_c_per_day": 0.03, "sst_3d_c_per_day": 0.05, "anomaly_7d_change_c": 0.2, "anomaly_3d_change_c": 0.1, "from": "2026-10-21", "to": "2026-10-27"}, "reading": rd,
            "forecast": {"issued_from": "2026-10-27", "dates": [f"2026-10-{28 + k}" if 28 + k <= 31 else f"2026-11-0{k - 3}" for k in range(7)]}, "advection": None, "coast": None, "baseline": None, **over}


def fr_reading(sst=(30.0, 29.6), anom=(2.0, 1.6), days=7):
    from app.services import forecast_reading as fr
    return fr.reading(sst[0], anom[0], [sst[0] + (sst[1] - sst[0]) * (k + 1) / days for k in range(days)], [anom[0] + (anom[1] - anom[0]) * (k + 1) / days for k in range(days)])


def DRV(**over):
    d = {"status": "live", "winds": W(), "heat_flux": {"available": True, "net": [96.0] * 8, "start_date": "2026-10-27", "source": "PSL", "dataset": "R1", "kind": "climatology", "unit": "W/m²"},
         "sea_level": {"available": True, "recent_mean_m": 0.5, "change_m": 0.01, "latest": {"date": "2026-10-27"}, "dataset_end": "2026-10-27", "window": {"start": "2026-10-21", "end": "2026-10-27"}, "baseline": {"years": list(range(2016, 2026)), "mean_m": 0.4, "sd_m": 0.03}, "departure_m": 0.1, "departure_z": 3.3, "series": [{"date": f"2026-10-{14 + k}", "sla_m": 0.5} for k in range(14)], "source": "NOAA", "dataset": "ssh"},
         "currents": {"available": True, "latest": {"u": 0.9, "v": 0.0, "date": "2026-10-26"}, "dataset_end": "2026-10-26", "source": "NOAA", "dataset": "cur"},
         "enso": {"available": True, "nino34_anomaly": 2.8, "latest_month": "2026-09", "dataset_end": "2026-09", "oni": {"value": 2.16, "season": "JAS 2026"}, "source": "CPC", "dataset": "sstoi"},
         "sources": {k: {"status": "ok"} for k in ("winds", "heat_flux", "sea_level", "currents", "enso")}}
    d.update(over)
    return d


def test_the_equatorial_case_has_several_consistent_indicators_but_is_never_called_attributed():
    r = pa.analyse(DRV(), _ctx())
    v = {m["id"]: m["verdict"] for m in r["mechanisms"]}
    assert v["wind"] == "consistent" and v["upwelling"] == "consistent" and v["sea_level"] == "consistent" and v["enso"] == "consistent" and v["heat_flux"] == "not assessable" and v["advection"] == "not assessable"
    assert r["confidence"]["level"] == "moderate (plausible mechanisms)" and "2 independent lines of evidence" in r["confidence"]["text"] and "not attribution" in r["confidence"]["text"]
    assert "wind field (CCMP)" in r["confidence"]["text"] and "satellite altimetry" in r["confidence"]["text"] and r["confidence"]["attribution"] == "No causal attribution is made."
    text = json.dumps(r, ensure_ascii=False).lower()
    for bad in ("cause established", "caused by", "proves that", "was caused", "is caused"):
        assert bad not in text, bad


def test_wind_and_upwelling_count_as_one_line_of_evidence():
    r = pa.analyse(DRV(sea_level={"available": False, "message": "none"}), _ctx())
    assert r["confidence"]["level"] == "limited" and "Only one line of evidence (wind field (CCMP))" in r["confidence"]["text"]


def test_conflicting_indicators_give_mixed_confidence_and_name_both_sides():
    r = pa.analyse(DRV(sea_level={"available": True, "recent_mean_m": -0.2, "change_m": 0.0, "latest": {"date": "2026-10-27"}, "dataset_end": "2026-10-27", "series": [], "baseline": {"years": [2016, 2017], "mean_m": 0.0, "sd_m": 0.05}, "departure_m": -0.2, "departure_z": -4.0}), _ctx())
    assert r["confidence"]["level"] == "mixed" and "satellite altimetry" in r["confidence"]["text"] and "wind field (CCMP)" in r["confidence"]["text"]
    sl = next(m for m in r["mechanisms"] if m["id"] == "sea_level")
    assert sl["verdict"] == "not consistent" and sl["evidence_against"] and not sl["evidence_for"]


def test_missing_sources_are_reported_as_unavailable_and_nothing_is_filled_in():
    r = pa.analyse(DRV(winds={"available": False, "message": "no wind"}, sea_level=None, currents=None, enso=None, sources={"winds": {"status": "no_data"}, "heat_flux": {"status": "ok"}}), _ctx())
    assert {m["id"]: m["verdict"] for m in r["mechanisms"]}["wind"] == "not assessable"
    st = {s["id"]: s["status"] for s in r["sources"]}
    assert st["winds"] == "no_data" and st["sea_level"] == "unavailable" and st["enso"] == "unavailable"
    assert r["confidence"]["level"] == "limited" and "could not be assessed" in r["confidence"]["text"]
    assert all(d["value"] is not None for m in r["mechanisms"] for d in m["data"])                             # no value is ever a placeholder


def test_a_source_far_behind_the_sst_is_marked_stale_with_its_lag():
    old = DRV()
    old["winds"]["dataset_end"] = "2026-03-05"
    old["winds"]["latest_date"] = "2026-03-05"
    r = pa.analyse(old, _ctx())
    s = next(x for x in r["sources"] if x["id"] == "winds")
    assert s["status"] == "stale" and s["lag_days_behind_sst"] == 236


def test_a_small_sst_anomaly_has_nothing_to_attribute():
    r = pa.analyse(DRV(), _ctx(a=0.2))
    assert r["confidence"]["level"] == "not applicable" and all(m["verdict"] in ("inconclusive", "not assessable") for m in r["mechanisms"])


def test_dates_of_the_observation_the_drivers_and_the_forecast_are_kept_apart():
    r = pa.analyse(DRV(), _ctx())
    d = r["forecast_relationship"]["dates"]
    assert d["sst_observation"] == "2026-10-27" and d["forecast_issued_from"] == "2026-10-27" and d["forecast_valid"] == ["2026-10-28", "2026-11-03"]
    assert d["drivers"]["winds"] == {"label": "Winds (CCMP)", "observation_date": "2026-10-27", "lag_days_behind_sst": 0}
    assert d["drivers"]["currents"]["lag_days_behind_sst"] == 1 and d["drivers"]["heat_flux"]["observation_date"] == "climatology" and d["drivers"]["enso"]["lag_days_behind_sst"] is None
    text = " ".join(r["forecast_relationship"]["statements"])
    assert "not forecasts of winds, currents or fluxes" in text and "does not establish causation" in text and "did not use any of these variables" in text


def test_the_physical_evidence_is_compared_with_the_forecast_direction_without_claiming_cause():
    cooling = pa.analyse(DRV(), _ctx(reading=fr_reading((30.0, 29.2), (2.0, 1.0))))["forecast_relationship"]
    assert "the physical evidence does not clearly agree" in " ".join(cooling["statements"]) and cooling["agreement"] == "not clearly consistent"
    warming = pa.analyse(DRV(), _ctx(reading=fr_reading((30.0, 30.6), (2.0, 2.4))))["forecast_relationship"]
    assert warming["agreement"] == "directionally consistent" and "directionally consistent with them" in " ".join(warming["statements"])
    stable = pa.analyse(DRV(), _ctx(reading=fr_reading((30.0, 30.0), (2.0, 2.0))))["forecast_relationship"]
    assert "neither supports nor contradicts" in " ".join(stable["statements"])


def test_the_chart_series_are_aligned_by_date_and_leave_gaps_as_none():
    r = pa.analyse(DRV(), _ctx())
    s = r["series"]
    assert len(s["dates"]) == 14 and s["dates"] == sorted(s["dates"]) and len(s["wind_speed_ms"]) == 14
    d = DRV()
    d["sea_level"]["series"] = [{"date": "2026-10-20", "sla_m": 0.4}]
    s2 = pa.analyse(d, _ctx())["series"]
    assert s2["sea_level_anomaly_m"].count(None) == 13 and s2["sea_level_anomaly_m"][s2["dates"].index("2026-10-20")] == 0.4


def test_each_region_of_the_pacific_gets_its_own_assessment():
    west = pa.analyse(DRV(), _ctx(lat=10.0, lon=150.0))
    central = pa.analyse(DRV(), _ctx(lat=0.0, lon=-170.0))
    east = pa.analyse(DRV(), _ctx(lat=-5.0, lon=-95.0))
    en = lambda r: next(m for m in r["mechanisms"] if m["id"] == "enso")["verdict"]                          # noqa: E731
    assert en(west) == "inconclusive" and en(central) == "consistent" and en(east) == "consistent"


# ------------------------------------------------------------------------------------------------ the report and the endpoint
def _payload():
    return DRV()


def test_the_report_matches_the_drivers_to_the_sst_and_forecast_dates(client, h, pac, monkeypatch):  # noqa: F811
    from app.services import physical_report as prp
    monkeypatch.setattr(prp.pdv, "location_drivers", lambda lat, lon, wait_s=6.0, d=None: _payload())
    r = client.get("/api/environment/physical-drivers", params={"dataset": "pacific", "lat": -10, "lon": 122}, headers=h).json()
    assert r["available"] and r["observed"]["date"] == P.LATEST and r["observed"]["anomaly_c"] is not None
    d = r["forecast_relationship"]["dates"]
    assert d["sst_observation"] == P.LATEST == d["forecast_issued_from"] and d["forecast_valid"][0] > P.LATEST
    assert {m["id"] for m in r["mechanisms"]} == {"wind", "heat_flux", "advection", "upwelling", "sea_level", "enso"}
    assert r["confidence"]["attribution"] == "No causal attribution is made." and len(r["sources"]) == 6 and r["method"]


def test_the_report_degrades_when_the_drivers_are_unavailable_and_never_breaks_the_forecast(client, h, pac, monkeypatch):  # noqa: F811
    from app.services import physical_report as prp
    monkeypatch.setattr(prp.pdv, "location_drivers", lambda lat, lon, wait_s=6.0, d=None: {"status": "unavailable", "sources": {}})
    r = client.get("/api/environment/physical-drivers", params={"dataset": "pacific", "lat": -10, "lon": 122}, headers=h)
    assert r.status_code == 200 and r.json()["available"] is False and "could not be reached" in r.json()["message"]
    monkeypatch.setattr(prp.pdv, "location_drivers", lambda lat, lon, wait_s=6.0, d=None: {"status": "refreshing", "sources": {}})
    j = client.get("/api/environment/physical-drivers", params={"dataset": "pacific", "lat": -10, "lon": 122}, headers=h).json()
    assert j["available"] is False and j["status"] == "refreshing" and j["refresh_hint_s"] == 12
    monkeypatch.setattr(prp.pdv, "location_drivers", lambda *a, **k: None)
    assert client.get("/api/environment/physical-drivers", params={"dataset": "pacific", "lat": -10, "lon": 122}, headers=h).json()["status"] == "disabled"
    assert client.get("/api/environment/forecast", params={"dataset": "pacific"}, headers=h).status_code == 200               # the forecast does not depend on the drivers


def test_land_outside_and_invalid_locations_are_handled(client, h, pac, monkeypatch):  # noqa: F811
    from app.services import physical_report as prp
    monkeypatch.setattr(prp.pdv, "location_drivers", lambda *a, **k: _payload())
    land = client.get("/api/environment/physical-drivers", params={"dataset": "pacific", "lat": 50, "lon": 110}, headers=h).json()
    assert land["available"] is False and land["status"] == "land"
    assert client.get("/api/environment/physical-drivers", params={"dataset": "pacific", "lat": 95, "lon": 0}, headers=h).status_code == 422


def test_the_two_sides_of_the_dateline_are_neighbours_in_the_report(client, h, pac, monkeypatch):  # noqa: F811
    from app.services import physical_report as prp
    seen = []
    monkeypatch.setattr(prp.pdv, "location_drivers", lambda lat, lon, wait_s=6.0, d=None: seen.append((lat, lon)) or _payload())
    a = client.get("/api/environment/physical-drivers", params={"dataset": "pacific", "lat": 10, "lon": 179}, headers=h).json()
    b = client.get("/api/environment/physical-drivers", params={"dataset": "pacific", "lat": 10, "lon": -179}, headers=h).json()
    assert a["available"] and b["available"] and abs(((seen[1][1] - seen[0][1] + 180) % 360) - 180) < 8 and seen[0][1] > 0 > seen[1][1]
    assert pa.enso_region(10, a["cell"]["lon"]) and pa.enso_region(10, b["cell"]["lon"])                       # both lie in the ENSO region, on either side of 180


def test_the_heat_flux_window_starts_with_the_forecast_week_and_the_cache_is_per_day(client, h, pac, monkeypatch):  # noqa: F811
    from app.services import physical_report as prp
    seen = []
    monkeypatch.setattr(prp.pdv, "location_drivers", lambda lat, lon, wait_s=6.0, d=None: seen.append(d) or _payload())
    client.get("/api/environment/physical-drivers", params={"dataset": "pacific", "lat": -10, "lon": 122}, headers=h)
    assert seen == [date.fromisoformat(P.LATEST) + timedelta(days=1)]
    assert pdv.cache_key(0.0, -150.0, date(2026, 10, 28)) != pdv.cache_key(0.0, -150.0, date(2026, 10, 29))


def test_an_advective_tendency_that_is_not_interpreted_is_not_displayed():
    cur = {"available": True, "latest": {"u": 0.9, "v": 0.0, "date": "2026-10-26"}}
    adv = {"dTdx_c_per_m": 1e-5, "dTdy_c_per_m": 0.0, "date": "2026-10-27"}
    eq = pa.advection_mechanism(cur, adv, 0.03, 0.5, 2.0)
    assert eq["verdict"] == "not assessable" and not any(d["label"].startswith("Advective") for d in eq["data"])
    off = pa.advection_mechanism(cur, adv, 0.03, 20.0, 2.0)
    assert any(d["label"].startswith("Advective") for d in off["data"])


# ------------------------------------------------------------------------------------------------ NASA POWER radiation and the bulk heat-flux estimate
def _power_payload(sw=6.0, lw=11.0, t2m=27.0, q=18.0, ps=101.0, end=date(2026, 10, 19), missing_tail=0, years=range(2016, 2027), shift=None):
    """A POWER-style JSON: radiation in kW-hr/m^2/day and the -999 fill value for missing days. `shift` changes the recent week relative to the earlier years."""
    out = {k: {} for k in ("ALLSKY_SFC_SW_DWN", "ALLSKY_SFC_LW_DWN", "T2M", "QV2M", "PS")}
    d = date(2016, 1, 1)
    while d <= date(2026, 10, 29):
        k = d.strftime("%Y%m%d")
        recent = end - timedelta(days=6) <= d <= end
        miss = d > end - timedelta(days=missing_tail)
        vals = (sw + (shift or {}).get("sw", 0) * recent, lw + (shift or {}).get("lw", 0) * recent, t2m + (shift or {}).get("t2m", 0) * recent, q + (shift or {}).get("q", 0) * recent, ps)
        for name, v in zip(out, vals):
            out[name][k] = pdv.POWER_FILL if (d > end or miss or d.year not in years) else v
        d += timedelta(days=1)
    return {"properties": {"parameter": out}}


def test_power_days_convert_units_and_never_use_the_fill_value(monkeypatch):
    days = pdv._power_days(_power_payload())
    assert days["2026-10-19"]["sw"] == pytest.approx(6.0 * 1000 / 24) and days["2026-10-19"]["lw"] == pytest.approx(11.0 * 1000 / 24) and days["2026-10-19"]["t2m"] == 27.0
    assert "2026-10-20" not in days and "2026-10-29" not in days                                                    # the fill value (-999) marks a missing day
    p = _power_payload()
    p["properties"]["parameter"]["T2M"]["20261018"] = pdv.POWER_FILL                                              # one variable missing: the day is not used at all
    assert "2026-10-18" not in pdv._power_days(p)


def test_power_met_reports_the_last_valid_day_the_recent_week_and_the_baseline(monkeypatch):
    monkeypatch.setattr(pdv, "_power_json", lambda *a, **k: _power_payload(shift={"sw": -1.0, "lw": 0.5, "t2m": 2.0, "q": 1.5}))
    r = pdv.power_met(0.0, -150.0, date(2026, 10, 28))
    assert r["available"] and r["dataset_end"] == "2026-10-19" and r["window"] == {"start": "2026-10-13", "end": "2026-10-19"} and r["valid_days"] == 7
    assert r["recent"]["sw"] == pytest.approx(5.0 * 1000 / 24, abs=0.01) and r["baseline"]["years"] == list(range(2016, 2026))
    assert r["anomaly"]["sw"] == pytest.approx(-1000 / 24, abs=0.01) and r["anomaly"]["t2m"] == pytest.approx(2.0) and r["anomaly"]["q"] == pytest.approx(1.5)
    assert "not in-situ" in r["kind"] and r["temporal_resolution"] == "daily"


def test_a_week_with_too_many_missing_days_is_unavailable_not_filled(monkeypatch):
    p = _power_payload()
    for d in (14, 16, 18):                                                                                      # three scattered gaps in the week: only four valid days
        p["properties"]["parameter"]["ALLSKY_SFC_SW_DWN"][f"202610{d}"] = pdv.POWER_FILL
    monkeypatch.setattr(pdv, "_power_json", lambda *a, **k: p)
    r = pdv.power_met(0.0, -150.0, date(2026, 10, 28))
    assert r["available"] is False and "Fewer than 6 valid days" in r["message"] and r["dataset_end"] == "2026-10-19"
    q = _power_payload()
    for d in range(14, 20):                                                                                     # the newest days are missing: the data END moves back, nothing is carried forward
        q["properties"]["parameter"]["ALLSKY_SFC_SW_DWN"][f"202610{d}"] = pdv.POWER_FILL
    monkeypatch.setattr(pdv, "_power_json", lambda *a, **k: q)
    moved = pdv.power_met(0.0, -150.0, date(2026, 10, 28))
    assert moved["available"] and moved["dataset_end"] == "2026-10-13"
    monkeypatch.setattr(pdv, "_power_json", lambda *a, **k: {"properties": {"parameter": {k: {} for k in ("ALLSKY_SFC_SW_DWN", "ALLSKY_SFC_LW_DWN", "T2M", "QV2M", "PS")}}})
    assert pdv.power_met(0.0, -150.0)["available"] is False


def test_power_request_uses_the_documented_api_and_the_signed_longitude(monkeypatch):
    seen = {}

    class R:
        status_code = 200
        def json(self): return _power_payload()
    monkeypatch.setattr(pdv.requests, "get", lambda url, params=None, **k: seen.update(url=url, params=params) or R())
    pdv._power_json(10.0, 181.0, "20160101", "20261028")
    assert seen["url"].startswith("https://power.larc.nasa.gov/api/temporal/daily/point") and seen["params"]["longitude"] == -179.0 and seen["params"]["community"] == "RE" and "QV2M" in seen["params"]["parameters"]


def test_saturation_humidity_and_bulk_fluxes_have_realistic_magnitudes():
    assert pdv._qsat(30.0, 1010.0) == pytest.approx(0.0265, abs=0.0006)                                            # about 26.5 g/kg at 30 C
    lh, sh = pdv._bulk(30.0, 6.0, 28.0, 19.0, 101.0)
    assert 80 < lh < 220 and 0 < sh < 20
    lh2, _ = pdv._bulk(30.0, 3.0, 28.0, 19.0, 101.0)
    assert lh2 == pytest.approx(lh / 2, rel=0.01)                                                                  # evaporation scales with the wind speed
    assert pdv._bulk(20.0, 5.0, 25.0, 12.0, 101.0)[1] < 0                                                         # warmer air over cooler water: the ocean gains sensible heat


def _rad(**shift):
    r = pdv.power_met.__wrapped__ if hasattr(pdv.power_met, "__wrapped__") else None
    base = {"sw": 240.0, "lw": 430.0, "t2m": 27.0, "q": 18.0, "ps": 101.0}
    rec = {k: base[k] + shift.get(k, 0.0) for k in base}
    return {"available": True, "dataset_end": "2026-10-19", "window": {"start": "2026-10-13", "end": "2026-10-19"}, "recent": rec,
            "baseline": {"years": list(range(2016, 2026)), **{k: {"mean": base[k], "sd": 5.0} for k in base}}, "anomaly": {k: shift.get(k, 0.0) for k in ("sw", "lw", "t2m", "q")}}


def _wind_window(speed=6.0, base=6.0):
    return {"available": True, "window": {"start": "2026-10-13", "end": "2026-10-19"}, "valid_days": 7, "recent": {"speed": speed}, "baseline": {"speed": {"mean": base, "sd": 1.0}, "years": list(range(2016, 2026))}}


def _wind(speed=6.0, base=6.0):
    return {"available": True, "recent": {"speed": speed}, "baseline": {"speed": {"mean": base, "sd": 1.0}}}


def test_the_flux_anomaly_is_zero_for_an_unchanged_atmosphere_over_an_unchanged_sst():
    f = pdv.bulk_flux_anomaly(_rad(), _wind(), 28.0, 28.0)
    assert f["net_anomaly_wm2"] == pytest.approx(0.0, abs=1e-6) and f["radiative_part_wm2"] == pytest.approx(0.0, abs=1e-6)


def test_more_sunshine_heats_and_a_warm_surface_damps():
    sunny = pdv.bulk_flux_anomaly(_rad(sw=50.0), _wind(), 28.0, 28.0)
    assert sunny["shortwave_net_wm2"] == pytest.approx(47.0) and sunny["net_anomaly_wm2"] == pytest.approx(47.0, abs=0.01)
    warm = pdv.bulk_flux_anomaly(_rad(), _wind(), 31.0, 28.0)                                                      # the same atmosphere over water 3 degrees warmer than normal
    assert warm["net_anomaly_wm2"] < -20 and warm["surface_response_wm2"] == warm["net_anomaly_wm2"] and warm["longwave_up_wm2"] > 15
    windy = pdv.bulk_flux_anomaly(_rad(), _wind(speed=9.0), 28.0, 28.0)
    assert windy["latent_loss_wm2"] > 20 and windy["net_anomaly_wm2"] < -20                                          # stronger wind: more evaporative loss


def test_the_flux_anomaly_needs_every_input_and_invents_nothing():
    assert pdv.bulk_flux_anomaly(None, _wind(), 28.0, 28.0) is None and pdv.bulk_flux_anomaly(_rad(), None, 28.0, 28.0) is None
    r = _rad()
    r.pop("baseline")
    assert pdv.bulk_flux_anomaly(r, _wind(), 28.0, 28.0) is None and pdv.bulk_flux_anomaly(_rad(), _wind(), None, 28.0) is None
    assert pdv.bulk_flux_anomaly(_rad(), _wind(), float("nan"), 28.0) is None


def test_heat_flux_verdicts_follow_the_sign_of_the_anomaly_and_say_when_the_surface_is_damping_it():
    sunny = pa.heat_flux_mechanism({"available": True, "net": [90.0] * 8, "start_date": "d"}, +1.5, None, pdv.bulk_flux_anomaly(_rad(sw=80.0), _wind(), 28.0, 28.0), _rad())
    assert sunny["verdict"] == "consistent" and sunny["favours"] == "warming" and "W/m²" in sunny["evidence_for"][0] and sunny["evidence_quality"] == "low"
    damp = pa.heat_flux_mechanism(None, +3.9, None, pdv.bulk_flux_anomaly(_rad(), _wind(), 31.0, 28.0), _rad())
    assert damp["verdict"] == "not consistent" and "damps rather than builds a warm anomaly" in " ".join(damp["evidence_against"]) and "other processes" in " ".join(damp["evidence_against"])
    cold_gain = pa.heat_flux_mechanism(None, -1.4, None, pdv.bulk_flux_anomaly(_rad(sw=-90.0), _wind(), 20.0, 21.4), _rad(sw=-90.0))
    assert cold_gain["verdict"] in ("consistent", "inconclusive", "not consistent") and any(d["label"].startswith("Net surface heat-flux anomaly") for d in cold_gain["data"])
    small = pa.heat_flux_mechanism(None, +1.5, None, pdv.bulk_flux_anomaly(_rad(sw=3.0), _wind(), 28.0, 28.0), _rad())
    assert small["verdict"] == "inconclusive" and "not interpreted" in " ".join(small["evidence_against"])
    mixed = pa.heat_flux_mechanism(None, +2.0, None, pdv.bulk_flux_anomaly(_rad(sw=60.0), _wind(), 31.5, 28.0), _rad(sw=60.0))
    assert mixed["verdict"] == "not consistent" and any("radiative part alone" in t for t in mixed["evidence_for"])           # sunshine favoured warming, the warm surface's response outweighed it
    assert pa.heat_flux_mechanism(None, 1.0, None, None, {"message": "gone"})["verdict"] == "not assessable"


def test_the_radiation_source_is_listed_with_its_own_lag_and_status():
    d = DRV(radiation={"available": True, "dataset_end": "2026-10-19", "window": {"start": "2026-10-13", "end": "2026-10-19"}, "recent": _rad()["recent"], "baseline": _rad()["baseline"], "source": "NASA POWER", "dataset": "POWER daily", "kind": "analysis", "wind_window": _wind_window()})
    d["sources"]["radiation"] = {"status": "ok"}
    r = pa.analyse(d, _ctx(window_sst={"sst": 30.0, "normal": 28.0, "start": "2026-10-13", "end": "2026-10-19", "days": 7}))
    s = next(x for x in r["sources"] if x["id"] == "radiation")
    assert s["status"] == "ok" and s["lag_days_behind_sst"] == 8 and s["label"].startswith("Surface radiation and humidity")
    assert r["forecast_relationship"]["dates"]["drivers"]["radiation"]["lag_days_behind_sst"] == 8 and r["flux"] is not None
