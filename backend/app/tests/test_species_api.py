"""Species catalogue API. The external OBIS/WoRMS calls are replaced by canned responses (the HTTP clients are unit
boundaries here; the live services are exercised by the sync job). Observations are real-shaped DB rows."""
from datetime import datetime, timezone

import pytest

from app.models.species import Species
from app.services import obis_client, species_service
from app.services.taxonomy import classify_group
from app.tests._helpers import auth_headers, make_biodiversity_observation, make_dataset, utc

HUMPBACK = {"id": 137092, "scientificName": "Megaptera novaeangliae", "rank": "Species", "taxonRank": "Species",
            "class": "Mammalia", "order": "Cetartiodactyla", "family": "Balaenopteridae", "acceptedNameUsageID": "137092"}
TURTLE = {"id": 137206, "scientificName": "Chelonia mydas", "rank": "Species", "taxonRank": "Species",
          "class": "Reptilia", "order": "Testudines", "family": "Cheloniidae", "acceptedNameUsageID": "137206"}


@pytest.fixture
def fake_obis(monkeypatch):
    taxa = {137092: HUMPBACK, 137206: TURTLE}
    monkeypatch.setattr(obis_client, "taxon", lambda aid: taxa.get(aid))
    monkeypatch.setattr(obis_client, "english_vernaculars", lambda aid: {137092: ["humpback whale"], 137206: ["green turtle"]}.get(aid, []))
    monkeypatch.setattr(obis_client, "gbif_common_name", lambda name: None)
    monkeypatch.setattr(obis_client, "gbif_iucn", lambda name: None)
    monkeypatch.setattr(obis_client, "redlist_category", lambda name: "EN" if name == "Chelonia mydas" else None)
    monkeypatch.setattr(obis_client, "taxon_complete", lambda q, limit=10: [t for t in taxa.values() if q.lower() in t["scientificName"].lower()])
    monkeypatch.setattr(obis_client, "occurrence_grid", lambda name, precision=3, geometry=None: {"type": "FeatureCollection", "features": []})
    return taxa


def _add(db, aphia):
    return species_service.upsert_species(db, aphia, watchlist=True)


def test_species_requires_auth(client):
    assert client.get("/api/species").status_code == 401
    assert client.get("/api/species/137092").status_code == 401
    assert client.post("/api/species", json={"aphia_id": 1}).status_code == 401


def test_taxonomy_grouping_rules():
    assert classify_group({"class": "Mammalia"}) == "Marine mammals"
    assert classify_group({"class": "Reptilia", "order": "Testudines"}) == "Sea turtles"
    assert classify_group({"class": None, "order": "Testudines"}) == "Sea turtles"  # as OBIS returns it
    assert classify_group({"class": "Hexacorallia", "order": "Scleractinia"}) == "Corals"
    assert classify_group({"class": "Reptilia", "order": "Squamata"}) == "Other marine organisms"  # sea snakes are not turtles
    assert classify_group({"class": "Elasmobranchii"}) == "Sharks & rays"
    assert classify_group({"class": "Teleostei"}) == "Fish"
    assert classify_group({"class": "Aves"}) == "Seabirds"
    assert classify_group({"class": "Anthozoa"}) == "Corals"
    assert classify_group({}) == "Other marine organisms"


def test_upsert_stores_only_what_the_sources_report(db_session, fake_obis):
    sp = _add(db_session, 137092)
    assert (sp.common_name, sp.taxon_group, sp.iucn_category) == ("humpback whale", "Marine mammals", None)
    assert sp.iucn_source is None  # no red-list entry => no conservation claim
    turtle = _add(db_session, 137206)
    assert turtle.iucn_category == "EN" and "OBIS" in turtle.iucn_source and turtle.taxon_group == "Sea turtles"
    again = _add(db_session, 137092)
    assert again.id == sp.id  # refresh, not duplicate


def test_list_search_filter_and_counts(client, db_session, fake_obis):
    _add(db_session, 137092)
    _add(db_session, 137206)
    ds = make_dataset(db_session)
    for _ in range(3):
        o = make_biodiversity_observation(db_session, ds)
        o.species_aphia_id, o.species_name = 137092, "Megaptera novaeangliae"
    db_session.commit()
    h = auth_headers(client)
    body = client.get("/api/species", headers=h).json()
    assert body["total"] == 2 and body["items"][0]["scientific_name"] == "Megaptera novaeangliae"  # most records first
    assert body["items"][0]["n_observations"] == 3 and body["groups"] == {"Marine mammals": 1, "Sea turtles": 1}
    assert [s["common_name"] for s in client.get("/api/species?q=green", headers=h).json()["items"]] == ["green turtle"]
    assert client.get("/api/species?group=Sea turtles", headers=h).json()["total"] == 1
    assert client.get("/api/species?threatened=true", headers=h).json()["items"][0]["iucn_label"] == "Endangered"
    assert client.get("/api/species?q=zzzz", headers=h).json() == {"items": [], "total": 0, "page": 1, "page_size": 24, "groups": {"Marine mammals": 1, "Sea turtles": 1},
                                                                       "statuses": {"UNCONFIRMED": 1, "EN": 1}}
    assert client.get("/api/species?group=Dragons", headers=h).status_code == 422
    assert client.get("/api/species?page=0", headers=h).status_code == 422


