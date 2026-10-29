"""The explanatory layer of the location report: forecast reading, nearby biodiversity records in the score, heatwave analysis, factor details."""
import numpy as np
import pytest

from app.services import forecast_reading as fr
from app.services import report_analysis as ra
from app.services import risk_service as rs
from app.tests.test_pacific_product import h, pac, report  # noqa: F401  (fixtures)
from app.tests.test_risk_scoring import inputs


# ------------------------------------------------------------------------------------------------ forecast reading
def test_reading_warming_peak_then_weakening_is_described_from_the_numbers():
    r = fr.reading(20.0, 1.8, [20.3, 20.5, 20.7, 20.8, 20.6, 20.4, 20.3], [2.0, 2.2, 2.4, 2.4, 2.1, 1.6, 1.2])
    assert r["label"] == "warming" and r["anomaly_label"] == "weakening" and r["peak_day"] in (3, 4) and "before beginning to weaken" in r["text"] and "+1.8" in r["text"] and "+2.4" in r["text"]


def test_reading_cooling_with_weakening_anomaly():
    r = fr.reading(25.0, 2.1, [24.8, 24.6, 24.4, 24.2, 24.0, 23.8, 23.7], [1.9, 1.6, 1.4, 1.2, 1.0, 0.9, 0.8], typical_error=[0.1] * 7)
    assert r["label"] == "cooling" and r["anomaly_label"] == "weakening" and "gradual cooling" in r["text"] and "+2.1" in r["text"] and "+0.8" in r["text"] and "±0.10" in r["text"]


def test_reading_stable_persistent_strengthening_and_sign_change():
    assert fr.reading(20.0, 0.3, [20.0] * 7, [0.3] * 7)["label"] == "stable"
    assert fr.reading(20.0, 2.0, [20.1, 20.1, 20.2, 20.2, 20.1, 20.1, 20.2], [2.0, 2.1, 2.1, 2.2, 2.0, 2.1, 2.2])["anomaly_label"] == "persistent"
    assert fr.reading(20.0, 1.0, [20.2, 20.4, 20.6, 20.8, 21.0, 21.2, 21.4], [1.2, 1.5, 1.8, 2.0, 2.2, 2.4, 2.6])["anomaly_label"] == "strengthening"
    assert fr.reading(20.0, 1.5, [19.9, 19.7, 19.5, 19.3, 19.1, 18.9, 18.7], [1.0, 0.5, 0.1, -0.2, -0.5, -0.8, -1.1])["anomaly_label"] == "changing sign"


def test_anomaly_classes_and_direction_by_day():
    assert [fr.classify_anomaly(x) for x in (0.4, -1.5, 2.4, -3.6, None)] == ["Low", "Moderate", "High", "Extreme", None]
    assert [fr.day_direction(x) for x in (0.01, 0.4, -0.4)] == ["stable", "warming", "cooling"]


# ------------------------------------------------------------------------------------------------ nearby biodiversity records enter the score
def _with_unsampled_species(species_at):
    inp = inputs(anom=1.5)
    inp.species_sampled = False
    inp.res = 1.0
    return inp, {species_at: 2}


def test_an_unsampled_block_uses_the_nearest_sampled_block_and_says_so():
    inp, overlap = _with_unsampled_species((0, 0))
    g = rs.factor_grids(inp, overlap)
    a = rs.cell_assessment(inp, 3, 3, overlap, g)                                                          # block (1, 1): unsampled, one block away from (0, 0)
    f = {x["factor"]: x for x in a["factors"]}["overlap"]
    assert f["available"] and f["scope"] == "nearby" and f["distance_deg"] > 0 and f["raw"] == 2 and "nearby records" in " ".join(a["reasons"])
    local = {x["factor"]: x for x in rs.cell_assessment(inp, 0, 0, overlap, g)["factors"]}["overlap"]
    assert local.get("scope") is None and local["value"] == f["value"]


def test_nearby_records_are_not_borrowed_beyond_the_reach():
    inp = inputs(anom=1.5)
    inp.species_sampled = False
    inp.res = 4.0                                                                                          # 4 degree blocks: cell (3, 3) is 12 degrees from the sampled block (0, 0)
    g = rs.factor_grids(inp, {(0, 0): 2})
    f = {x["factor"]: x for x in rs.cell_assessment(inp, 3, 3, {(0, 0): 2}, g)["factors"]}["overlap"]
    assert f["status"] == "unavailable" and f["value"] is None
    near = {x["factor"]: x for x in rs.cell_assessment(inp, 1, 0, {(0, 0): 2}, g)["factors"]}["overlap"]
    assert near["status"] != "unavailable"


# ------------------------------------------------------------------------------------------------ the report's explanatory layer
def test_report_has_analysis_forecast_reading_and_per_day_direction(client, h, pac):  # noqa: F811
    r = report(client, h, -10, 122).json()
    f = r["forecast"]
    assert f["reading"]["label"] in ("warming", "cooling", "stable") and len(f["direction_by_day"]) == 7 and f["reading"]["days"] == 7
    drivers = {d["factor"]: d for d in r["risk"]["drivers"]}
    assert drivers["anomaly"]["classification"] in ("Low", "Moderate", "High", "Extreme") and drivers["anomaly"]["detail_lines"]
    assert drivers["forecast"]["detail_lines"][0].startswith("Forecast anomaly by day")
    assert all(d["normalization"] for d in r["risk"]["drivers"])
    w = r["analysis"]["why_forecast"]
    assert w["headline"].startswith("Why is the forecast") and any(b["kind"] == "model_prediction" for b in w["bullets"]) and any(b["kind"] == "physical_cause" for b in w["bullets"])


