"""Correctness and honesty of the physical-driver analysis: alignment of the dates actually used, sign conventions, the equator, units and wording. Each test pins a problem found in review."""
import json
from datetime import date, datetime

import pytest

from app.services import ocean_context as oc
from app.services import physical_analysis as pa
from app.services import physical_drivers as pdv
from app.services import physical_interpretation as pi
from app.tests.test_physical_drivers import DRV, W, _ctx, _rad, _wind_window
from app.tests.test_physical_interpretation import make


# ------------------------------------------------------------------------------------------------ advection: the verdict is about the anomaly
CUR = {"available": True, "latest": {"u": 0.2, "v": 0.0, "date": "2026-10-26"}}
GRAD_WARMING = {"dTdx_c_per_m": -1e-5, "dTdy_c_per_m": 0.0, "date": "2026-10-27"}        # -u dT/dx = +0.173 C/day: the current brings warmer water
GRAD_COOLING = {"dTdx_c_per_m": 1e-5, "dTdy_c_per_m": 0.0, "date": "2026-10-27"}


def test_advection_that_warms_is_consistent_with_a_warm_anomaly_and_against_a_cold_one():
    warm = pa.advection_mechanism(CUR, GRAD_WARMING, +0.05, 20.0, +2.0)
    cold = pa.advection_mechanism(CUR, GRAD_WARMING, -0.05, 20.0, -2.0)
    assert warm["verdict"] == "consistent" and warm["favours"] == "warming"
    assert cold["verdict"] == "not consistent" and not cold["evidence_for"] and "opposite to the cold anomaly" in " ".join(cold["evidence_against"])


def test_advection_that_cools_a_warm_anomaly_is_not_called_consistent_even_when_the_sst_is_falling():
    """Before the review the verdict compared the tendency with the SST TREND only, so a cooling tendency over a falling SST was 'consistent' with a warm anomaly."""
    m = pa.advection_mechanism(CUR, GRAD_COOLING, -0.05, 20.0, +2.0)
    assert m["verdict"] == "not consistent" and m["favours"] == "cooling" and not m["evidence_for"]
    assert "same sign" in " ".join(m["evidence_against"])                                     # the relation to the trend is still reported, as a separate fact


def test_the_advection_caveat_says_that_normal_advection_is_included():
    m = pa.advection_mechanism(CUR, GRAD_WARMING, +0.05, 20.0, +2.0)
    assert "normal advection" in m["caveat"] and "anomalous current" in m["caveat"]
    assert pa.advection_mechanism(CUR, GRAD_WARMING, +0.05, 20.0, +0.1)["verdict"] == "inconclusive"


def test_the_narrator_does_not_say_the_current_matches_a_trend_it_may_not_match():
    pkg, _ = make(a=2.0, drv=DRV(currents=CUR), advection=GRAD_WARMING, lat=20.0)
    out = pi.narrate(pkg)
    text = json.dumps(out)
    assert "matching the warming trend" not in text
    adv = [m for m in out["mechanisms"] if m["id"] == "advection"]
    assert all("in the direction of the warm anomaly" in m["explanation"] for m in adv)


def test_the_equator_boundary_is_the_same_for_every_current_and_upwelling_rule():
    assert pa.advection_mechanism(CUR, GRAD_WARMING, 0.05, 2.9, 2.0)["verdict"] == "not assessable"
    assert pa.advection_mechanism(CUR, GRAD_WARMING, 0.05, 3.0, 2.0)["verdict"] == "consistent"
    assert pdv.ekman_transport(2.9, 0.1, 0.0) is None and pdv.ekman_transport(3.0, 0.1, 0.0) is not None
    at3 = pa.upwelling_mechanism(W(), 2.0, 3.0, None)
    assert "equatorial" not in at3["caveat"].lower() and "Ekman" in json.dumps(at3["data"])      # exactly 3 degrees is treated as off the equator by every rule


