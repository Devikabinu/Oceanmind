"""Location report: what is counted, which day each product refers to, the forecast explanation and the implications wording."""
from datetime import datetime, timezone

import numpy as np
import pytest

from app.services import forecast_explain as fe
from app.services import forecast_store
from app.tests import _forecast as F
from app.tests import _pacific as P
from app.tests._helpers import make_biodiversity_observation, make_dataset
from app.tests.test_pacific_product import get, h, pac, report  # noqa: F401  (fixtures)

H = 7


def fake_sensitivity(dataset, lat, lon):
    days = [f"2020-01-{14 + k}" for k in range(7)]
    return {
        "input_window": {"dates": days, "sst_c": [20 + 0.1 * k for k in range(7)], "climatology_c": [19.5] * 7, "anomaly_c": [0.5 + 0.1 * k for k in range(7)]},
        "forecast_c": [20.6 + 0.1 * k for k in range(H)],
        "sensitivity": {"temporal": {"days": days, "delta_c": [[0.01 * (d + 1)] * H for d in range(7)]}, "local_all_days_c": [0.2] * H, "everywhere_all_days_c": [0.3] * H,
                        "neighbourhood_deg": 8, "block_deg": 8,
                        "spatial": {"lat_edges": [-20, -12], "lon_edges": [100, 108], "delta_c": [[[0.1, None], [0.05, 0.02]] for _ in range(H)], "own_block": [0, 0]}},
    }


@pytest.fixture
def explain_ready(pac, monkeypatch):  # noqa: F811
    fe._cache.clear()
    return pac


# ------------------------------------------------------------------------------------------------ species counting
def test_species_count_is_labelled_and_scoped_to_the_place(client, h, pac, db_session):  # noqa: F811
    ds = make_dataset(db_session)
    for name, n in (("Alpha fish", 3), ("Beta whale", 2)):
        for _ in range(n):
            o = make_biodiversity_observation(db_session, ds, ts=datetime.now(timezone.utc), lat=-10, lon=122)
            o.scientific_name = name
    db_session.commit()
    sp = report(client, h, -10, 122).json()["species"]
    c = sp["counted"]
    assert c["observations"] == 5 and c["distinct_species"] == 2
    assert "Species observations" in c["label"] and "distinct species: 2" in c["label"] and "last 2 years" in c["label"]
    det = {d["factor"]: d for d in report(client, h, -10, 122).json()["risk"]["drivers"]}["overlap"]["evidence_detail"]
    assert det["observations"] == 5 and det["species"] == 2                                                         # the score and the species list count the same records


def test_no_biodiversity_observations_is_a_sampling_gap_not_zero_species(client, h, pac):  # noqa: F811
    sp = report(client, h, 30, 150).json()["species"]
    assert sp["counted"]["observations"] == 0 and sp["counted"]["label"].startswith("No stored biodiversity observations")
    assert "sampling gap, not absence" in sp["counted"]["label"] and sp["evidence"] == "insufficient_coverage"


def test_sparse_places_fall_back_to_regional_records_and_say_so(client, h, pac, db_session):  # noqa: F811
    ds = make_dataset(db_session)
    o = make_biodiversity_observation(db_session, ds, ts=datetime.now(timezone.utc), lat=-10, lon=129)             # 7 degrees from the clicked place: outside 3, inside 10
    o.scientific_name = "Distant fish"
    db_session.commit()
    sp = report(client, h, -10, 122).json()["species"]
    c = sp["counted"]
    assert c["scope"] == "regional" and c["radius_deg"] == 10.0 and c["observations"] == 1 and c["distinct_species"] == 1
    assert c["label"].startswith("Regional records") and "regional records" in sp["summary"]
    near = make_biodiversity_observation(db_session, ds, ts=datetime.now(timezone.utc), lat=-10, lon=123)
    near.scientific_name = "Near fish"
    db_session.commit()
    c2 = report(client, h, -10, 122).json()["species"]["counted"]
    assert c2["scope"] == "nearby" and c2["radius_deg"] == 3.0 and c2["observations"] == 1                          # nearby records are preferred; the regional ones are not mixed in