def test_detail_and_observations_with_geographic_filter(client, db_session, fake_obis):
    _add(db_session, 137092)
    ds = make_dataset(db_session)
    for lat, lon in ((10.0, 75.0), (40.0, -130.0)):
        o = make_biodiversity_observation(db_session, ds, lat=lat, lon=lon)
        o.species_aphia_id = 137092
    db_session.commit()
    h = auth_headers(client)
    d = client.get("/api/species/137092", headers=h).json()
    assert d["n_observations"] == 2 and d["sources"]["taxonomy"].endswith("/137092")
    allobs = client.get("/api/species/137092/observations", headers=h).json()
    assert allobs["total"] == 2 and allobs["source"].startswith("OBIS")
    box = client.get("/api/species/137092/observations?min_latitude=20&max_latitude=50&min_longitude=-160&max_longitude=-120", headers=h).json()
    assert box["total"] == 1 and box["items"][0]["latitude"] == 40.0
    assert client.get("/api/species/137092/observations?min_latitude=50&max_latitude=20", headers=h).status_code == 422
    assert client.get("/api/species/999/observations", headers=h).status_code == 404
    assert client.get("/api/species/999", headers=h).status_code == 404


def test_species_with_no_observations_says_so(client, db_session, fake_obis, outputs):
    _add(db_session, 137092)
    h = auth_headers(client)
    r = client.get("/api/species/137092/risk", headers=h).json()
    assert r["available"] is False and "No available observations" in r["message"] and r["score"] is None


def test_species_risk_with_records_returns_factors_and_labels(client, db_session, fake_obis, outputs):
    _add(db_session, 137092)
    ds = make_dataset(db_session)
    for k in range(5):
        o = make_biodiversity_observation(db_session, ds, ts=datetime.now(timezone.utc), lat=21.0 + 0.25 * k, lon=-158.0)
        o.species_aphia_id = 137092
    db_session.commit()
    r = client.get("/api/species/137092/risk", headers=auth_headers(client)).json()
    assert r["available"] and r["n_records"] == 5 and r["level"] in {"LOW", "MEDIUM", "HIGH", "CRITICAL"}
    assert len(r["factors"]) == 4 and r["reasons"]
    assert "potential exposure" in r["labels"]["score"] and "not proof of harm" in r["labels"]["score"]


def test_live_search_and_failure_is_a_clear_502(client, db_session, fake_obis, monkeypatch):
    h = auth_headers(client)
    hits = client.get("/api/species/search?q=chelonia", headers=h).json()
    assert hits[0]["aphia_id"] == 137206 and hits[0]["taxon_group"] == "Sea turtles" and hits[0]["in_catalogue"] is False
    assert client.get("/api/species/search?q=ab", headers=h).status_code == 422

    def boom(*a, **k):
        raise obis_client.ExternalServiceError("down")
    monkeypatch.setattr(obis_client, "taxon_complete", boom)
    assert client.get("/api/species/search?q=chelonia", headers=h).status_code == 502


def test_only_researchers_can_add_species(client, db_session, fake_obis):
    user = auth_headers(client, role="USER")
    assert client.post("/api/species", json={"aphia_id": 137092}, headers=user).status_code == 403
    researcher = auth_headers(client, role="RESEARCHER")
    created = client.post("/api/species", json={"aphia_id": 137092}, headers=researcher)
    assert created.status_code == 201 and created.json()["common_name"] == "humpback whale"
    assert client.post("/api/species", json={"aphia_id": 424242}, headers=researcher).status_code == 404  # unknown to OBIS
    assert client.post("/api/species", json={"aphia_id": -5}, headers=researcher).status_code == 422


def test_distribution_proxy(client, db_session, fake_obis, monkeypatch):
    _add(db_session, 137092)
    h = auth_headers(client)
    d = client.get("/api/species/137092/distribution", headers=h).json()
    assert d["geojson"]["type"] == "FeatureCollection" and "not a range map" in d["note"]
    assert client.get("/api/species/137092/distribution?precision=9", headers=h).status_code == 422