# ------------------------------------------------------------------------------------------------ equatorial upwelling needs an easterly normal
def test_a_weaker_stress_is_upwelling_evidence_only_where_the_normal_stress_is_easterly():
    easterly = pa.upwelling_mechanism(W(taux_z=2.5), 2.0, 0.0, None)
    assert easterly["verdict"] == "consistent"
    westerly = W(taux_z=2.5)
    westerly["baseline"]["taux"]["mean"] = +0.03                                              # a warm-pool longitude with a westerly normal
    m = pa.upwelling_mechanism(westerly, 2.0, 0.0, None)
    assert m["verdict"] == "not assessable" and "not clearly easterly" in m["caveat"]


# ------------------------------------------------------------------------------------------------ sea level: relative to the same days of other years
def sla(dep_m=0.07, z=2.3, mean=0.12):
    return {"available": True, "recent_mean_m": mean, "change_m": 0.0, "latest": {"date": "2026-10-27"}, "window": {"start": "2026-10-21", "end": "2026-10-27"},
            "baseline": {"years": list(range(2016, 2026)), "mean_m": mean - dep_m, "sd_m": 0.03}, "departure_m": dep_m, "departure_z": z}


def test_a_high_sea_level_that_is_normal_for_the_season_is_not_evidence_for_a_warm_anomaly():
    """The altimetry product keeps the seasonal cycle: +12 cm can be an ordinary autumn value."""
    m = pa.sea_level_mechanism(sla(dep_m=0.005, z=0.2, mean=0.12), +2.0)
    assert m["verdict"] == "inconclusive" and "normal range for the season" in " ".join(m["evidence_against"])
    assert pa.sea_level_mechanism(sla(), +2.0)["verdict"] == "consistent"


def test_without_the_same_week_baseline_a_raw_sea_level_is_not_interpreted():
    s = sla()
    s.pop("baseline")
    s.pop("departure_m")
    s.pop("departure_z")
    m = pa.sea_level_mechanism({**s, "baseline_message": "only 2 of 10 baseline years"}, +2.0)
    assert m["verdict"] == "inconclusive" and not m["evidence_for"] and "seasonal cycle" in m["caveat"]


def test_sea_level_uses_seven_calendar_days_and_says_so_when_the_week_has_gaps(monkeypatch):
    monkeypatch.setattr(oc, "_last_time", lambda base, ds: date(2026, 10, 27))
    days = {f"2026-10-{d:02d}": 0.1 for d in range(1, 21)} | {"2026-10-26": 0.3}                # one valid day in the last 7 days
    monkeypatch.setattr(pdv, "_sla_rows", lambda lat, lon, t0, t1: days)
    out = pdv.sea_level(0.0, -150.0)
    assert out["available"] is False and "Fewer than 4 valid sea level days" in out["message"]
    days.update({"2026-10-24": 0.3, "2026-10-25": 0.3, "2026-10-27": 0.3})
    monkeypatch.setattr(pdv, "_sla_baseline", lambda lat, lon, end: {"years": list(range(2016, 2026)), "mean": 0.1, "sd": 0.05})
    out = pdv.sea_level(0.0, -150.0)
    assert out["available"] and out["recent_days"] == 4 and out["recent_mean_m"] == pytest.approx(0.3) and out["window"] == {"start": "2026-10-21", "end": "2026-10-27"}
    assert out["departure_m"] == pytest.approx(0.2) and out["departure_z"] == pytest.approx(4.0) and "seasonal cycle is not removed" in out["kind"]


def test_the_sea_level_baseline_needs_enough_years_and_failures_do_not_break_the_source(monkeypatch):
    monkeypatch.setattr(pdv, "_sla_rows", lambda lat, lon, t0, t1: {"2026-01-01": 0.1})        # too few days in every year
    b = pdv._sla_baseline(9.0, -140.0, date(2026, 10, 27))
    assert "mean" not in b and "only 0 of 10" in b["insufficient"]

    def boom(*a):
        raise RuntimeError("down")
    monkeypatch.setattr(oc, "_last_time", lambda base, ds: date(2026, 10, 27))
    monkeypatch.setattr(pdv, "_sla_rows", lambda lat, lon, t0, t1: {f"2026-10-{d:02d}": 0.1 for d in range(1, 28)})
    monkeypatch.setattr(pdv, "_sla_baseline", boom)
    out = pdv.sea_level(0.0, -150.0)
    assert out["available"] and "could not be retrieved" in out["baseline_message"] and "departure_m" not in out


