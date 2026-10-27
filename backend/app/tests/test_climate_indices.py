"""ONI / PDO context: parsing of the published files, month lookup, staleness, and the rule that El Niño, La Niña or the PDO are only mentioned when index data are loaded."""
import json

import pytest

from app.services import climate_indices as ci
from app.services import explain_service

ONI_TEXT = """  SEAS  YR   TOTAL   ANOM
  DJF 2026  27.00  -0.30
  NDJ 2025  26.90  -0.40
  JAS 2026  29.12   2.16
  ASO 2026  99.90  99.90
  JJA 2026  29.09   0.20
"""
PDO_TEXT = """ ERSST PDO Index:
Year  Jan   Feb   Mar   Apr   May   Jun   Jul   Aug   Sep   Oct   Nov   Dec
2026 -1.24 -1.00 -1.42 -1.62 -1.68 -1.72 -2.16 -1.89 -1.55 99.99 99.99 99.99
2020  0.50  0.40  0.30  0.20  0.10  0.00 -0.10 -0.20 -0.30 -0.40 -0.50 -0.60
"""


@pytest.fixture
def indices(tmp_path, monkeypatch):
    f = tmp_path / "indices.json"
    monkeypatch.setattr(ci, "index_file", lambda: f)
    oni, pdo = ci.parse_oni(ONI_TEXT), ci.parse_pdo(PDO_TEXT)
    f.write_text(json.dumps({"oni": {"series": oni, "retrieved_at": "2026-10-23T00:00:00+00:00"}, "pdo": {"series": pdo, "retrieved_at": "2026-10-23T00:00:00+00:00"}}))
    ci._load_cached.cache_clear()
    return f


def test_files_are_parsed_by_the_centre_month_and_missing_values_are_dropped():
    oni = ci.parse_oni(ONI_TEXT)
    assert oni["2026-01"] == {"value": -0.3, "season": "DJF 2026"} and oni["2025-12"]["season"] == "NDJ 2025" and oni["2026-08"]["value"] == 2.16
    assert "2026-09" not in oni                                           # 99.90 marks a season that is not available yet
    pdo = ci.parse_pdo(PDO_TEXT)
    assert pdo["2026-09"]["value"] == -1.55 and "2026-10" not in pdo and pdo["2020-01"]["value"] == 0.5


def test_context_reports_noaa_classification_and_phase(indices):
    c = ci.context("2026-08-15")
    assert c["oni"]["state"] == "El Niño conditions" and c["oni"]["value"] == 2.16 and c["oni"]["season"] == "JAS 2026"
    assert c["pdo"]["phase"] == "negative" and c["pdo"]["month"] == "2026-08"
    assert ci.context("2026-01-10")["oni"]["state"] == "neutral"


def test_values_older_than_three_months_are_not_used_and_missing_files_give_none(indices, tmp_path, monkeypatch):
    assert "oni" not in (ci.context("2026-12-20") or {})                   # the latest ONI value is August: December would be a stale guess
    assert ci.context("2030-01-01") is None
    monkeypatch.setattr(ci, "index_file", lambda: tmp_path / "missing.json")
    ci._load_cached.cache_clear()
    assert ci.context("2026-08-15") is None


def ctx(**over):
    base = {"date": "2026-08-15", "sst": 29.0, "normal": 27.5, "anomaly": 1.5, "region_name": "Equatorial Pacific", "region_percentile": 95, "neighbourhood_mean": 1.4, "neighbourhood_cells": 24,
            "heatwave": {"inside": False, "available": True}, "history": {"percentile": 99, "n": 400}, "baseline": ["2002-01-01", "2023-12-31"], "lat": 2.0, "lon_180": -140.0}
    base.update(over)
    return base


def why(e):
    return next(s for s in e["sections"] if s["id"] == "why")["bullets"]


def test_explanation_cites_the_indices_as_observed_context_and_as_a_possible_association_only(indices):
    b = why(explain_service.explain_anomaly(ctx(climate=ci.context("2026-08-15"))))
    assert any(t.startswith("Observed:") and "Oceanic Niño Index for JAS 2026 is +2.16" in t for t in b)
    assert any(t.startswith("Observed:") and "Pacific Decadal Oscillation index" in t and "negative phase" in t for t in b)
    poss = [t for t in b if t.startswith("Possible explanation")]
    assert any("El Niño" in t and "has not tested it" in t for t in poss)
    assert any("basin-wide conditions and do not show that they caused" in t for t in b if t.startswith("Not established"))


def test_no_claim_about_climate_modes_without_index_data_or_outside_the_affected_area(indices):
    none = why(explain_service.explain_anomaly(ctx(climate=None)))
    assert not any(("El Niño" in t or "La Niña" in t or "Oceanic" in t) for t in none if t.startswith(("Observed", "Inferred", "Possible")))
    assert any("no climate-index data are loaded" in t for t in none)
    far = why(explain_service.explain_anomaly(ctx(climate=ci.context("2026-08-15"), lat=-45.0, lon_180=160.0)))     # southwest Pacific: no ENSO association is suggested
    assert not any(t.startswith("Possible explanation") and "El Niño" in t for t in far)
    neutral = why(explain_service.explain_anomaly(ctx(climate=ci.context("2026-01-10"))))
    assert not any("El Niño" in t and t.startswith("Possible explanation") for t in neutral)
