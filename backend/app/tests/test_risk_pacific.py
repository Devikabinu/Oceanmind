"""Ecological risk on the Pacific-wide dataset: same methodology, inputs from the processed Pacific data, explicit unavailable / insufficient states."""
from datetime import datetime, timezone

import numpy as np
import pytest

from app.models.species import Species
from app.services import environment_store as es
from app.services import geo_regions as geo
from app.services import risk_service as risk
from app.tests import _pacific as P
from app.tests._helpers import auth_headers, make_biodiversity_observation, make_dataset

HOT = ((10, 14), (20, 26), 2.5)          # rows -18..-6 N, columns 182..202 E: a strong anomaly on the latest day only
AREAS = ["pacific", "western_pacific", "central_pacific", "eastern_pacific", "north_pacific", "south_pacific", "pacific_islands"]


@pytest.fixture
def pac(tmp_path, monkeypatch):
    P.build(tmp_path / "pacific", hot=HOT)
    monkeypatch.setattr(es, "processed_pacific_dir", lambda: tmp_path / "pacific")
    monkeypatch.setattr(es, "processed_dir", lambda: tmp_path / "absent_ne")
    es.clear_cache()
    risk._inputs_cache.clear()
    risk._overlap_cache.update(key=None)
    yield tmp_path / "pacific"
    es.clear_cache()
    risk._inputs_cache.clear()
    risk._overlap_cache.update(key=None)


@pytest.fixture
def h(client):
    return auth_headers(client)


def rmap(client, h, **kw):
    return client.get("/api/ecological-risk/map", params={"dataset": "pacific", **kw}, headers=h)


def arr(m, key="values"):
    return np.array([[np.nan if v is None else v for v in r] for r in m[key]], dtype="float64")


def add_obs(db, lat, lon, n=3):
    ds = make_dataset(db)
    now = datetime.now(timezone.utc)
    for k in range(n):
        o = make_biodiversity_observation(db, ds, ts=now, lat=lat, lon=lon)
        o.scientific_name = f"Species {k}"
    db.commit()


# ---------------------------------------------------------------------------------------------------- map
def test_pacific_risk_map_covers_the_whole_grid(client, h, pac):
    m = rmap(client, h).json()
    assert m["dataset"] == "pacific" and m["date"] == P.LATEST and m["region"]["id"] == "pacific"
    assert m["source"]["is_observational"] is False and "noaa" not in str(m["source"]).lower()
    assert np.allclose(m["lat"], P.LAT) and np.allclose(m["lon"], P.LON)             # Pacific grid alignment, no second grid
    assert np.array(m["status"]).shape == (P.H, P.W) and m["downsample_factor"] == 1
    assert m["counts"]["assessed"] > 0 and m["weights"] == risk.WEIGHTS


def test_land_missing_and_insufficient_cells_are_explicit_not_zero(client, h, pac):
    m = rmap(client, h).json()
    v, st = arr(m), np.array(m["status"])
    land = P.land_mask()
    assert (st[land] == risk.LAND).all() and np.isnan(v[land]).all()
    for r, c in P.MISSING_CELLS:                                                       # ocean cell without SST that day
        assert st[r, c] == risk.UNAVAILABLE and np.isnan(v[r, c])
    r, c = P.NO_CLIM_CELL                                                              # SST but no climatology: anomaly (core factor) cannot be computed
    assert st[r, c] == risk.INSUFFICIENT and np.isnan(v[r, c])
    assert m["counts"]["land"] == int(land.sum())
    assert not np.isnan(v[(st == risk.ASSESSED)]).any()


def test_heatwave_and_forecast_are_unavailable_not_zero(client, h, pac):
    m = rmap(client, h).json()
    assert m["factors_used"] == ["anomaly"]
    assert set(m["factors_unavailable"]) == {"persistence", "forecast"}
    assert all("not treated as zero" in why for why in m["factors_unavailable"].values())
    loc = client.get("/api/ecological-risk/location", params={"dataset": "pacific", "lat": -10, "lon": -170}, headers=h).json()
    f = {x["factor"]: x for x in loc["factors"]}
    assert f["persistence"]["available"] is False and f["persistence"]["value"] is None and f["persistence"]["reason"]
    assert f["forecast"]["available"] is False and f["forecast"]["value"] is None
    assert set(loc["unavailable_factors"]) == {"persistence", "forecast"}