def test_gbif_common_name_is_the_most_frequent_english_name(monkeypatch):
    rows = [{"language": "eng", "vernacularName": n} for n in ("Killer Whale", "Blackfish", "killer whale", "Killer whale", "Orca")]
    rows.append({"language": "fra", "vernacularName": "Epaulard"})

    def fake_get(url, params=None, timeout=25.0):
        return {"usageKey": 1, "matchType": "EXACT"} if url.endswith("/match") else {"results": rows}
    monkeypatch.setattr(obis_client, "_get", fake_get)
    assert obis_client.gbif_common_name("Orcinus orca").lower() == "killer whale"
    monkeypatch.setattr(obis_client, "_get", lambda *a, **k: (_ for _ in ()).throw(obis_client.ExternalServiceError("down")))
    assert obis_client.gbif_common_name("Orcinus orca") is None  # failure => fall back to WoRMS, never an error


def test_gbif_name_is_preferred_over_worms_when_available(db_session, fake_obis, monkeypatch):
    monkeypatch.setattr(obis_client, "gbif_common_name", lambda name: "Humpback Whale")
    sp = _add(db_session, 137092)
    assert sp.common_name == "Humpback Whale" and "GBIF" in sp.sources["common_name"]


def test_gbif_iucn_category_is_preferred_and_labelled_with_its_source(db_session, fake_obis, monkeypatch):
    monkeypatch.setattr(obis_client, "gbif_iucn", lambda name: {"code": "LC", "category": "LEAST_CONCERN", "iucn_taxon_id": "13006"})
    sp = _add(db_session, 137092)
    assert sp.iucn_category == "LC" and "GBIF" in sp.iucn_source and "13006" in sp.iucn_source
    assert sp.sources["conservation"] == "https://www.iucnredlist.org/species/13006"
    # sources disagree: GBIF is shown, the OBIS value is kept visible in `sources`
    monkeypatch.setattr(obis_client, "gbif_iucn", lambda name: {"code": "LC", "category": "LEAST_CONCERN", "iucn_taxon_id": "4615"})
    turtle = _add(db_session, 137206)
    assert turtle.iucn_category == "LC" and turtle.sources["conservation_alt"] == {"source": "OBIS red-list checklist", "category": "EN"}
    assert sp.sources["conservation_alt"] is None  # humpback: OBIS has no entry, nothing to disagree with
    # the OBIS threatened-list entry is only a fallback when GBIF has no assessment
    monkeypatch.setattr(obis_client, "gbif_iucn", lambda name: None)
    refreshed = _add(db_session, 137206)
    assert refreshed.iucn_category == "EN" and refreshed.sources["conservation_alt"] is None


def test_status_filter_labels_and_unconfirmed_are_distinct(client, db_session, fake_obis, monkeypatch):
    monkeypatch.setattr(obis_client, "gbif_iucn", lambda name: {"code": "LC", "category": "LEAST_CONCERN", "iucn_taxon_id": "1"} if name == "Megaptera novaeangliae" else None)
    _add(db_session, 137092)
    _add(db_session, 137206)
    h = auth_headers(client)
    lc = client.get("/api/species?status=LC", headers=h).json()
    assert [x["scientific_name"] for x in lc["items"]] == ["Megaptera novaeangliae"] and lc["items"][0]["iucn_label"] == "Least Concern"
    assert client.get("/api/species?status=UNCONFIRMED", headers=h).json()["items"] == []  # the turtle has an OBIS EN entry
    assert client.get("/api/species?threatened=true", headers=h).json()["total"] == 1  # LC is not conservation-sensitive
    assert client.get("/api/species?status=XX", headers=h).status_code == 422


def test_taxonomy_search_matches_family(client, db_session, fake_obis):
    _add(db_session, 137092)
    assert client.get("/api/species?q=Balaenopteridae", headers=auth_headers(client)).json()["total"] == 1


def test_biodiversity_summary_counts_real_rows_only(client, db_session, fake_obis):
    h = auth_headers(client)
    empty = client.get("/api/species/summary", headers=h).json()
    assert empty["n_records"] == 0 and empty["latest_observation"] is None and empty["conservation_sensitive_with_records"] == 0
    _add(db_session, 137206)
    ds = make_dataset(db_session)
    o = make_biodiversity_observation(db_session, ds, ts=datetime.now(timezone.utc))
    o.species_aphia_id = 137206
    db_session.commit()
    s = client.get("/api/species/summary", headers=h).json()
    assert s["n_species"] == 1 and s["n_records"] == 1 and s["records_last_90_days"] == 1 and s["conservation_sensitive_with_records"] == 1