def test_heatwave_analysis_for_active_and_inactive_places(client, h, pac):  # noqa: F811
    inside = report(client, h, -10, 122).json()["heatwave"]["analysis"]
    assert inside["active"] is True and "has persisted for 9 days" in inside["lines"][0] and any("Forecast relationship" in x and "Classification:" in x for x in inside["lines"]) and any(x.startswith("Threshold:") for x in inside["lines"]) and inside["status"] in ("Persisting", "Strengthening", "Weakening", "Ending")
    outside = report(client, h, 30, 150).json()["heatwave"]["analysis"]
    assert outside["active"] is False and outside["lines"][0] == "No active marine heatwave is detected at this location."


def test_other_dates_say_that_heatwave_status_applies_to_the_latest_date(client, h, pac):  # noqa: F811
    a = report(client, h, -10, 122, date="2020-01-05").json()["heatwave"]["analysis"]
    assert a["active"] is None and "latest date" in a["lines"][0]


def test_scores_and_explanations_change_between_places(client, h, pac):  # noqa: F811
    places = [(-10, 122), (30, 150), (10, -179), (0, 130)]
    rs_ = [report(client, h, la, lo).json() for la, lo in places]
    ok = [r for r in rs_ if r.get("risk", {}).get("score") is not None]
    assert len({r["risk"]["score"] for r in ok}) >= 2
    assert len({r["forecast"]["reading"]["text"] for r in ok if r["forecast"].get("reading")}) >= 2 or len(ok) < 3


def test_implications_cover_fisheries_plankton_spawning_and_habitat_and_name_the_value(client, h, pac):  # noqa: F811
    r = report(client, h, -10, 122).json()
    a = r["conditions"]["anomaly"]
    text = " ".join(i["text"] for i in r["implications"]["items"])
    if abs(a) >= 1.0:
        for word in ("Fisheries", "Plankton", "Spawning and recruitment", "Habitat suitability"):
            assert word in text
        assert f"{abs(a):.1f}" in text
    assert "damage has occurred" not in text.lower()


def test_small_anomalies_are_near_normal_not_a_persistent_warm_anomaly():
    r = fr.reading(20.0, 0.3, [19.9, 19.8, 19.7, 19.6, 19.6, 19.5, 19.5], [0.2, 0.1, 0.0, -0.1, -0.2, -0.3, -0.4])
    assert r["anomaly_label"] == "near normal" and "stays close to normal" in r["text"] and "persistent warm" not in r["text"]


def test_a_persistent_anomaly_that_cools_with_the_season_says_so():
    r = fr.reading(25.0, 1.6, [24.8, 24.6, 24.4, 24.2, 24.0, 23.5, 24.3], [1.6, 1.6, 1.6, 1.6, 1.6, 1.6, 1.6], clim_f=[23.2] * 7, normal_now=23.4)
    r2 = fr.reading(25.0, 1.6, [24.6, 24.5, 24.4, 24.3, 24.3, 24.3, 24.3], [1.6, 1.6, 1.6, 1.6, 1.6, 1.6, 1.5], clim_f=[23.0] * 7, normal_now=23.4)
    assert r["seasonal_change_c"] == pytest.approx(-0.2) and r2["anomaly_label"] == "persistent"
    r3 = fr.reading(25.0, 1.6, [24.8, 24.7, 24.6, 24.5, 24.4, 24.4, 24.3], [1.6, 1.6, 1.6, 1.6, 1.6, 1.6, 1.6], clim_f=[22.7] * 7, normal_now=23.4)
    assert "normal seasonal change of -0.70" in r3["text"] and "anomaly persisting" in r3["text"]


def test_every_sentence_about_the_anomalys_future_uses_the_same_rule():
    from app.services import explain_service as ex, location_report as lr
    for now, end in ((2.6, 1.8), (2.0, 2.1), (1.0, 2.0), (1.5, -0.8), (0.2, 0.3)):
        label = fr.trajectory(now, end)
        bullets = lr._forecast_reading("cooling", now, [end] * 7, [20.0] * 7, None, None, None)
        said = [b for b in bullets if b.startswith("The current anomaly")]
        if said and abs(now) >= 0.5:
            assert fr.EXPECTED[label] in said[0]
        imp = ex.implications({"anomaly": now, "forecast": {"available": True, "forecast_anomaly": [end] * 7}, "heatwave": {}, "species": {}, "risk": {}})
        assert any(fr.EXPECTED[label] in i["text"] for i in imp["items"] if i["kind"] == "model_prediction")


def test_plain_language_risk_text_never_says_medium():
    from app.services import explain_service as ex
    assert "MEDIUM" not in ex.LEVEL_BANDS and "MODERATE below 0.5" in ex.LEVEL_BANDS


def test_no_report_text_says_medium(client, h, pac):  # noqa: F811
    import json
    for la, lo in [(-10, 122), (30, 150), (10, -179), (0, 130), (-30, 110), (20, 170)]:
        r = report(client, h, la, lo).json()
        if r.get("status") != "valid":
            continue
        shown = json.dumps({k: r.get(k) for k in ("risk", "anomaly", "implications", "forecast", "analysis", "heatwave")}, ensure_ascii=False)
        # "level": "MEDIUM" is the API's code for MODERATE; the only place the code may appear is a field that holds the code itself
        text = shown.replace('"level": "MEDIUM"', "").replace('"highest_risk_level": "MEDIUM"', "")
        assert "(MEDIUM)" not in text and "MEDIUM below" not in text and "MEDIUM risk" not in text