def test_old_records_are_used_only_as_a_labelled_historical_fallback(client, h, pac, db_session):  # noqa: F811
    ds = make_dataset(db_session)
    o = make_biodiversity_observation(db_session, ds, ts=datetime(2005, 1, 1, tzinfo=timezone.utc), lat=-10, lon=122)
    o.scientific_name = "Old fish"
    db_session.commit()
    c = report(client, h, -10, 122).json()["species"]["counted"]
    assert c["historical"] is True and c["observations"] == 1 and "older records included" in c["label"] and c["earliest_record"] == "2005-01-01"
    recent = make_biodiversity_observation(db_session, ds, ts=datetime.now(timezone.utc), lat=-10, lon=122)
    recent.scientific_name = "New fish"
    db_session.commit()
    c2 = report(client, h, -10, 122).json()["species"]["counted"]
    assert c2["historical"] is False and c2["observations"] == 1 and c2["scope"] == "nearby"                 # recent nearby records take precedence over old ones


# ------------------------------------------------------------------------------------------------ driver wording
def test_every_driver_states_why_it_is_or_is_not_in_the_score(client, h, pac):  # noqa: F811
    r = report(client, h, -10, 122).json()["risk"]
    ok = {"contributing", "below_threshold", "incomplete", "unavailable"}
    for d in r["drivers"]:
        assert d["status"] in ok and d["status_text"] and d["explanation"]
        if d["status"] == "unavailable":
            assert d["missing_input"] and d["value"] is None and d["contribution"] is None
        else:
            assert d["raw_unit"] and d["effective_weight"] > 0 and d["contribution"] is not None
    assert r["score_breakdown"]["sum"] == pytest.approx(r["score"], abs=0.002) and r["score_breakdown"]["text"]


def test_no_biodiversity_data_leaves_the_species_driver_out_and_says_which_input_is_missing(client, h, pac):  # noqa: F811
    d = {x["factor"]: x for x in report(client, h, 30, 150).json()["risk"]["drivers"]}["overlap"]
    assert d["status"] == "unavailable" and "biodiversity" in d["missing_input"] and d["contribution"] is None
    assert "renormalised" in d["status_text"] and "not treated as zero" in d["explanation"]


# ------------------------------------------------------------------------------------------------ dates
def test_data_dates_of_the_latest_day_are_aligned(client, h, pac):  # noqa: F811
    dd = report(client, h, -10, 122).json()["data_dates"]
    assert dd["aligned"] is True and dd["sst_observation"]["date"] == P.LATEST == dd["sst_observation"]["latest_available"]
    assert dd["forecast"]["initialised_from"] == P.LATEST and dd["forecast"]["valid_dates"][0] > P.LATEST and len(dd["forecast"]["valid_dates"]) == H
    assert dd["marine_heatwave"]["date"] == P.LATEST


def test_an_earlier_date_does_not_borrow_the_forecast_or_heatwave(client, h, pac):  # noqa: F811
    r = report(client, h, -10, 122, date="2020-01-05").json()
    assert r["forecast"]["available"] is False and r["forecast"]["issued_from"] == P.LATEST and "not from the selected date" in r["forecast"]["message"]
    assert r["data_dates"]["aligned"] is False and "2020-01-05" in r["data_dates"]["message"]


def test_stale_forecast_is_named_as_such(client, h, pac):  # noqa: F811
    F.build(pac, issued="2020-01-10")
    forecast_store._read.cache_clear()
    r = report(client, h, -10, 122).json()
    assert r["forecast"]["available"] is False and r["data_dates"]["forecast"]["initialised_from"] == "2020-01-10" and r["data_dates"]["aligned"] is False


def test_data_dates_endpoint(client, h, pac):  # noqa: F811
    d = get(client, h, "/api/environment/data-dates").json()
    assert d["dataset"] == "pacific" and d["sst_observation"]["latest_available"] == P.LATEST and "freshness" in d and "aligned" in d


# ------------------------------------------------------------------------------------------------ implications
def test_implications_are_cautious_and_labelled_by_kind(client, h, pac):  # noqa: F811
    imp = report(client, h, -10, 122).json()["implications"]
    assert imp["available"] and imp["items"]
    kinds = {i["kind"] for i in imp["items"]}
    assert kinds <= set(imp["kinds"]) and "ecological_implication" in kinds
    text = " ".join(i["text"] for i in imp["items"]).lower()
    assert "may" in text or "could" in text
    for banned in ("will die", "is damaged", "has caused", "mass mortality has"):
        assert banned not in text