# ------------------------------------------------------------------------------------------------ the dates that are actually used
def test_the_wind_baseline_ends_on_the_last_complete_day_not_the_last_analysis_time(monkeypatch):
    end = "2026-10-27T06:00:00Z"                                                                  # the newest analysis exists, but its day has only two analyses
    monkeypatch.setattr(oc, "_csv", lambda url: [{"time": end}])
    days = [{"date": f"2026-10-{13 + k}", "speed": 5.0, "u": -5.0, "v": 0.0, "taux": -0.03, "tauy": 0.0} for k in range(14)]            # complete days to 2026-10-26
    monkeypatch.setattr(pdv, "_wind_query", lambda *a: days)
    seen = []
    base = {"fetched_at": "x", "years": [2016], "window": "w", "dataset": "d", "speed": {"mean": 5.0, "sd": 1.0}, "u": {"mean": -5.0, "sd": 1.0}, "v": {"mean": 0.0, "sd": 1.0}, "taux": {"mean": -0.03, "sd": 0.01}, "tauy": {"mean": 0.0, "sd": 0.01}}
    monkeypatch.setattr(pdv, "_wind_baseline", lambda lat, lon, e: seen.append(e) or base)
    w = pdv.winds(0.0, -150.0)
    assert w["latest_date"] == "2026-10-26" and seen[0].date() == date(2026, 10, 26)


def test_the_source_table_reports_the_day_actually_used_and_the_lag_from_that_day():
    d = DRV()
    d["winds"]["dataset_end"] = "2026-10-27"
    d["winds"]["latest_date"] = "2026-10-24"
    d["sea_level"]["dataset_end"] = "2026-10-27"
    d["sea_level"]["latest"] = {"date": "2026-10-20"}
    r = pa.analyse(d, _ctx())
    by = {s["id"]: s for s in r["sources"]}
    assert by["winds"]["dataset_end"] == "2026-10-27" and by["winds"]["used_through"] == "2026-10-24" and by["winds"]["lag_days_behind_sst"] == 3
    assert by["sea_level"]["used_through"] == "2026-10-20" and by["sea_level"]["lag_days_behind_sst"] == 7
    assert r["forecast_relationship"]["dates"]["drivers"]["sea_level"]["lag_days_behind_sst"] == 7


# ------------------------------------------------------------------------------------------------ the heat-flux estimate: one week, no invented error
def radiation_with_wind():
    rad = {"available": True, "dataset_end": "2026-10-19", "window": {"start": "2026-10-13", "end": "2026-10-19"}, "recent": _rad()["recent"], "baseline": _rad()["baseline"], "source": "NASA POWER", "dataset": "POWER daily", "kind": "analysis"}
    return rad


def test_the_flux_estimate_is_not_made_without_the_sst_and_wind_of_the_radiation_week():
    rad = radiation_with_wind()
    ctx = _ctx()                                                                                  # no SST of the radiation days
    r = pa.analyse(DRV(radiation={**rad, "wind_window": _wind_window()}), ctx)
    assert r["flux"] is None and next(m for m in r["mechanisms"] if m["id"] == "heat_flux")["verdict"] == "not assessable"
    r = pa.analyse(DRV(radiation={**rad, "wind_window": None}), _ctx(window_sst={"sst": 30.0, "normal": 28.0, "start": "2026-10-13", "end": "2026-10-19", "days": 7}))
    assert r["flux"] is None
    msg = next(m for m in r["mechanisms"] if m["id"] == "heat_flux")["caveat"]
    assert "wind of the same days" in msg or "same days" in msg
    ok = pa.analyse(DRV(radiation={**rad, "wind_window": _wind_window()}), _ctx(window_sst={"sst": 30.0, "normal": 28.0, "start": "2026-10-13", "end": "2026-10-19", "days": 7}))
    assert ok["flux"] is not None


