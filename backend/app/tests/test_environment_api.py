"""/api/environment (and the dataset/region extension of /api/monitor/map) against a tiny synthetic processed-Pacific directory, plus geo_regions units
and integration checks against the real processed outputs when they exist."""
import math
import time

import numpy as np
import pytest

from app.services import environment_store as es
from app.services import geo_regions as geo
from app.tests import _pacific as P
from app.tests._helpers import auth_headers

REGION_IDS = ["pacific", "western_pacific", "central_pacific", "eastern_pacific", "north_pacific", "south_pacific", "equatorial_pacific", "east_asia", "southeast_asia",
              "australia_new_zealand", "melanesia", "micronesia", "polynesia", "pacific_islands", "eastern_pacific_americas"]


@pytest.fixture
def pacific(tmp_path, monkeypatch):
    P.build(tmp_path / "pacific")
    monkeypatch.setattr(es, "processed_pacific_dir", lambda: tmp_path / "pacific")
    monkeypatch.setattr(es, "processed_dir", lambda: tmp_path / "absent_ne")
    es.clear_cache()
    yield tmp_path / "pacific"
    es.clear_cache()


@pytest.fixture
def h(client):
    return auth_headers(client)


def get(client, h, path, **params):
    return client.get(f"/api/environment/{path}", params={"dataset": "pacific", **params}, headers=h)


def arr(body):
    return np.array([[np.nan if v is None else v for v in row] for row in body["values"]], dtype="float64")


# ------------------------------------------------------------------------------------------------------- geo_regions units
def test_fourteen_regions_stable_ids():
    assert list(geo.REGIONS) == REGION_IDS
    for r in geo.REGIONS.values():
        assert r.name and r.view and (r.parent is None) == (r.id == "pacific")


def test_bbox_antimeridian_is_one_continuous_box_and_splits_on_wrapped_axes():
    (box,) = geo.bbox_boxes(-10, 10, 170, -170)               # 170E .. 190E
    assert (box.lon_min, box.lon_max) == (170, 190)
    lon180 = np.arange(-180, 180, 1.0) + 0.5                   # a -180..180 axis: the same box is two column runs
    runs = geo.column_runs(geo.box_mask([0.0], lon180, [box])[0])
    assert len(runs) == 2
    assert len(geo.column_runs(geo.box_mask([0.0], np.arange(100.5, 290), [box])[0])) == 1


def test_bbox_validation():
    for bad in [(10, -10, 0, 10), (-100, 10, 0, 10), (0, 10, -400, 10)]:
        with pytest.raises(ValueError):
            geo.bbox_boxes(*bad)


# ------------------------------------------------------------------------------------------------------- catalogue endpoints
def test_requires_auth(client, pacific):
    assert client.get("/api/environment/map").status_code == 401


def test_regions_endpoint_lists_all_14(client, h):
    body = client.get("/api/environment/regions", headers=h).json()["regions"]
    assert [r["id"] for r in body] == REGION_IDS
    assert next(r for r in body if r["id"] == "central_pacific")["crosses_antimeridian"] is True
    assert all(r["map_extent"] for r in body)


def test_datasets_and_dates_use_actual_latest(client, h, pacific):
    d = client.get("/api/environment/datasets", headers=h).json()
    pac = next(x for x in d["datasets"] if x["id"] == "pacific")
    assert pac["latest_date"] == P.LATEST and pac["available"] and pac["provider"]["is_observational"] is False
    ne = next(x for x in d["datasets"] if x["id"] == "ne_pacific")
    assert ne["available"] is False
    assert get(client, h, "dates").json()["latest_date"] == P.LATEST