# ------------------------------------------------------------------------------------------------ forecast explanation
def test_forecast_explanation_uses_the_actual_inputs_and_outputs(explain_ready):
    e = fe.explain("pacific", -10, 122, runner=fake_sensitivity)
    assert e["available"] and e["issued_from"] == P.LATEST == e["latest_observation"]
    assert e["current"]["anomaly_c"] == pytest.approx(1.1, abs=0.01) and e["current"]["relation"] == "warmer" and len(e["current"]["window"]) == 7
    assert len(e["forecast"]) == H and [r["day"] for r in e["forecast"]] == list(range(1, H + 1))
    first = e["forecast"][0]
    assert first["date"] > P.LATEST and first["direction"] in ("warmer", "cooler", "about the same") and first["typical_error_c"] == 0.40
    kinds = [s["kind"] for s in e["model_explanation"]]
    assert {"model_prediction", "model_explanation", "statistical", "physical_cause"} <= set(kinds)
    phys = next(s for s in e["model_explanation"] if s["kind"] == "physical_cause")
    assert "cannot say" in phys["text"] and "not physical causation" in phys["text"]
    poss = next(s for s in e["model_explanation"] if s["kind"] == "possible_explanation")
    assert "None of them is an input" in poss["text"]
    assert e["sensitivity"]["title"] == "Model sensitivity: not causal attribution"


def test_forecast_explanation_forecast_matches_the_published_snapshot(explain_ready):
    from app.services import environment_store as es
    i, j = fe._locate(es.get_store("pacific"), -10, 122)
    pub = fe.forecast_store.load("pacific")[0]["latest_forecast"][:, i, j]
    assert fe.explain("pacific", -10, 122, runner=lambda *a: {**fake_sensitivity(*a), "forecast_c": [float(x) for x in pub]})["matches_published_forecast"] is True
    fe._cache.clear()
    assert fe.explain("pacific", -10, 122, runner=fake_sensitivity)["matches_published_forecast"] is False             # a different network output is flagged, not hidden


def test_forecast_explanation_is_not_given_for_a_stale_forecast(explain_ready):
    F.build(explain_ready, issued="2020-01-10")
    forecast_store._read.cache_clear()
    e = fe.explain("pacific", -10, 122, runner=fake_sensitivity)
    assert e["available"] is False and "2020-01-10" in e["message"]


def test_forecast_explanation_rejects_land_and_outside_locations(explain_ready):
    with pytest.raises(ValueError, match="land"):
        fe.explain("pacific", 50, 110, runner=fake_sensitivity)
    with pytest.raises(ValueError, match="outside"):
        fe.explain("pacific", 70, 200, runner=fake_sensitivity)
    with pytest.raises(ValueError):
        fe.explain("pacific", 95, 0, runner=fake_sensitivity)


def test_forecast_explain_endpoint_validates_and_forecast_model_describes_the_network(client, h, pac):  # noqa: F811
    assert client.get("/api/environment/forecast-explain", params={"dataset": "pacific", "lat": 95, "lon": 0}, headers=h).status_code == 422
    assert client.get("/api/environment/forecast-explain", params={"dataset": "pacific", "lat": 50, "lon": 110}, headers=h).status_code == 422
    m = client.get("/api/environment/forecast-model", params={"dataset": "pacific"}, headers=h)
    assert m.status_code == 200
    b = m.json()
    assert b["input"]["window_days"] >= 1 and b["output"]["horizons"] == list(range(1, H + 1))
    assert b["evaluation"]["beats_persistence"] is False and b["periods"]["test"] and "ConvLSTM" in b["name"]
    assert "not inputs" in b["input"]["not_inputs"]


def _day_text(e):
    return next(s["text"] for s in e["model_explanation"] if s["text"].startswith("Which input day matters most"))