def test_the_flux_uses_the_sst_of_the_radiation_week_not_the_sst_of_the_last_day():
    rad = {**radiation_with_wind(), "wind_window": _wind_window()}
    week = pa.analyse(DRV(radiation=rad), _ctx(sst=31.5, window_sst={"sst": 28.0, "normal": 28.0, "start": "2026-10-13", "end": "2026-10-19", "days": 7}))["flux"]
    assert week["sst_c"] == 28.0 and week["net_anomaly_wm2"] == pytest.approx(0.0, abs=1e-6)       # the last day's 31.5 C does not enter


def test_the_wind_of_the_radiation_window_is_fetched_with_its_own_baseline(monkeypatch):
    seen = {}
    days = [{"date": f"2026-10-{13 + k}", "speed": 7.0 + 0.1 * k, "u": -7.0, "v": 0.0, "taux": -0.05, "tauy": 0.0} for k in range(7)]
    monkeypatch.setattr(pdv, "_wind_query", lambda lat, lon, t0, t1: seen.update(t0=t0, t1=t1) or days + [{"date": "2026-10-25", "speed": 99.0, "u": 0, "v": 0, "taux": 0, "tauy": 0}])
    monkeypatch.setattr(pdv, "_wind_baseline", lambda lat, lon, e: seen.update(end=e) or {"speed": {"mean": 6.0, "sd": 1.0}, "years": [2016, 2017]})
    ww = pdv.wind_window(0.0, -150.0, date(2026, 10, 19))
    assert seen["t0"].startswith("2026-10-13") and seen["t1"].startswith("2026-10-19") and seen["end"].date() == date(2026, 10, 19)
    assert ww["recent"]["speed"] == pytest.approx(7.3) and ww["window"] == {"start": "2026-10-13", "end": "2026-10-19"}              # a day outside the window is not averaged in
    monkeypatch.setattr(pdv, "_wind_query", lambda *a: days[:3])
    assert pdv.wind_window(0.0, -150.0, date(2026, 10, 19)) is None


def test_no_unvalidated_error_bound_is_claimed_anywhere_in_the_output():
    r = pa.analyse(DRV(radiation={**radiation_with_wind(), "wind_window": _wind_window()}), _ctx(window_sst={"sst": 30.0, "normal": 28.0, "start": "2026-10-13", "end": "2026-10-19", "days": 7}))
    text = json.dumps(r, ensure_ascii=False).lower()
    for claim in ("order 10 w", "errors of order", "tens of w", "within the error", "uncertainty of the estimate"):
        assert claim not in text, claim
    hf = next(m for m in r["mechanisms"] if m["id"] == "heat_flux")
    assert "estimate" in hf["caveat"].lower() and "not validated" in hf["caveat"] and "not a measured flux" in hf["caveat"]
    assert any(d["kind"].startswith("derived") for d in hf["data"] if "anomaly" in d["label"].lower())             # labelled derived, never as a measurement
    assert all(d["kind"] != "measurement" for d in hf["data"])
    assert any("not been validated" in t for t in r["limitations"])


# ------------------------------------------------------------------------------------------------ the climatology across the new year
def test_the_heat_flux_climatology_window_can_cross_the_new_year(monkeypatch):
    calls = []

    def fake_dap(url):
        calls.append(url)
        var = url.split("?")[1].split("[")[0]
        if "ascii?lat" in url or "ascii?lon" in url:
            name = "lat" if "ascii?lat" in url else "lon"
            return f"{name}[3]\n" + ", ".join(["-1.0", "0.0", "1.0"] if name == "lat" else ["209.0", "210.0", "211.0"])
        a, b = (int(x) for x in url.split("?")[1].split("[")[1].rstrip("]").split(":1:"))
        n = b - a + 1
        sign = {"dswrf": 2.0, "uswrf": 1.0, "dlwrf": 3.0, "ulwrf": 1.0, "lhtfl": 1.0, "shtfl": 0.5}[var]
        return f"{var}.{var}[{n}][1][1]\n" + "\n".join(f"[{k}][0], {sign}" for k in range(n)) + "\n\n"
    monkeypatch.setattr(pdv, "_dap", fake_dap)
    pdv._grid_cache.clear()
    h = pdv.heat_flux_climatology(0.0, -150.0, date(2026, 12, 28), days=8)
    assert h["available"] and len(h["net"]) == 8 and h["net"][0] == pytest.approx(2 - 1 + 3 - 1 - 1 - 0.5)
    ranges = {u.split("[")[1].split("]")[0] for u in calls if "ascii?dswrf" in u}
    assert ranges == {"361:1:364", "0:1:3"}                                                       # 28-31 December, then 1-4 January