def test_risk_classification_uses_existing_bands(client, h, pac):
    m = rmap(client, h).json()
    v, lv = arr(m), np.array(m["levels"])
    assert lv[11, 22] == 3 and v[11, 22] == pytest.approx(1.0, abs=0.01)             # +2.5 degC on top of ~0.7 -> anomaly factor capped at 1 -> CRITICAL
    calm = v[(np.array(m["status"]) == 0)]
    assert calm.min() < 0.3
    assert (lv[np.isfinite(v)] == np.digitize(v[np.isfinite(v)], [0.25, 0.5, 0.75])).all()
    assert [risk.level_for(x) for x in (0.1, 0.3, 0.6, 0.9)] == ["LOW", "MEDIUM", "HIGH", "CRITICAL"]
    assert lv[~np.isfinite(v)].max() == -1                                           # no score -> no level, never LOW


@pytest.mark.parametrize("rid", AREAS)
def test_every_pacific_area_returns_its_own_grid(client, h, pac, rid):
    m = rmap(client, h, region=rid).json()
    reg = geo.get_region(rid)
    lat, lon, st = np.array(m["lat"]), np.array(m["lon"]), np.array(m["status"])
    assert m["region"]["id"] == rid and np.all(np.diff(lon) > 0)
    inside = geo.region_mask(reg, lat, lon)
    assert (st[~inside] == risk.OUTSIDE).all() and (st[inside] != risk.OUTSIDE).all()
    assert m["counts"]["assessed"] > 0
    if rid != "pacific":
        assert m["counts"]["assessed"] < rmap(client, h).json()["counts"]["assessed"]


def test_regions_give_different_risk(client, h, pac):
    means = {r: np.nanmean(arr(rmap(client, h, region=r).json())) for r in ("central_pacific", "eastern_pacific", "western_pacific")}
    assert means["central_pacific"] > means["eastern_pacific"] and means["central_pacific"] > means["western_pacific"]      # the hot block is in the central Pacific


def test_dataset_selection_and_errors(client, h, pac):
    assert client.get("/api/ecological-risk/map", params={"dataset": "mars"}, headers=h).status_code == 404
    assert rmap(client, h, region="atlantis").status_code == 404
    assert rmap(client, h, date="2019-01-01").status_code == 404
    assert rmap(client, h, date="2020-01-05").json()["date"] == "2020-01-05"
    assert client.get("/api/ecological-risk/map", params={"dataset": "ne_pacific"}, headers=h).status_code in (200, 503)


# ---------------------------------------------------------------------------------------------------- biodiversity evidence
def test_no_biodiversity_rows_means_overlap_unavailable(client, h, pac):
    loc = client.get("/api/ecological-risk/location", params={"dataset": "pacific", "lat": -10, "lon": -170}, headers=h).json()
    assert loc["biodiversity_evidence"] == "unavailable" and loc["n_species"] is None
    f = {x["factor"]: x for x in loc["factors"]}
    assert f["overlap"]["available"] is False
    assert loc["evidence_completeness"] == pytest.approx(0.35 / 1.0, abs=0.01)


def test_cells_without_records_are_insufficient_coverage_not_zero_overlap(client, h, pac, db_session):
    add_obs(db_session, -10, -170)                                                   # records only in one 2x2 block
    away = client.get("/api/ecological-risk/location", params={"dataset": "pacific", "lat": 30, "lon": -150}, headers=h).json()
    assert away["biodiversity_evidence"] == "insufficient_coverage" and away["n_species"] == 0
    f = {x["factor"]: x for x in away["factors"]}
    assert f["overlap"]["available"] is False and f["overlap"]["value"] is None       # NOT 0
    assert away["score"] == pytest.approx(f["anomaly"]["value"], abs=0.002)           # score from the anomaly alone, not diluted by a fake zero
    here = client.get("/api/ecological-risk/location", params={"dataset": "pacific", "lat": -10, "lon": -170}, headers=h).json()
    assert here["biodiversity_evidence"] == "observed" and here["n_species"] == 3
    fh = {x["factor"]: x for x in here["factors"]}
    assert fh["overlap"]["available"] and fh["overlap"]["value"] == pytest.approx(1.0)
    assert here["evidence_completeness"] > away["evidence_completeness"]


def test_ne_pacific_keeps_zero_overlap_for_empty_blocks(outputs, db_session):
    add_obs(db_session, 21.0, -158.0)
    e = risk.legacy_inputs(__import__("app.services.environment", fromlist=["env"]).env())
    g = risk.factor_grids(e, risk.species_overlap_blocks(db_session, e))
    assert g["used"] == ["anomaly", "persistence", "forecast", "overlap"]
    assert (g["bio"] == 1).sum() > 0 and e.species_sampled is True