def test_sensitivity_sign_is_never_reversed(explain_ready):
    warm = fe.explain("pacific", -10, 122, runner=fake_sensitivity)                                           # warm anomaly, positive contribution
    t = _day_text(warm)
    assert "warm anomaly" in t and "contributes +" in t and "would lower the predicted temperature" in t and "relies on this recent anomaly" in t

    def cold(*a):
        r = fake_sensitivity(*a)
        r["input_window"]["anomaly_c"] = [-0.5 - 0.1 * k for k in range(7)]
        r["sensitivity"]["temporal"]["delta_c"] = [[-0.02 * (d + 1)] * H for d in range(7)]                  # a cold anomaly pulls the forecast colder
        return r
    fe._cache.clear()
    t = _day_text(fe.explain("pacific", -10, 122, runner=cold))
    assert "cold anomaly" in t and "contributes -" in t and "would raise the predicted temperature" in t


def test_explanation_separates_observed_inferred_possible_and_not_established(explain_ready):
    e = fe.explain("pacific", -10, 122, runner=fake_sensitivity)
    kinds = {s["kind"] for s in e["model_explanation"]}
    assert {"observed", "model_prediction", "model_explanation", "possible_explanation", "physical_cause"} <= kinds
    assert any("Seasonal signal" in s["text"] for s in e["model_explanation"] if s["kind"] == "observed")
    text = " ".join(s["text"] for s in e["model_explanation"])
    for claim in ("El Ni", "caused by", "because of the wind"):
        assert claim not in text


# ------------------------------------------------------------------------------------------------ anomaly outlook
def _outlook(now, fa, err=None):
    from app.services import location_report as lr
    out = {"conditions": {"anomaly": now}, "anomaly": {"explanation": {"sections": []}}, "forecast": {"available": True, "forecast_anomaly": fa, "typical_error_c": err}}
    lr._add_outlook(out)
    return out["anomaly"]["explanation"]["sections"]


def test_warm_anomaly_outlook_persist_weaken_strengthen():
    assert "persist" in _outlook(2.0, [2.0, 2.1, 2.0, 1.9, 2.0, 2.1, 2.0])[0]["text"] and "warmer than the baseline throughout" in _outlook(2.0, [2.0] * 7)[0]["text"]
    assert "weaken" in _outlook(3.0, [2.8, 2.5, 2.2, 2.0, 1.8, 1.6, 1.4])[0]["text"]
    assert "strengthen" in _outlook(1.0, [1.1, 1.3, 1.5, 1.7, 1.9, 2.1, 2.3])[0]["text"]


def test_cold_anomaly_outlook_uses_cold_wording_and_never_claims_a_cause():
    s = _outlook(-2.0, [-1.9, -1.8, -1.6, -1.5, -1.3, -1.2, -1.0], err=[0.1, 0.18, 0.24, 0.28, 0.33, 0.37, 0.4])[0]
    assert "weaken" in s["text"] and "colder than the baseline" in s["text"] and "no physical cause is implied" in s["text"] and "±0.40" in s["bullets"][0]


def test_small_and_sign_changing_anomalies_and_missing_forecast():
    assert "close to the baseline" in _outlook(0.2, [0.1, 0.2, 0.1, 0.0, 0.1, 0.2, 0.1])[0]["text"]
    assert "change sign" in _outlook(1.5, [1.0, 0.6, 0.2, -0.2, -0.6, -0.9, -1.2])[0]["text"]
    assert _outlook(1.5, None) == []


def test_report_anomaly_explanation_has_the_forecast_outlook(client, h, pac):  # noqa: F811
    secs = {s["id"]: s for s in report(client, h, -10, 122).json()["anomaly"]["explanation"]["sections"]}
    assert "outlook" in secs and "model prediction" in secs["outlook"]["text"]


def test_forecast_explanation_has_a_counterfactual_table_and_a_numeric_narrative(explain_ready):
    e = fe.explain("pacific", -10, 122, runner=fake_sensitivity)
    cf = e["counterfactual"]
    assert cf["horizon"] == 7 and cf["title"] == "Model sensitivity: not causal attribution"
    base = cf["rows"][0]
    assert base["difference_c"] == 0 and base["sst_c"] == pytest.approx(e["forecast"][6]["sst_c"], abs=0.01)
    for row in cf["rows"][1:]:                                                                               # perturbed = observed output minus the measured contribution
        assert row["sst_c"] == pytest.approx(base["sst_c"] + row["difference_c"], abs=0.02) and row["anomaly_c"] == pytest.approx(base["anomaly_c"] + row["difference_c"], abs=0.02)
    assert "not evidence that the anomaly caused" in cf["reading"] or "not sensitive" in cf["reading"]
    it = e["interpretation"]
    assert it["direction"] in ("warming", "cooling", "stable") and f"{it['start_anomaly_c']:+.1f}" in it["text"] and f"{it['end_anomaly_c']:+.1f}" in it["text"] and "not proof of physical causation" in it["text"]
    assert e["current"]["trend_3d_c_per_day"] is not None and e["current"]["anomaly_change_7d_c"] is not None


