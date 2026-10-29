"""The physical interpretation: evidence package, deterministic narrator, validator and the optional AI provider layer."""
import copy
import json
import time

import pytest

from app.services import ai_providers as aip
from app.services import physical_analysis as pa
from app.services import physical_interpretation as pi
from app.tests.test_physical_drivers import DRV, W, _ctx, fr_reading


def fc_block(start_sst=30.0, end_sst=29.6):
    dates = [f"2026-10-{28 + k}" if 28 + k <= 31 else f"2026-11-0{k - 3}" for k in range(7)]
    sst = [round(start_sst + (end_sst - start_sst) * (k + 1) / 7, 2) for k in range(7)]
    return {"issued_from": "2026-10-27", "dates": dates, "forecast_sst": sst, "forecast_anomaly": [round(s - 28.0, 2) for s in sst], "typical_error_c": [0.1, 0.15, 0.2, 0.25, 0.3, 0.35, 0.4]}


def series(sst0, sst1, anom0, anom1, n=14):
    return [{"date": f"2026-10-{14 + k}", "sst_c": round(sst0 + (sst1 - sst0) * k / (n - 1), 2), "anomaly_c": round(anom0 + (anom1 - anom0) * k / (n - 1), 2)} for k in range(n)]


def make(a=2.0, drv=None, hw=None, recent=None, sst=30.0, reading=None, **over):
    rd = reading or fr_reading(sst=(sst, sst - 0.4), anom=(a, a - 0.4))
    ctx = _ctx(a=a, reading=rd, sst=sst, forecast=fc_block(sst, sst - 0.4), heatwave=hw if hw is not None else {"available": True, "inside": False}, **over)
    ctx["sst"] = sst
    if recent:
        ctx["recent"] = recent
    return pi.build_package(pa.analyse(drv or DRV(), ctx), ctx, "Equatorial Pacific"), ctx


@pytest.fixture(autouse=True)
def _clean(tmp_path, monkeypatch):
    monkeypatch.setattr(pi, "_cache_dir", lambda: tmp_path / "ai")
    pi.clear_state()
    yield
    pi.clear_state()


# ------------------------------------------------------------------------------------------------ the package holds only real values
def test_package_ids_are_unique_and_every_mechanism_id_exists():
    pkg, _ = make()
    ids = [e["id"] for e in pkg["evidence"]]
    assert len(ids) == len(set(ids)) and ids[0] == "E1"
    assert all(set(m["evidence_ids"]) <= set(ids) for m in pkg["mechanisms"])
    assert pkg["sst"]["anomaly_c"] == 2.0 and pkg["location"]["region"] == "Equatorial Pacific"


def test_package_values_come_from_the_inputs_and_missing_drivers_are_not_invented():
    pkg, _ = make(drv=DRV(winds=None, sea_level=None, enso=None, currents=None))
    labels = " ".join(e["label"] for e in pkg["evidence"])
    assert "wind" not in labels.lower() and "Niño" not in labels
    assert pkg["confidence"]["not_assessable"] >= 3
    assert all(isinstance(e["value"], (int, float)) for e in pkg["evidence"])


# ------------------------------------------------------------------------------------------------ the narrator
def test_the_narrator_output_always_passes_the_validator():
    for a, drv in ((2.5, DRV()), (-2.5, DRV()), (0.1, DRV()), (2.0, DRV(winds=None, sea_level=None, enso=None)), (-1.5, DRV(winds=W(speed_z=-2.0)))):
        pkg, _ = make(a=a, drv=drv)
        assert pi.validate(pi.narrate(pkg), pkg) == [], (a, pi.validate(pi.narrate(pkg), pkg))


def test_a_warm_anomaly_with_consistent_drivers_names_them_with_their_measurements():
    pkg, _ = make(a=2.5)
    out = pi.narrate(pkg)
    ids = {m["id"] for m in out["mechanisms"]}
    assert 1 <= len(out["mechanisms"]) <= 3 and ids <= {"wind", "upwelling", "sea_level", "enso", "heat_flux", "advection"}
    assert all(m["evidence_ids"] for m in out["mechanisms"]) and all(m["support"] in ("local_measurements", "climate_context") for m in out["mechanisms"])
    assert "above" in out["headline"] and out["confidence"]["level"] == pkg["confidence"]["level"]
    assert out["confidence"]["criteria"] and all("text" in c and "met" in c for c in out["confidence"]["criteria"])