# ------------------------------------------------------------------------------------------------ evidence families, labels and rate limits
def test_sea_level_and_geostrophic_currents_are_one_altimetry_family_so_they_are_not_counted_twice():
    assert pa.FAMILY["sea_level"] == pa.FAMILY["advection"]
    mechs = [{"id": "sea_level", "verdict": "consistent"}, {"id": "advection", "verdict": "consistent"}, {"id": "wind", "verdict": "not assessable"}]
    c = pa.confidence(mechs, 2.0)
    assert c["level"] == "limited" and "single data source" in c["text"]                          # two altimetry indicators are one line of evidence


def test_an_altimetry_family_that_disagrees_with_itself_is_described_as_such():
    c = pa.confidence([{"id": "sea_level", "verdict": "consistent"}, {"id": "advection", "verdict": "not consistent"}, {"id": "wind", "verdict": "consistent"}], 2.0)
    assert c["level"] == "mixed" and "within satellite altimetry one indicator is consistent and another is not" in c["text"] and "wind field (CCMP) is consistent" in c["text"]


def test_the_upward_longwave_evaporative_and_sensible_terms_are_not_called_the_oceans_own_response():
    r = pa.analyse(DRV(radiation={**radiation_with_wind()} | {"wind_window": _wind_window(speed=4.0)}), _ctx(window_sst={"sst": 31.0, "normal": 28.0, "start": "2026-10-13", "end": "2026-10-19", "days": 7}))
    hf = next(m for m in r["mechanisms"] if m["id"] == "heat_flux")
    labels = " | ".join(d["label"] for d in hf["data"])
    assert "own response" not in labels and "depend on the SST, the wind and the air" in labels
    assert "own response" not in json.dumps(hf) and "ocean's own response" not in json.dumps(hf["caveat"])


def test_a_geostrophic_current_within_three_degrees_of_the_equator_is_shown_with_its_caveat():
    m = pa.advection_mechanism({"available": True, "latest": {"u": 1.2, "v": 0.0, "date": "2026-10-27"}}, GRAD_WARMING, 0.04, 0.1, 3.9)
    assert m["verdict"] == "not assessable" and m["data"][0]["label"] == "Geostrophic surface current (not reliable within 3° of the equator)"
    assert not any(d["label"].startswith("Advective") for d in m["data"])


def test_the_psl_requests_back_off_on_rate_limits_and_give_up_clearly(monkeypatch):
    calls = []

    class R:
        def __init__(self, code, text="", headers=None):
            self.status_code, self.text, self.headers = code, text, headers or {}
    seq = iter([R(429, headers={"Retry-After": "1"}), R(503), R(200, "ok")])
    monkeypatch.setattr(pdv.requests, "get", lambda *a, **k: calls.append(1) or next(seq))
    monkeypatch.setattr(pdv.time, "sleep", lambda s: None)
    assert pdv._dap("http://x") == "ok" and len(calls) == 3
    monkeypatch.setattr(pdv.requests, "get", lambda *a, **k: R(429))
    with pytest.raises(RuntimeError, match="HTTP 429"):
        pdv._dap("http://x")
    monkeypatch.setattr(pdv.requests, "get", lambda *a, **k: R(404))
    with pytest.raises(RuntimeError, match="HTTP 404"):
        pdv._dap("http://x")