# ------------------------------------------------------------------------------------------------------- map: SST, anomaly, dates
def test_entire_pacific_latest_sst(client, h, pacific):
    b = get(client, h, "map").json()
    assert b["date"] == P.LATEST == b["latest_available_date"] and b["region"]["id"] == "pacific"
    v = arr(b)
    assert v.shape == (P.H, P.W) and b["downsample_factor"] == 1
    assert b["lon"][0] == P.LON[0] and b["lon"][-1] == P.LON[-1] and np.all(np.diff(b["lon"]) > 0)       # continuous across 180, no gap
    assert np.nanmax(np.diff(b["lon"])) == 4.0
    land = P.land_mask()
    assert np.isnan(v[land]).all()                                                                       # land is never valid
    sst, _ = P.raw_fields(19)
    ok = ~land
    for r, c in P.MISSING_CELLS:
        ok[r, c] = False
    assert v[ok] == pytest.approx(sst[ok], abs=0.01)                                                   # de-normalised exactly
    assert b["min"] == pytest.approx(np.nanmin(v)) and b["max"] == pytest.approx(np.nanmax(v))


def test_anomaly_comes_from_preprocessing_channel(client, h, pacific):
    b = get(client, h, "map", layer="anomaly").json()
    v = arr(b)
    _, anom = P.raw_fields(19)
    r, c = P.NO_CLIM_CELL
    assert math.isnan(v[r, c])                                       # no climatology that day -> missing, not 0
    ok = ~P.land_mask()
    ok[r, c] = False
    for rr, cc in P.MISSING_CELLS:
        ok[rr, cc] = False
    assert v[ok] == pytest.approx(anom[ok], abs=0.01)
    assert b["diverging"] is True


def test_missing_cells_are_null_not_zero_and_counted(client, h, pacific):
    b = get(client, h, "map", include_status="true").json()
    v, st = arr(b), np.array(b["status"])
    for r, c in P.MISSING_CELLS:
        assert math.isnan(v[r, c]) and st[r, c] == es.MISSING
    assert (st[P.land_mask()] == es.LAND).all()
    cov = b["coverage"]
    n_missing = len(P.MISSING_CELLS)
    assert cov["missing_cells"] == n_missing + 0 and cov["total_cells"] == P.H * P.W
    assert cov["valid_cells"] == int((~P.land_mask()).sum()) - n_missing
    assert cov["valid_pct_of_ocean"] < 100


def test_coverage_endpoint_math(client, h, pacific):
    c = get(client, h, "coverage").json()["coverage"]
    assert c["land_cells"] + c["valid_cells"] + c["missing_cells"] == c["total_cells"]
    assert c["valid_pct_of_ocean"] == pytest.approx(100 * c["valid_cells"] / c["ocean_cells"], abs=0.01)
    r = get(client, h, "coverage", region="east_asia").json()
    assert r["coverage"]["total_cells"] < c["total_cells"]


def test_explicit_date_and_missing_date(client, h, pacific):
    b = get(client, h, "map", date="2020-01-05").json()
    assert b["date"] == "2020-01-05"
    assert np.nanmean(arr(b)) < np.nanmean(arr(get(client, h, "map").json()))                             # day index drives the field upward
    r = get(client, h, "map", date="2019-06-01")
    assert r.status_code == 404
    d = r.json()["detail"]
    assert d["code"] == "no_data_for_date" and d["latest_available_date"] == P.LATEST and d["available_range"]["first"] == "2020-01-01"


def test_invalid_inputs(client, h, pacific):
    assert get(client, h, "map", region="atlantis").status_code == 404
    assert get(client, h, "map", region="atlantis").json()["detail"]["code"] == "unknown_region"
    assert get(client, h, "map", date="2020-13-45").status_code in (404, 422)
    assert get(client, h, "map", date="not-a-date").status_code == 422
    assert get(client, h, "map", layer="salinity").status_code == 422
    assert client.get("/api/environment/map", params={"dataset": "mars"}, headers=h).status_code == 404
    assert get(client, h, "map", min_lat=10, max_lat=-10, min_lon=0, max_lon=10).status_code == 422
    assert get(client, h, "map", min_lat=10).status_code == 422
    assert client.get("/api/environment/map", headers=h).status_code == 503              # default dataset (ne_pacific) is not built here


