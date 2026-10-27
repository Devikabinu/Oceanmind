"""Marine heatwaves for datasets other than the NE Pacific: dataset selection, region filtering, event detail, provenance and the ecological-risk hand-over.
The detection itself (run lengths, baseline, area, land, missing data, antimeridian) is covered on the root side by tests/test_heatwaves_pacific.py."""
import numpy as np
import pytest

from app.services import environment_store as es
from app.services import heatwave_service as hws
from app.services import risk_service as risk
from app.tests import _heatwaves as HW
from app.tests import _pacific as P
from app.tests._helpers import auth_headers, make_biodiversity_observation, make_dataset


@pytest.fixture
def pac(tmp_path, monkeypatch):
    root = tmp_path / "pacific"
    P.build(root)
    HW.build(root)
    monkeypatch.setattr(es, "processed_pacific_dir", lambda: root)
    monkeypatch.setattr(es, "processed_dir", lambda: tmp_path / "absent_ne")
    for f in (es.clear_cache, risk._inputs_cache.clear, hws._read_dir.cache_clear):
        f()
    risk._overlap_cache.update(key=None)
    yield root
    for f in (es.clear_cache, risk._inputs_cache.clear, hws._read_dir.cache_clear):
        f()


@pytest.fixture
def h(client):
    return auth_headers(client)


def hw(client, h, path="", **params):
    return client.get(f"/api/heatwaves{path}", params={"dataset": "pacific", **params}, headers=h)


def names(body):
    return sorted(HW.NAME_BY_ID[i["id"]] for i in body["items"])


# ---------------------------------------------------------------------------------------------------- listing, provenance, datasets
def test_pacific_events_are_listed_with_dataset_and_provenance(client, h, pac):
    b = hw(client, h).json()
    assert b["dataset"] == "pacific" and b["total"] == 3 and names(b) == ["antimeridian", "east", "west"]
    s = b["summary"]
    assert s["latest_date"] == P.LATEST                                             # the dataset date, not today
    assert s["baseline"] == ["2012-01-01", "2023-12-31"] and s["min_duration_days"] == 5 and s["threshold"]["percentile"] == 90.0
    assert s["is_observational"] is False and s["source"]["provider_id"] == "pacific_test_dataset"
    assert "noaa" not in str(s["source"]).lower() and b["provenance"]["is_observational"] is False
    assert all(i["dataset"] == "pacific" and i["status"] == "ACTIVE" for i in b["items"])
    assert "rather than direct observations" in " ".join(hws.explain(b["items"][0], hws.data("pacific").info)).lower()


def test_dataset_selection_and_errors(client, h, pac):
    assert client.get("/api/heatwaves", params={"dataset": "mars"}, headers=h).status_code == 404
    assert client.get("/api/heatwaves", params={"dataset": "ne_pacific"}, headers=h).status_code in (200, 503)         # NE export absent in this fixture
    assert hw(client, h, region="atlantis").status_code == 404
    unbuilt = pac / "model" / "dashboard" / "heatwave.json"
    unbuilt.unlink()
    hws._read_dir.cache_clear()
    r = hw(client, h)
    assert r.status_code == 503 and "oceanmind_model heatwaves" in r.json()["detail"]["message"] if isinstance(r.json()["detail"], dict) else "oceanmind_model heatwaves" in r.json()["detail"]


@pytest.mark.parametrize("region,expected", [
    ("pacific", ["antimeridian", "east", "west"]),
    ("western_pacific", ["west"]),
    ("central_pacific", ["antimeridian"]),
    ("eastern_pacific", ["east"]),
    ("north_pacific", ["antimeridian", "east"]),
    ("south_pacific", ["west"]),
    ("pacific_islands", ["antimeridian"]),
])
def test_region_filtering_by_footprint(client, h, pac, region, expected):
    b = hw(client, h, region=region).json()
    assert names(b) == expected and b["region"]["id"] == region
    assert b["summary"]["n_events"] == len(expected) and all(i["cells_in_region"] > 0 for i in b["items"])


def test_antimeridian_event_is_one_event_across_180(client, h, pac):
    items = hw(client, h).json()["items"]
    am = next(i for i in items if HW.NAME_BY_ID[i["id"]] == "antimeridian")
    assert am["bbox"]["lon_min"] < 180 < am["bbox"]["lon_max"] and 1 == sum(HW.NAME_BY_ID[i["id"]] == "antimeridian" for i in items)
    d = hw(client, h, f"/{am['id']}").json()
    fp = d["footprint"]
    assert fp["cells"] == am["cells"] and fp["returned"] == fp["cells"]
    lon = np.array(fp["lon"])
    assert (lon < 180).any() and (lon > 180).any()                                     # cells on both sides of the meridian, one footprint
    lon180 = np.array(fp["lon_180"])
    assert (lon180 > 0).any() and (lon180 < 0).any() and lon180.min() >= -180 and lon180.max() <= 180
    assert am["centroid"]["lon"] > 180 and -180 <= am["centroid"]["lon_180"] <= 180