def test_a_cached_payload_with_a_failed_source_is_retried_after_minutes_not_hours(monkeypatch, tmp_path):
    from datetime import timedelta, timezone
    monkeypatch.setattr(pdv, "ENABLED", True)
    monkeypatch.setattr(pdv, "cache_dir", lambda: tmp_path / "pd")
    pdv.clear_state()
    d = date(2026, 10, 28)
    calls = []

    def fake_build(lat, lon, day):
        calls.append(1)
        return {"schema": pdv.SCHEMA, "fetched_at": datetime.now(timezone.utc).isoformat(timespec="seconds"), "query": {}, "winds": {"available": True},
                "sources": {"winds": {"status": "ok"}, "heat_flux": {"status": "unavailable"}}}
    monkeypatch.setattr(pdv, "build", fake_build)
    first = pdv.location_drivers(0.375, -149.625, wait_s=5, d=d)
    assert first["status"] == "live" and len(calls) == 1
    again = pdv.location_drivers(0.375, -149.625, wait_s=5, d=d)
    assert again["status"] == "cached" and len(calls) == 1                                       # within the retry interval: served from the cache
    key = pdv.cache_key(0.375, -149.625, d)
    old = pdv._load(key)
    old["fetched_at"] = (datetime.now(timezone.utc) - timedelta(minutes=30)).isoformat(timespec="seconds")      # 30 minutes old: far inside the 12 h TTL
    pdv._save(key, old)
    pdv.location_drivers(0.375, -149.625, wait_s=5, d=d)
    assert len(calls) == 2                                                                        # the failed source is fetched again
    ok = {**old, "sources": {"winds": {"status": "ok"}, "heat_flux": {"status": "ok"}}}
    pdv._save(key, ok)
    pdv.location_drivers(0.375, -149.625, wait_s=5, d=d)
    assert len(calls) == 2                                                                        # a complete payload of the same age is still trusted
    pdv.clear_state()


# ------------------------------------------------------------------------------------------------ found in the browser QA pass
def test_a_bulk_flux_estimate_is_labelled_as_an_estimate_never_as_a_local_measurement():
    drv = DRV(radiation={**radiation_with_wind(), "wind_window": _wind_window(speed=4.0)})
    pkg, _ = make(a=2.5, drv=drv, window_sst={"sst": 30.0, "normal": 27.5, "start": "2026-10-13", "end": "2026-10-19", "days": 7})
    hf = next(m for m in pkg["mechanisms"] if m["id"] == "heat_flux")
    out = pi.narrate(pkg)
    kinds = {m["id"]: m["support"] for m in out["mechanisms"]}
    assert kinds.get("wind") == "local_measurements" and kinds.get("enso", "climate_context") == "climate_context"
    if hf["verdict"] == "consistent":
        assert kinds["heat_flux"] == "local_estimate"
    bad = {"id": "heat_flux", "name": "x", "support": "local_measurements", "explanation": "e", "evidence": [], "evidence_ids": hf["evidence_ids"] or ["E1"], "complications": []}
    forged = {**out, "mechanisms": [bad]}
    hf["verdict"] = "consistent"
    assert any("bulk estimate is never a measurement" in p for p in pi.validate(forged, pkg))
    wrong = {"id": "wind", "name": "x", "support": "local_estimate", "explanation": "e", "evidence": [], "evidence_ids": next(m for m in pkg["mechanisms"] if m["id"] == "wind")["evidence_ids"], "complications": []}
    assert any("never a measurement" in p for p in pi.validate({**out, "mechanisms": [wrong]}, pkg))


def test_an_error_sent_to_the_browser_names_a_missing_file_but_not_where_it_is_on_the_server():
    from app.services import forecast_explain as fe
    win = "FileNotFoundError: [Errno 2] No such file or directory: 'C:\\Users\\Angeline Lewis\\Documents\\proj\\processed_pacific\\model\\best_model.pt'"
    posix = "FileNotFoundError: [Errno 2] No such file or directory: '/home/ocean/proj/processed_pacific/model/best_model.pt'"
    for msg in (win, posix):
        out = fe._without_paths(msg)
        assert "best_model.pt" in out and "Users" not in out and "home" not in out and "Angeline" not in out and "processed_pacific" not in out
    assert fe._without_paths("ModuleNotFoundError: No module named 'torch'") == "ModuleNotFoundError: No module named 'torch'"
    assert fe._without_paths("the sensitivity run failed") == "the sensitivity run failed"