# ------------------------------------------------------------------------------------------------------- regions
@pytest.mark.parametrize("rid", REGION_IDS)
def test_every_region_subset(client, h, pacific, rid):
    b = get(client, h, "map", region=rid, include_status="true").json()
    reg = geo.get_region(rid)
    assert b["region"]["id"] == rid
    full = es.get_store("pacific")
    mask = es.selection_mask(full, rid, None)
    assert b["coverage"]["total_cells"] == int(mask.sum())
    v, st = arr(b), np.array(b["status"])
    assert (st[~np.isfinite(v)] != es.VALID).all()
    assert not (np.isfinite(v) & (st != es.VALID)).any()
    lat, lon = np.array(b["lat"]), np.array(b["lon"])
    assert np.all(np.diff(lon) > 0) and np.all(np.diff(lat) > 0)
    inside = geo.region_mask(reg, lat, lon)
    assert (st[inside] != es.OUTSIDE).all() or reg.dataset_wide or rid in ("pacific_islands",)
    assert (st[~inside] == es.OUTSIDE).all()


def test_antimeridian_region_is_continuous(client, h, pacific):
    b = get(client, h, "map", region="central_pacific").json()
    lon = np.array(b["lon"])
    assert lon.min() >= 170 and lon.max() < 240 and (lon > 180).any() and (lon < 180).any()
    assert np.all(np.diff(lon) == 4.0)                                                           # no jump at 180
    s = get(client, h, "map", min_lat=-20, max_lat=20, min_lon=170, max_lon=-170).json()         # user box 170E..190E
    assert s["lon"][0] <= 174 and s["lon"][-1] >= 186 and np.all(np.diff(s["lon"]) == 4.0)


def test_western_central_eastern_partition_the_pacific(client, h, pacific):
    tot = {r: get(client, h, "coverage", region=r).json()["coverage"]["total_cells"] for r in ("pacific", "western_pacific", "central_pacific", "eastern_pacific")}
    assert tot["western_pacific"] + tot["central_pacific"] + tot["eastern_pacific"] == tot["pacific"]
    n, s = (get(client, h, "coverage", region=r).json()["coverage"]["total_cells"] for r in ("north_pacific", "south_pacific"))
    assert n + s == tot["pacific"]


def test_region_outside_dataset_gives_clear_empty_answer(client, h, pacific, monkeypatch):
    b = get(client, h, "map", min_lat=70, max_lat=80, min_lon=0, max_lon=10).json()
    assert b["values"] == [] and "does not overlap" in b["message"] and b["coverage"]["total_cells"] == 0
    assert b["coverage"]["valid_pct_of_ocean"] is None


# ------------------------------------------------------------------------------------------------------- metadata, size, speed
def test_provider_metadata_propagates_and_is_not_labelled_noaa(client, h, pacific):
    b = get(client, h, "map").json()
    assert b["dataset"]["provider"]["provider_id"] == "pacific_test_dataset"
    assert b["dataset"]["provider"]["is_observational"] is False and b["kind"] == "generated"
    text = str(b["dataset"]).lower()
    assert "noaa" not in text and "copernicus" not in text
    assert b["lon_convention"] and b["dataset"]["extent"]["lon_max"] > 180


def test_map_is_downsampled_to_requested_size(client, h, pacific):
    b = get(client, h, "map", max_cells=200).json()
    n = len(b["lat"]) * len(b["lon"])
    assert b["downsample_factor"] > 1 and n <= 200 + 2 * (len(b["lat"]) + len(b["lon"]))
    assert b["native_shape"] == [P.H, P.W]
    assert b["coverage"]["total_cells"] == P.H * P.W                                              # coverage always refers to native cells
    v = arr(b)
    assert np.isnan(v).any() and np.nanmin(v) >= np.nanmin(arr(get(client, h, "map").json())) - 0.01