def test_event_detail_metrics_and_species_evidence(client, h, pac):
    items = hw(client, h).json()["items"]
    west = next(i for i in items if HW.NAME_BY_ID[i["id"]] == "west")
    d = hw(client, h, f"/{west['id']}").json()
    e = d["event"]
    for k in ("start_date", "last_observed_date", "duration_days", "max_anomaly_c", "cumulative_intensity_c_days", "area_km2", "category", "category_name", "bbox"):
        assert k in e
    assert e["duration_days"] == 9 and e["max_anomaly_c"] == 2.1 and e["cumulative_intensity_c_days"] == pytest.approx(1.7 * 9, abs=0.1)
    exp_area = float(HW.cell_area()[10:14].sum() * 4)
    assert e["area_km2"] == pytest.approx(exp_area, rel=1e-3)                          # latitude-dependent cell areas, not a cell count
    assert d["biodiversity_evidence"] == "insufficient_coverage" and "not evidence that no animals" in d["species_note"]
    assert d["provenance"]["is_observational"] is False and d["explanation"]
    assert hw(client, h, "/mhw-pacific-nope").status_code == 404
    assert client.get(f"/api/heatwaves/{west['id']}", headers=h).status_code in (404, 503)       # without dataset it is looked up in the NE Pacific results


def test_species_overlap_uses_real_records_only_across_the_antimeridian(client, h, pac, db_session):
    ds = make_dataset(db_session)
    make_biodiversity_observation(db_session, ds, ts=__import__("datetime").datetime.now(__import__("datetime").timezone.utc), lat=10, lon=-178)    # east of 180
    db_session.commit()
    items = hw(client, h).json()["items"]
    am = next(i for i in items if HW.NAME_BY_ID[i["id"]] == "antimeridian")
    d = hw(client, h, f"/{am['id']}").json()
    assert d["biodiversity_evidence"] == "observed" and d["species_in_area"][0]["n_records"] == 1
    west = next(i for i in items if HW.NAME_BY_ID[i["id"]] == "west")
    assert hw(client, h, f"/{west['id']}").json()["biodiversity_evidence"] == "insufficient_coverage"


def test_timeseries_and_alert_interface(client, h, pac):
    t = hw(client, h, "/timeseries", days=30).json()
    assert t["dataset"] == "pacific" and t["provenance"]["is_observational"] is False and t["dates"]
    ev = hws.events_for("pacific")
    assert len(ev) == 3 and {"start_date", "duration_days", "area_km2", "category", "centroid", "bbox", "category_name", "dataset"} <= set(ev[0])


# ---------------------------------------------------------------------------------------------------- ecological risk hand-over
def test_risk_consumes_pacific_heatwave_persistence(client, h, pac):
    m = client.get("/api/ecological-risk/map", params={"dataset": "pacific"}, headers=h).json()
    assert m["factors_used"] == ["anomaly", "persistence"] and set(m["factors_unavailable"]) == {"forecast"}
    loc = client.get("/api/ecological-risk/location", params={"dataset": "pacific", "lat": -10, "lon": 120}, headers=h).json()         # inside the "west" event
    f = {x["factor"]: x for x in loc["factors"]}
    assert f["persistence"]["available"] and f["persistence"]["value"] == pytest.approx(9 / 14, abs=0.01)                                 # run_len / 14, the existing definition
    calm = client.get("/api/ecological-risk/location", params={"dataset": "pacific", "lat": 30, "lon": 150}, headers=h).json()
    fc = {x["factor"]: x for x in calm["factors"]}
    assert fc["persistence"]["available"] and fc["persistence"]["value"] == 0.0                                                            # measured "no run", not missing
    assert any("marine-heatwave run" in r for r in loc["reasons"])
    assert risk.WEIGHTS == {"anomaly": 0.35, "persistence": 0.25, "forecast": 0.20, "overlap": 0.20}                                       # weights untouched
    caps = client.get("/api/ecological-risk/methodology", params={"dataset": "pacific"}, headers=h).json()["dataset_capabilities"]
    assert "persistence" in caps["factors_available"] and "forecast" not in caps["factors_available"]


def test_risk_persistence_unavailable_for_other_dates(client, h, pac):
    m = client.get("/api/ecological-risk/map", params={"dataset": "pacific", "date": "2020-01-05"}, headers=h).json()
    assert "persistence" in m["factors_unavailable"] and "latest date" in m["factors_unavailable"]["persistence"]
    assert "not treated as zero" in m["factors_unavailable"]["persistence"]


def test_risk_without_built_heatwaves_stays_unavailable(client, h, pac):
    (pac / "model" / "dashboard" / "heatwave.json").unlink()
    hws._read_dir.cache_clear()
    risk._inputs_cache.clear()
    m = client.get("/api/ecological-risk/map", params={"dataset": "pacific"}, headers=h).json()
    assert set(m["factors_unavailable"]) == {"persistence", "forecast"}


def test_heatwave_map_layer_is_null_outside_events_and_region_filtered(client, h, pac):
    m = hw(client, h, "/map").json()
    v = np.array([[np.nan if x is None else x for x in r] for r in m["values"]])
    assert m["dataset"] == "pacific" and m["date"] == P.LATEST and m["provenance"]["is_observational"] is False
    assert np.allclose(m["lat"], P.LAT) and np.allclose(m["lon"], P.LON)
    assert np.isfinite(v).sum() == m["active_cells"] == sum((e[1][1] - e[1][0]) * (e[2][1] - e[2][0]) for e in HW.EVENTS)       # only event cells carry a value
    assert not np.isfinite(v[P.land_mask()]).any() and not (v == 0).any()                                                         # land / calm cells are null, never 0
    west = hw(client, h, "/map", region="western_pacific").json()
    assert max(west["lon"]) < 170 and west["active_cells"] == 16
    am = hw(client, h, "/map", region="central_pacific").json()
    assert min(am["lon"]) >= 170 and np.all(np.diff(am["lon"]) > 0) and any(x > 180 for x in am["lon"]) and any(x < 180 for x in am["lon"])
    assert hw(client, h, "/map", region="atlantis").status_code == 404