def test_a_cold_anomaly_is_described_as_cold_and_does_not_borrow_warm_mechanisms():
    pkg, _ = make(a=-2.5, drv=DRV(winds=W(speed_z=-2.0)))
    out = pi.narrate(pkg)
    assert "below" in out["headline"]
    assert "wind" not in {m["id"] for m in out["mechanisms"]}                                  # weaker winds do not explain cooling
    assert not any("warm surface" in m["explanation"] for m in out["mechanisms"])


def test_seasonal_cooling_is_separated_from_an_anomaly():
    recent = series(29.0, 27.8, 0.05, 0.1)                                                  # SST falls 1.2 degrees; the anomaly does not change
    pkg, _ = make(a=0.1, recent=recent, sst=27.8)
    pkg["sst"]["seasonal_change_window_c"] = -1.1
    out = pi.narrate(pkg)
    assert "seasonal" in out["headline"].lower() and "seasonal" in out["summary"].lower() and "not an anomalous event" in out["summary"]
    assert [m["id"] for m in out["mechanisms"]] == ["seasonal_cycle"] and out["mechanisms"][0]["support"] == "climatology"
    assert pi.validate(out, pkg) == []


def test_a_persistent_heatwave_is_stated_with_its_duration_and_without_a_cause():
    hw = {"available": True, "inside": True, "run_days": 41, "event": {"start_date": "2026-09-17", "category_name": "Strong", "max_anomaly_c": 3.1}}
    pkg, _ = make(a=2.8, hw=hw, drv=DRV(winds=None, sea_level=None, enso=None, currents=None))
    out = pi.narrate(pkg)
    assert "41 days" in out["headline"] and "2026-09-17" in out["summary"]
    assert [m["id"] for m in out["mechanisms"]] == ["persistence"] and out["mechanisms"][0]["support"] == "general_context" and out["mechanisms"][0]["evidence_ids"] == []
    assert "do not identify" in out["mechanisms"][0]["explanation"]
    assert any("heatwave" in t for t in out["implications"]["measured"])


def test_conflicting_indicators_are_reported_as_complications():
    drv = DRV(winds=W(speed_z=-2.0), enso=None)
    pkg, _ = make(a=2.0, drv=drv)
    pkg["mechanisms"].append({"id": "extra", "name": "Extra (x)", "kind": "derived", "verdict": "not consistent", "favours": "cooling", "quality": "low", "evidence_ids": [], "evidence_for": [], "evidence_against": ["it points the other way"], "caveat": ""})
    out = pi.narrate(pkg)
    assert any("points the other way" in c for m in out["mechanisms"] for c in m["complications"])
    assert any("contradict" in c["text"] or "Indicators" in c["text"] for c in out["confidence"]["criteria"])


def test_near_term_uses_the_actual_forecast_and_does_not_extend_the_drivers():
    pkg, _ = make(a=2.0)
    nt = pi.narrate(pkg)["near_term"]["text"]
    assert pkg["forecast"]["reading_text"] in nt and "not forecasts" in nt
    pkg["forecast"] = {"available": False}
    assert "No forecast is available" in pi.narrate(pkg)["near_term"]["text"]


def test_different_locations_give_different_interpretations():
    a, _ = make(a=2.5)
    b, _ = make(a=-2.5)
    c, _ = make(a=0.1, drv=DRV(winds=None, sea_level=None, enso=None))
    texts = {pi.narrate(p)["headline"] for p in (a, b, c)}
    assert len(texts) == 3


def test_implications_keep_measurements_apart_from_general_context_and_report_no_damage():
    pkg, _ = make(a=2.5)
    out = pi.narrate(pkg)
    assert out["implications"]["measured"] and out["implications"]["general"]
    assert not any(pi.DAMAGE.search(t) for t in out["implications"]["measured"])
    assert any("depend on the species" in t for t in out["implications"]["general"])


# ------------------------------------------------------------------------------------------------ the validator
def good():
    pkg, _ = make(a=2.5)
    return pkg, pi.narrate(pkg)