def test_monitor_map_extension_is_backward_compatible(client, h, pacific):
    b = client.get("/api/monitor/map", params={"layer": "observed", "dataset": "pacific", "region": "east_asia"}, headers=h).json()
    for k in ("layer", "label", "kind", "unit", "horizon", "date", "diverging", "coverage", "lat", "lon", "values", "min", "max"):
        assert k in b
    assert b["layer"] == "observed" and "lat_min" in b["coverage"] and b["coverage_stats"]["total_cells"] > 0
    assert client.get("/api/monitor/map", params={"layer": "forecast", "dataset": "pacific"}, headers=h).status_code == 422


def test_legacy_monitor_map_without_dataset_unchanged(client, h, outputs):
    b = client.get("/api/monitor/map", params={"layer": "observed"}, headers=h).json()
    assert b["layer"] == "observed" and "coverage_stats" not in b


def test_ocean_map_workflow_entire_pacific_then_subsets(client, h, pacific):
    """What the future Ocean Map will do: whole Pacific latest SST first, then Western/Central/Eastern subsets of the same day."""
    whole = get(client, h, "map", layer="sst", date="latest").json()
    land = P.land_mask()
    full = es.get_store("pacific")
    for rid in ("western_pacific", "central_pacific", "eastern_pacific"):
        sub = get(client, h, "map", layer="sst", date="latest", region=rid).json()
        assert sub["date"] == whole["date"] and sub["dataset"]["id"] == "pacific"
        la, lo, v = np.array(sub["lat"]), np.array(sub["lon"]), arr(sub)
        i = np.searchsorted(full.lat, la)
        j = np.searchsorted(full.lon, lo)
        assert not np.isfinite(v[land[np.ix_(i, j)]]).any()                                         # no land shown as valid
        ref = arr(whole)[np.ix_(i, j)]
        both = np.isfinite(v)
        assert v[both] == pytest.approx(ref[both])                                                  # same numbers as the whole-basin view


def test_speed(client, h, pacific):
    t = time.perf_counter()
    for layer in ("sst", "anomaly"):
        get(client, h, "map", layer=layer)
        get(client, h, "map", layer=layer, region="central_pacific")
    assert time.perf_counter() - t < 5


# ------------------------------------------------------------------------------------------------------- real processed outputs (skipped when absent)
def _real(path):
    p = path
    return p if (p / "meta.json").exists() else None


def test_real_pacific_output_if_built(client, h):
    es.clear_cache()
    real = es.processed_pacific_dir()
    if not _real(real):
        pytest.skip("processed_pacific/ not built")
    t = time.perf_counter()
    b = client.get("/api/environment/map", params={"dataset": "pacific"}, headers=h).json()
    a = client.get("/api/environment/map", params={"dataset": "pacific", "layer": "anomaly", "region": "central_pacific"}, headers=h).json()
    assert time.perf_counter() - t < 5
    assert b["date"] == b["latest_available_date"] and b["kind"] == ("observed" if b["dataset"]["provider"]["is_observational"] else "generated")
    assert len(b["lon"]) == b["native_shape"][1] // b["downsample_factor"] + (b["native_shape"][1] % b["downsample_factor"] > 0)
    assert b["coverage"]["valid_cells"] > 0 and a["coverage"]["total_cells"] < b["coverage"]["total_cells"]
    v = arr(b)
    assert np.isfinite(v).sum() <= b["coverage"]["valid_cells"] and -5 < np.nanmin(v) and np.nanmax(v) < 40


def test_ne_pacific_dataset_regression_if_built(client, h):
    es.clear_cache()
    ref = es.dataset_refs()["ne_pacific"]
    if not (ref.path / "meta.json").exists():
        pytest.skip("processed/ NE Pacific dataset not present")
    b = client.get("/api/environment/map", headers=h).json()                  # default dataset
    assert b["dataset"]["id"] == "ne_pacific" and b["dataset"]["provider"]["is_observational"] is True
    assert b["coverage"]["valid_cells"] > 0
    lon = np.array(b["lon"])
    assert lon.min() < -100 and lon.max() < -100                                # NE Pacific stays on its own -180..180 axis