def test_the_interpretation_says_when_the_forecast_reverses_the_recent_tendency(explain_ready):
    agree = fe.explain("pacific", -10, 122, runner=fake_sensitivity)["interpretation"]                       # SST rises over the window and the forecast warms
    assert agree["direction"] == "warming" and "projects that warming tendency forward" in agree["text"]
    fe._cache.clear()

    def falling(*a):
        r = fake_sensitivity(*a)
        r["input_window"]["sst_c"] = [20.6 - 0.1 * k for k in range(7)]
        return r
    rev = fe.explain("pacific", -10, 122, runner=falling)["interpretation"]
    assert "falling SST" in rev["text"] and "does not simply continue the recent tendency" in rev["text"] and "projects that" not in rev["text"]


def test_signed_numbers_never_print_negative_zero():
    from app.services import forecast_reading as fr
    assert fr.sg(-0.001) == "0.00" and fr.sg(0.3) == "+0.30" and fr.sg(-1.234) == "-1.23"
    r = fr.reading(25.0, 1.6, [24.9] * 7, [1.6] * 7, clim_f=[23.4] * 7, normal_now=23.4)
    assert "-0.00" not in r["text"]


# ------------------------------------------------------------------------------------------------ the explainable-AI payload
def _rebuild(pac_root, slope):
    F.build(pac_root, slope=slope)
    forecast_store._read.cache_clear()
    fe._cache.clear()


def _obs_at(lat, lon):
    from app.services import environment_store as es
    i, j = fe._locate(es.get_store("pacific"), lat, lon)
    return float(forecast_store.load("pacific")[0]["latest_obs"][i, j])


def _window(lat, lon, rising):
    obs = _obs_at(lat, lon)
    return [obs - 0.6 + 0.1 * k for k in range(7)] if rising else [obs + 0.6 - 0.1 * k for k in range(7)]


def _sens(window_sst, window_anom):
    def run(dataset, lat, lon):
        r = fake_sensitivity(dataset, lat, lon)
        r["input_window"]["sst_c"] = window_sst
        r["input_window"]["anomaly_c"] = window_anom
        return r
    return run


@pytest.mark.parametrize("slope,rising,expect", [
    (0.1, True, ("warming", "continues in the same direction, indicating warmer conditions")),
    (-0.1, False, ("cooling", "continues in the same direction, indicating cooler conditions")),
    (0.0, True, ("stable", "change only slightly over the forecast period")),
])
def test_the_plain_explanation_follows_the_forecast_direction(explain_ready, slope, rising, expect):
    _rebuild(explain_ready, slope)
    it = fe.explain("pacific", -10, 122, runner=_sens(_window(-10, 122, rising), [0.5 + 0.1 * k for k in range(7)]))["interpretation"]
    assert it["direction"] == it["forecast_outlook"] == expect[0] and expect[1] in it["plain"]
    assert it["anomaly_outlook"] in ("persistent", "strengthening", "weakening", "returning toward normal", "near normal", "changing sign")


def test_a_forecast_that_reverses_the_recent_tendency_is_said_to_do_so(explain_ready):
    _rebuild(explain_ready, -0.1)
    it = fe.explain("pacific", -10, 122, runner=_sens(_window(-10, 122, True), [0.5] * 7))["interpretation"]
    assert it["direction"] == "cooling" and "not a simple continuation of the recent trend" in it["plain"]


def test_the_two_outlooks_always_agree_with_the_numbers(explain_ready):
    from app.services import forecast_reading as fr
    for slope in (0.1, -0.1, 0.0, 0.3):
        _rebuild(explain_ready, slope)
        e = fe.explain("pacific", -10, 122, runner=fake_sensitivity)
        it, fcs = e["interpretation"], e["forecast"]
        assert it["anomaly_outlook"] == fr.trajectory(it["start_anomaly_c"], fcs[-1]["anomaly_c"]) or abs(it["end_anomaly_c"] - fcs[-1]["anomaly_c"]) < 0.06
        assert it["direction"] == fr.reading(e["current"]["sst_c"], e["current"]["anomaly_c"], [f["sst_c"] for f in fcs], [f["anomaly_c"] for f in fcs])["label"]