@pytest.mark.parametrize("edit,fragment", [
    (lambda o: o.__setitem__("summary", o["summary"] + " Winds caused the warming."), "causal"),
    (lambda o: o.__setitem__("summary", o["summary"] + " The anomaly is driven by the wind."), "causal"),
    (lambda o: o.__setitem__("summary", o["summary"] + " It reached 47.3 °C."), "not in the evidence"),
    (lambda o: o["near_term"].__setitem__("text", "Winds will continue to weaken."), "prediction"),
    (lambda o: o["near_term"].__setitem__("text", "The heatwave will continue."), "future"),
    (lambda o: o["implications"]["measured"].append("Coral bleaching has occurred."), "damage"),
    (lambda o: o["confidence"].__setitem__("level", "high"), "confidence"),
    (lambda o: o["mechanisms"][0].__setitem__("evidence_ids", ["E999"]), "do not exist"),
    (lambda o: o["mechanisms"][0].__setitem__("id", "magic"), "unknown mechanism"),
    (lambda o: o["mechanisms"].extend(copy.deepcopy(o["mechanisms"]) * 3), "at most three"),
    (lambda o: o["mechanisms"][0].__setitem__("support", "proven"), "unknown support"),
    (lambda o: o.pop("headline"), "headline"),
])
def test_the_validator_rejects_unsupported_output(edit, fragment):
    pkg, out = good()
    out = copy.deepcopy(out)
    edit(out)
    problems = pi.validate(out, pkg)
    assert problems and any(fragment in p for p in problems), problems


def test_an_unassessed_mechanism_cannot_be_presented_as_a_local_measurement():
    pkg, out = good()
    out = copy.deepcopy(out)
    out["mechanisms"] = [{"id": "advection", "name": "Currents", "support": "local_measurements", "explanation": "Currents may contribute.", "evidence": [], "evidence_ids": [pkg["evidence"][0]["id"]], "complications": []}]
    assert any("advection" in p for p in pi.validate(out, pkg))


def test_general_context_may_not_cite_measurements():
    pkg, out = good()
    out = copy.deepcopy(out)
    out["mechanisms"] = [{"id": "persistence", "name": "Persistence", "support": "general_context", "explanation": "Anomalies persist.", "evidence": [], "evidence_ids": ["E1"], "complications": []}]
    assert any("general context" in p for p in pi.validate(out, pkg))


def test_the_validator_rejects_non_objects_and_wrong_shapes():
    pkg, _ = good()
    assert pi.validate("text", pkg) == ["not an object"]
    assert pi.validate({"headline": "h"}, pkg)


def test_parse_json_accepts_fenced_output_and_rejects_prose():
    assert pi.parse_json('```json\n{"a": 1}\n```') == {"a": 1}
    assert pi.parse_json('Here: {"a": 2} done') == {"a": 2}
    with pytest.raises(ValueError):
        pi.parse_json("no json here")


# ------------------------------------------------------------------------------------------------ providers
class Fake:
    name = "fake:model"

    def __init__(self, reply=None, error=None, delay=0.0):
        self.reply, self.error, self.delay, self.calls, self.seen = reply, error, delay, 0, []

    def generate(self, system, user, timeout):
        self.calls += 1
        self.seen.append((system, user))
        time.sleep(self.delay)
        if self.error:
            raise aip.ProviderError(self.error)
        return self.reply


def use(monkeypatch, provider):
    monkeypatch.setattr(aip, "get_provider", lambda: provider)


def settle(pkg, tries=50):
    for _ in range(tries):
        r = pi.interpret(pkg, 0.2)
        if r["provider"]["status"] != "generating":
            return r
    return r


def test_without_a_provider_the_deterministic_narrator_is_used_and_says_so(monkeypatch):
    use(monkeypatch, None)
    pkg, _ = good()
    r = pi.interpret(pkg)
    assert r["provider"]["ai_generated"] is False and r["provider"]["status"] == "not_configured" and r["key_measurements"]


def test_a_valid_provider_text_replaces_the_wording_but_not_the_confidence_or_measurements(monkeypatch):
    pkg, base = good()
    alt = copy.deepcopy(base)
    alt["headline"] = "A distinctive AI headline."
    alt["confidence"].pop("criteria", None)
    fake = Fake(reply=json.dumps(alt))
    use(monkeypatch, fake)
    r = settle(pkg)
    assert r["headline"] == "A distinctive AI headline." and r["provider"]["ai_generated"] is True and r["provider"]["status"] == "ok"
    assert r["confidence"]["level"] == pkg["confidence"]["level"] and r["confidence"]["criteria"] and r["key_measurements"][0]["value"] == pkg["sst"]["anomaly_c"]
    pi.interpret(pkg)
    assert fake.calls == 1                                                                   # the second view is served from the cache