# ------------------------------------------------------------------------------------------------------- point query
def pt(client, h, lat, lon, **params):
    return client.get("/api/environment/point", params={"dataset": "pacific", "lat": lat, "lon": lon, **params}, headers=h)


def expected(lat, lon, day=19):
    i = int(np.argmin(np.abs(P.LAT - lat)))
    j = int(np.argmin(np.abs(P.LON - lon)))
    sst, anom = P.raw_fields(day)
    return i, j, float(sst[i, j]), float(anom[i, j])


@pytest.mark.parametrize("name,lat,lon", [("western", -10, 141), ("central", 1, 201), ("eastern", 1, 250), ("north", 41, 190), ("south", -41, 161),
                                          ("islands", -15, 178)])
def test_pacific_points_in_every_area(client, h, pacific, name, lat, lon):
    b = pt(client, h, lat, lon).json()
    i, j, sst, anom = expected(lat, lon)
    assert b["status"] == "valid" and b["in_coverage"] and b["is_ocean"]
    assert b["sst"] == pytest.approx(sst, abs=0.01) and b["anomaly"] == pytest.approx(anom, abs=0.01)
    assert b["cell"]["lat"] == P.LAT[i] and b["cell"]["lon"] == P.LON[j]
    assert b["date"] == P.LATEST == b["latest_available_date"] and b["unit"] == "degC"
    assert b["query"] == {"lat": lat, "lon": lon}


def test_longitude_conventions_resolve_to_the_same_cell(client, h, pacific):
    a, b = pt(client, h, 1, 250).json(), pt(client, h, 1, -110).json()
    assert a["cell"] == b["cell"] and a["sst"] == b["sst"]
    assert pt(client, h, 1, 201).json()["cell"] == pt(client, h, 0, -160).json()["cell"]


def test_antimeridian_points(client, h, pacific):
    cells = {lon: pt(client, h, 0, lon).json()["cell"] for lon in (179, -179, 180, -180, 181)}
    assert cells[179]["lon"] == 178 and cells[-179]["lon"] == 182 and cells[181]["lon"] == 182
    assert cells[180]["lon"] == 182 and cells[-180] == cells[180]                      # 180 and -180 are the same meridian
    assert cells[179]["lon_180"] == 178 and cells[-179]["lon_180"] == -178           # reported in both conventions
    assert all(pt(client, h, 0, lon).json()["status"] == "valid" for lon in (179, -179, 180, -180))


def test_point_matches_the_map_value_for_the_same_cell(client, h, pacific):
    m = get(client, h, "map").json()
    v = arr(m)
    b = pt(client, h, -10, 141).json()
    i, j = b["cell"]["row"], b["cell"]["col"]
    assert b["sst"] == pytest.approx(v[i, j], abs=0.01)


def test_land_outside_and_missing_are_distinct_no_data(client, h, pacific):
    land = pt(client, h, 50, 110).json()
    assert land["status"] == "land" and land["sst"] is None and land["anomaly"] is None and land["is_ocean"] is False and land["cell"]
    out = pt(client, h, 70, 200).json()
    assert out["status"] == "outside_dataset" and out["in_coverage"] is False and out["sst"] is None and out["cell"] is None
    assert pt(client, h, 0, 295).json()["status"] == "outside_dataset"
    r, c = P.MISSING_CELLS[0]
    miss = pt(client, h, P.LAT[r], P.LON[c]).json()
    assert miss["status"] == "missing" and miss["sst"] is None and miss["anomaly"] is None and miss["is_ocean"] is True
    assert pt(client, h, P.LAT[r], P.LON[c], date="2020-01-05").json()["status"] == "valid"        # only missing on the latest day


def test_anomaly_missing_without_climatology_but_sst_kept(client, h, pacific):
    r, c = P.NO_CLIM_CELL
    b = pt(client, h, P.LAT[r], P.LON[c]).json()
    assert b["status"] == "valid" and b["sst"] is not None and b["anomaly"] is None and "climatology" in b["message"]