# ---------------------------------------------------------------------------------------------------- location / areas / species
def test_location_land_outside_and_longitude_conventions(client, h, pac):
    q = lambda lat, lon: client.get("/api/ecological-risk/location", params={"dataset": "pacific", "lat": lat, "lon": lon}, headers=h)  # noqa: E731
    assert q(50, 110).status_code == 404 and "land" in q(50, 110).json()["detail"].lower()
    assert q(70, 200).status_code == 404
    a, b = q(-10, -170).json(), q(-10, 190).json()
    assert a["cell"]["lat"] == b["cell"]["lat"] and a["cell"]["lon"] == b["cell"]["lon"] and a["level"] == "CRITICAL" and a["status"] == "assessed"
    r, c = P.MISSING_CELLS[0]
    miss = q(P.LAT[r], P.LON[c]).json()
    assert miss["status"] == "unavailable" and miss["score"] is None and miss["level"] is None
    r, c = P.NO_CLIM_CELL
    ins = q(P.LAT[r], P.LON[c]).json()
    assert ins["status"] == "insufficient_data" and ins["score"] is None and ins["level"] is None


def test_areas_by_region_and_dataset(client, h, pac):
    q = lambda **kw: client.get("/api/ecological-risk/areas", params={"dataset": "pacific", "min_level": "LOW", "limit": 200, **kw}, headers=h)  # noqa: E731
    whole = q().json()
    central = q(region="central_pacific").json()
    west = q(region="western_pacific").json()
    assert whole["dataset"] == "pacific" and whole["total"] > central["total"] > 0 and west["total"] > 0
    assert whole["items"][0]["level"] == "CRITICAL" and 180 < whole["items"][0]["lon"] < 205
    assert "lon_180" in whole["items"][0] and set(whole["factors_unavailable"]) == {"persistence", "forecast"}
    assert q(region="mars").status_code == 404
    hi = q(min_level="CRITICAL").json()
    assert hi["total"] >= 1 and all(i["level"] == "CRITICAL" for i in hi["items"])


def test_species_exposure_on_pacific_and_unknown_status(client, h, pac, db_session):
    db_session.add(Species(aphia_id=900001, scientific_name="Species 0", taxon_group="Fish", sources={}))
    db_session.add(Species(aphia_id=900002, scientific_name="Never recorded", taxon_group="Fish", iucn_category="EN", sources={}))
    db_session.commit()
    add_obs(db_session, -10, -170, n=2)
    body = client.get("/api/ecological-risk/species", params={"dataset": "pacific"}, headers=h).json()
    by = {x["scientific_name"]: x for x in body["items"]}
    s0 = by["Species 0"]
    assert s0["available"] and s0["dataset"] == "pacific" and s0["level"] == "CRITICAL" and s0["conservation_status"] == "Status not confirmed"
    assert s0["forecast_exposure"] is None and set(s0["unavailable_factors"]) == {"persistence", "forecast"}
    f = {x["factor"]: x for x in s0["factors"]}
    assert f["forecast"]["available"] is False and f["persistence"]["available"] is False
    nr = by["Never recorded"]
    assert nr["available"] is False and nr["status"] == "insufficient_data" and "No observations is not the same as no animals" in nr["message"]
    assert nr["conservation_status"] == "EN"


def test_methodology_reports_dataset_capabilities(client, h, pac):
    base = client.get("/api/ecological-risk/methodology", headers=h).json()
    assert "dataset_capabilities" not in base and base["weights"] == risk.WEIGHTS         # existing contract and weights untouched
    m = client.get("/api/ecological-risk/methodology", params={"dataset": "pacific"}, headers=h).json()
    caps = m["dataset_capabilities"]
    assert caps["factors_available"] == ["anomaly", "overlap"] and set(caps["factors_unavailable"]) == {"persistence", "forecast"}
    assert m["weights"] == risk.WEIGHTS


# ---------------------------------------------------------------------------------------------------- NE Pacific compatibility
def test_ne_pacific_explicit_dataset_matches_default(client, h, outputs):
    default = client.get("/api/ecological-risk/location", params={"lat": 21.0, "lon": -159.0}, headers=h).json()
    explicit = client.get("/api/ecological-risk/location", params={"lat": 21.0, "lon": -159.0, "dataset": "ne_pacific"}, headers=h).json()
    assert default == explicit and default["status"] == "assessed" and default["level"] in {"HIGH", "CRITICAL"}
    assert default["biodiversity_evidence"] in {"unavailable", "none_recorded", "observed"}
    a1 = client.get("/api/ecological-risk/areas", params={"min_level": "LOW", "limit": 200}, headers=h).json()
    a2 = client.get("/api/ecological-risk/areas", params={"min_level": "LOW", "limit": 200, "dataset": "ne_pacific"}, headers=h).json()
    assert a1["items"] == a2["items"] and a1["total"] >= 1
    m = client.get("/api/ecological-risk/map", params={"dataset": "ne_pacific"}, headers=h).json()
    assert m["dataset"] == "ne_pacific" and m["counts"]["assessed"] > 0 and m["factors_used"][:3] == ["anomaly", "persistence", "forecast"]