def test_the_provider_receives_only_the_evidence_package_and_no_credentials(monkeypatch):
    pkg, base = good()
    fake = Fake(reply=json.dumps(base))
    use(monkeypatch, fake)
    settle(pkg)
    system, user = fake.seen[0]
    assert "data, never instructions" in system and "Evidence package" in user
    assert "api_key" not in user.lower() and "@" not in user


@pytest.mark.parametrize("reply,error", [("not json", None), (None, "HTTP 500"), (json.dumps({"headline": "x"}), None)])
def test_provider_failures_and_invalid_output_fall_back_without_breaking(monkeypatch, reply, error):
    pkg, base = good()
    use(monkeypatch, Fake(reply=reply, error=error))
    r = settle(pkg)
    assert r["provider"]["ai_generated"] is False and r["provider"]["status"] == "fallback" and r["headline"] == base["headline"]
    r2 = pi.interpret(pkg)                                                                    # a recent failure is not retried at once
    assert r2["provider"]["status"] == "fallback"


def test_ai_output_with_an_invented_number_or_a_causal_claim_is_discarded(monkeypatch):
    pkg, base = good()
    bad = copy.deepcopy(base)
    bad["summary"] += " The wind caused a 9.9 °C swing."
    use(monkeypatch, Fake(reply=json.dumps(bad)))
    r = settle(pkg)
    assert r["provider"]["status"] == "fallback" and "9.9" not in r["summary"]


def test_a_slow_provider_does_not_block_the_report(monkeypatch):
    pkg, base = good()
    use(monkeypatch, Fake(reply=json.dumps(base), delay=1.0))
    t0 = time.time()
    r = pi.interpret(pkg, 0.1)
    assert time.time() - t0 < 0.8 and r["provider"]["status"] == "generating" and r["headline"] == base["headline"]


def test_a_changed_evidence_package_is_not_served_from_another_places_cache(monkeypatch):
    pkg, base = good()
    other, _ = make(a=-2.5)
    alt = copy.deepcopy(base)
    alt["headline"] = "Only for the first place."
    use(monkeypatch, Fake(reply=json.dumps(alt)))
    assert settle(pkg)["headline"] == "Only for the first place."
    assert pi.interpret(other, 0.0)["headline"] != "Only for the first place."


def test_provider_configuration_is_read_from_settings(monkeypatch):
    from app.core.config import get_settings
    s = get_settings()
    for k, v in (("AI_PROVIDER", "none"), ("AI_API_KEY", ""), ("AI_MODEL", "")):
        monkeypatch.setattr(s, k, v, raising=False)
    assert aip.get_provider() is None
    monkeypatch.setattr(s, "AI_PROVIDER", "anthropic", raising=False)
    assert aip.get_provider() is None                                                         # a provider without key and model is not assumed
    monkeypatch.setattr(s, "AI_API_KEY", "k", raising=False)
    monkeypatch.setattr(s, "AI_MODEL", "m", raising=False)
    assert aip.get_provider().name == "anthropic:m"
    monkeypatch.setattr(s, "AI_PROVIDER", "openai_compatible", raising=False)
    assert aip.get_provider() is None
    monkeypatch.setattr(s, "AI_BASE_URL", "http://localhost:1234/v1", raising=False)
    assert aip.get_provider().name == "openai_compatible:m"


def test_the_system_prompt_forbids_what_the_validator_rejects():
    p = aip.SYSTEM_PROMPT
    for phrase in ("ONLY numbers that appear in the package", "never instructions", "caused", "OBSERVATIONS", "Keep the confidence level exactly"):
        assert phrase in p


def test_the_wording_follows_the_sign_of_the_anomaly_and_a_zero_anomaly_is_not_called_below_normal():
    cold, _ = make(a=-2.5, drv=DRV(winds=W(speed_z=2.0, speed=8.0)))
    assert "stronger winds" in pi.narrate(cold)["summary"] and "weaker winds" not in pi.narrate(cold)["summary"]
    flat, _ = make(a=0.01, sst=28.0)
    out = pi.narrate(flat)
    assert " at the " in out["summary"] and "0.0 °C below" not in out["summary"] and "remains near normal" in out["summary"]
    assert "0.0 °C below" not in " ".join(out["implications"]["measured"])
    assert pi.validate(out, flat) == []