def test_point_validation(client, h, pacific):
    assert pt(client, h, 91, 0).status_code == 422
    assert pt(client, h, -91, 0).status_code == 422
    assert pt(client, h, 0, 400).status_code == 422
    assert pt(client, h, 0, -361).status_code == 422
    assert pt(client, h, "abc", 0).status_code == 422
    assert pt(client, h, 1, 201, layer="salinity").status_code == 422
    assert client.get("/api/environment/point", params={"dataset": "pacific", "lat": 0}, headers=h).status_code == 422


def test_point_dataset_and_date_selection(client, h, pacific):
    assert pt(client, h, 1, 201, date="2020-01-05").json()["date"] == "2020-01-05"
    early, late = pt(client, h, 1, 201, date="2020-01-05").json()["sst"], pt(client, h, 1, 201).json()["sst"]
    assert early == pytest.approx(expected(1, 201, 4)[2], abs=0.01) and early < late
    r = pt(client, h, 1, 201, date="2019-01-01")
    assert r.status_code == 404 and r.json()["detail"]["latest_available_date"] == P.LATEST
    assert client.get("/api/environment/point", params={"dataset": "mars", "lat": 0, "lon": 0}, headers=h).status_code == 404
    assert client.get("/api/environment/point", params={"dataset": "ne_pacific", "lat": 0, "lon": 0}, headers=h).status_code == 503


def test_point_provider_metadata(client, h, pacific):
    b = pt(client, h, 1, 201).json()
    assert b["provider"]["provider_id"] == "pacific_test_dataset" and b["provider"]["is_observational"] is False and b["kind"] == "generated"
    assert "noaa" not in str(b["provider"]).lower()


def test_point_query_reads_a_cell_not_the_field(client, h, pacific, monkeypatch):
    calls = []
    orig = es.EnvironmentalStore.native_layer
    monkeypatch.setattr(es.EnvironmentalStore, "native_layer", lambda *a, **k: calls.append(1) or orig(*a, **k))
    assert pt(client, h, 1, 201).json()["status"] == "valid"
    assert not calls


def test_existing_location_endpoint_unchanged(client, h, outputs):
    b = client.get("/api/monitor/location", params={"lat": 21.1, "lon": -158.1}, headers=h).json()
    assert "in_coverage" in b and "coverage" in b and "query" in b


def test_ne_pacific_point_regression_if_built(client, h):
    es.clear_cache()
    ref = es.dataset_refs()["ne_pacific"]
    if not (ref.path / "meta.json").exists():
        pytest.skip("processed/ NE Pacific dataset not present")
    b = client.get("/api/environment/point", params={"dataset": "ne_pacific", "lat": 35, "lon": -140}, headers=h).json()
    assert b["status"] == "valid" and b["kind"] == "observed" and b["sst"] is not None and b["cell"]["lon"] < -100
    same = client.get("/api/environment/point", params={"dataset": "ne_pacific", "lat": 35, "lon": 220}, headers=h).json()
    assert same["cell"] == b["cell"]                                                       # 0..360 input resolves identically
    assert client.get("/api/environment/point", params={"dataset": "ne_pacific", "lat": 0, "lon": 0}, headers=h).json()["status"] == "outside_dataset"


def test_real_pacific_points_if_built(client, h):
    es.clear_cache()
    if not (es.processed_pacific_dir() / "meta.json").exists():
        pytest.skip("processed_pacific/ not built")
    for lat, lon in [(0, 200), (-20, 175), (30, -140), (-30, 160), (35, 150)]:
        b = pt(client, h, lat, lon).json()
        assert b["status"] in ("valid", "land") and (b["sst"] is None) == (b["status"] == "land")
    assert pt(client, h, 0, 180).json()["cell"] == pt(client, h, 0, -180).json()["cell"]
