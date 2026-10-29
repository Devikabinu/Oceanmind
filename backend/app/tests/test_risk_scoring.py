"""The ecological-risk calculation, tested on small hand-built inputs so that every number can be checked by hand."""
import numpy as np
import pytest

from app.services import risk_service as rs

N = 4


def inputs(anom=0.5, persist=0, forecast=0.5, with_persist=True, with_forecast=True) -> rs.RiskInputs:
    a = np.full((N, N), anom, dtype="float32")
    return rs.RiskInputs(
        dataset="t", lat=np.arange(N, dtype="float64"), lon=np.arange(N, dtype="float64"), res=1.0, bounds={}, date="2020-01-01", anomaly=a,
        state=np.zeros((N, N), dtype="int8"),
        persistence_days=np.full((N, N), persist, dtype="float32") if with_persist else None,
        forecast_anomaly=np.full((7, N, N), forecast, dtype="float32") if with_forecast else None,
        unavailable={} if with_persist and with_forecast else {"persistence": "no heatwave state", "forecast": "no forecast"},
        cell_fn=lambda la, lo: (int(la), int(lo)), baseline=["2012-01-01", "2023-12-31"])


def assess(inp, overlap=None):
    return rs.cell_assessment(inp, 1, 1, overlap)


def by(a):
    return {f["factor"]: f for f in a["factors"]}


def test_different_inputs_give_different_scores():
    scores = [assess(inputs(anom=x, persist=p, forecast=f), {(0, 0): n})["score"] for x, p, f, n in [(0.2, 0, 0.2, 0), (1.5, 5, 1.0, 1), (3.0, 14, 3.0, 3)]]
    assert scores == sorted(scores) and len(set(scores)) == 3


def test_low_anomaly_is_not_critical_and_moderate_is_not_the_maximum():
    low = assess(inputs(anom=0.3, persist=0, forecast=0.3), {(0, 0): 0})
    assert low["score"] < 0.25 and low["level"] == "LOW"
    mid = assess(inputs(anom=1.5, persist=0, forecast=1.5), {(0, 0): 0})
    f = by(mid)["anomaly"]
    assert f["value"] == pytest.approx(0.5) and f["saturated"] is False and 0.0 < mid["score"] < 1.0


def test_extreme_conditions_can_reach_a_high_score_and_are_marked_capped():
    a = assess(inputs(anom=4.0, persist=20, forecast=4.0), {(0, 0): 5})
    assert a["score"] == pytest.approx(1.0) and a["level"] == "CRITICAL"
    assert all(f["saturated"] for f in a["factors"])
    assert by(a)["anomaly"]["raw"] == pytest.approx(4.0) and by(a)["anomaly"]["ratio"] > 1               # the raw value stays visible beyond the cap


def test_negative_anomaly_scores_by_magnitude_and_keeps_its_sign():
    a = assess(inputs(anom=-2.0, persist=0, forecast=-2.0), {(0, 0): 0})
    assert by(a)["anomaly"]["value"] == pytest.approx(2 / 3, abs=0.01) and by(a)["anomaly"]["raw"] == pytest.approx(-2.0)


def test_missing_evidence_is_never_one_or_zero():
    a = assess(inputs(anom=1.5, with_persist=False, with_forecast=False), None)
    f = by(a)
    for k in ("persistence", "forecast", "overlap"):
        assert f[k]["status"] == "unavailable" and f[k]["value"] is None and f[k]["contribution"] is None and f[k]["missing_input"]
    assert a["score"] == pytest.approx(0.5)                                                           # only the anomaly is present: 0.35 * 0.5 / 0.35
    assert a["score_breakdown"]["denominator_weight"] == pytest.approx(rs.WEIGHTS["anomaly"])


def test_unavailable_factors_are_excluded_and_remaining_weights_renormalised():
    a = assess(inputs(anom=3.0, persist=0, forecast=3.0, with_persist=True), None)                    # no species data: overlap left out
    f = by(a)
    assert f["overlap"]["status"] == "unavailable"
    den = rs.WEIGHTS["anomaly"] + rs.WEIGHTS["persistence"] + rs.WEIGHTS["forecast"]
    assert f["anomaly"]["effective_weight"] == pytest.approx(rs.WEIGHTS["anomaly"] / den, abs=1e-3)
    assert a["score"] == pytest.approx((rs.WEIGHTS["anomaly"] + rs.WEIGHTS["forecast"]) / den, abs=1e-3)


def test_evidence_present_but_small_is_below_threshold_not_insufficient():
    a = assess(inputs(anom=0.2, persist=0, forecast=0.2), {(0, 0): 0})
    f = by(a)
    assert f["persistence"]["available"] and f["persistence"]["status"] == "below_threshold" and f["persistence"]["value"] == 0.0
    assert f["overlap"]["available"] and f["overlap"]["status"] == "below_threshold"                   # records were gathered and there are none here


def test_partial_forecast_is_incomplete_but_used():
    inp = inputs(anom=1.0, forecast=1.0)
    inp.forecast_anomaly[3:, 1, 1] = np.nan
    f = by(assess(inp, {(0, 0): 1}))["forecast"]
    assert f["status"] == "incomplete" and f["available"] and f["days_with_data"] == 3 and f["value"] == pytest.approx(1 / 3, abs=0.01)


def test_score_is_the_sum_of_contributions_and_within_range():
    for x in (0.0, 0.4, 1.2, 2.6, 3.5):
        for n in (None, {(0, 0): 0}, {(0, 0): 2}):
            a = assess(inputs(anom=x, persist=int(x * 3), forecast=x), n)
            assert 0.0 <= a["score"] <= 1.0
            assert a["score_breakdown"]["sum"] == pytest.approx(a["score"], abs=0.002)


def test_species_factor_counts_distinct_species_in_the_block():
    a = assess(inputs(anom=1.0), {(0, 0): 2})
    f = by(a)["overlap"]
    assert f["raw"] == 2 and f["raw_unit"] == "species" and f["value"] == pytest.approx(2 / rs.OVERLAP_SATURATION, abs=0.01)


def test_unsampled_domain_gives_no_species_evidence_rather_than_zero():
    inp = inputs(anom=1.0)
    inp.species_sampled = False
    g = rs.factor_grids(inp, {})
    assert np.isnan(g["factors"]["overlap"]).all()
    assert by(rs.cell_assessment(inp, 1, 1, {}, g))["overlap"]["status"] == "unavailable"