def test_the_explanation_differs_between_places(explain_ready):
    a = fe.explain("pacific", -10, 122, runner=_sens(_window(-10, 122, True), [0.5 + 0.1 * k for k in range(7)]))
    fe._cache.clear()
    b = fe.explain("pacific", 30, 150, runner=_sens(_window(30, 150, False), [-0.5 - 0.1 * k for k in range(7)]))
    assert a["interpretation"]["plain"] != b["interpretation"]["plain"] and a["inputs"]["latest_anomaly_c"] != b["inputs"]["latest_anomaly_c"] and a["inputs"]["cell"] != b["inputs"]["cell"]


def test_nothing_in_the_explanation_names_a_physical_cause(explain_ready):
    import json as _json
    e = fe.explain("pacific", -10, 122, runner=fake_sensitivity)
    text = _json.dumps({k: e[k] for k in ("interpretation", "signals", "model_evidence", "physical_cause", "counterfactual", "model_explanation", "statement")}, ensure_ascii=False)
    for bad in ("caused by", "because of the wind", "due to El", "due to La", "El Niño caused", "currents caused", "upwelling caused", "driven by the wind"):
        assert bad not in text, bad
    assert "Cannot be established by this model" in e["physical_cause"] and "not inputs" in e["physical_cause"]
    assert e["issued_from"] == e["latest_observation"] and e["forecast"][0]["date"] > e["latest_observation"]               # the first forecast day follows the latest observation


# ------------------------------------------------------------------------------------------------ the sensitivity subprocess and its failures
class _Done:
    def __init__(self, rc=0, out="", err=""):
        self.returncode, self.stdout, self.stderr = rc, out, err


def test_the_sensitivity_run_uses_the_interpreter_that_runs_the_api(monkeypatch):
    import json as _json
    import sys
    seen = {}

    def fake_run(cmd, **kw):
        seen["cmd"], seen["kw"] = cmd, kw
        return _Done(0, "log line\n" + _json.dumps({"forecast_c": [1.0]}))

    monkeypatch.setattr(fe.subprocess, "run", fake_run)
    assert fe.run_sensitivity("pacific", 1.0, 2.0) == {"forecast_c": [1.0]}
    assert seen["cmd"][:3] == [sys.executable, "-m", "oceanmind_model"] and seen["kw"]["timeout"] == fe.TIMEOUT_S


@pytest.mark.parametrize("err,fragment", [("Traceback...\nModuleNotFoundError: No module named 'torch'", "No module named 'torch'"),
                                          ("Traceback...\nFileNotFoundError: best_model.pt", "best_model.pt")])
def test_a_failing_sensitivity_run_is_a_clear_503_and_the_rest_of_the_report_still_works(client, h, pac, monkeypatch, err, fragment):  # noqa: F811
    fe._cache.clear()
    monkeypatch.setattr(fe.subprocess, "run", lambda cmd, **kw: _Done(1, "", err))
    r = client.get("/api/environment/forecast-explain", params={"dataset": "pacific", "lat": -10, "lon": 122}, headers=h)
    assert r.status_code == 503 and r.json()["detail"]["code"] == "explanation_unavailable" and fragment in r.json()["detail"]["message"]
    assert report(client, h, -10, 122).status_code == 200                                  # the Location Report does not depend on the explanation
    assert client.get("/api/environment/forecast-model", params={"dataset": "pacific"}, headers=h).status_code == 200


def test_a_sensitivity_timeout_is_reported_as_such_and_never_cached(client, h, pac, monkeypatch):  # noqa: F811
    import subprocess
    fe._cache.clear()

    def boom(cmd, **kw):
        raise subprocess.TimeoutExpired(cmd, 1)

    monkeypatch.setattr(fe.subprocess, "run", boom)
    r = client.get("/api/environment/forecast-explain", params={"dataset": "pacific", "lat": -10, "lon": 122}, headers=h)
    assert r.status_code == 503 and r.json()["detail"]["code"] == "explanation_timeout"
    assert not fe._cache
