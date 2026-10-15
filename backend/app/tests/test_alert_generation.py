"""Explainable alert generation from the (synthetic) export; existing alert API semantics are untouched."""
from datetime import datetime, timezone

from sqlalchemy import select

from app.jobs import publish_outputs
from app.models.alert import Alert
from app.models.enums import AlertSeverity
from app.models.species import Species
from app.services.environment import env as load_env
from app.tests._helpers import auth_headers, make_biodiversity_observation, make_dataset


def test_alerts_are_generated_with_evidence_and_are_idempotent(db_session, outputs):
    e = load_env()
    first = publish_outputs.generate_alerts(db_session, e)
    assert first["MARINE_HEATWAVE"] == 1 and first["SST_ANOMALY"] >= 1 and first["SST_FORECAST_HEAT"] >= 1
    again = publish_outputs.generate_alerts(db_session, e)
    assert sum(again.values()) == 0  # same export -> no duplicates
    alerts = db_session.execute(select(Alert)).scalars().all()
    for a in alerts:
        d = a.details
        assert d["key"] and d["driver"] and d["reasons"] and d["data_sources"] and d["classification"] and d["recommendation"]
        assert a.status.value == "NEW"
    mhw = next(a for a in alerts if a.alert_type == "MARINE_HEATWAVE")
    assert mhw.severity == AlertSeverity.HIGH  # category II
    assert "project definition" in mhw.message and "not an official classification" in mhw.details["classification"]
    fc = next(a for a in alerts if a.alert_type == "SST_FORECAST_HEAT")
    assert "model output" in fc.message and fc.details["classification"] == "MODEL OUTPUT"


def test_species_alert_requires_enough_records_and_avoids_harm_claims(db_session, outputs):
    e = load_env()
    db_session.add(Species(aphia_id=777, scientific_name="Testus marinus", taxon_group="Fish", watchlist=True, sources={}))
    ds = make_dataset(db_session)
    for k in range(19):  # one short of the 20-record minimum
        o = make_biodiversity_observation(db_session, ds, ts=datetime.now(timezone.utc), lat=21.0 + 0.1 * (k % 5), lon=-158.5)
        o.species_aphia_id, o.species_name = 777, "Testus marinus"
    db_session.commit()
    assert publish_outputs.generate_alerts(db_session, e)["ECOLOGICAL_RISK"] == 0
    o = make_biodiversity_observation(db_session, ds, ts=datetime.now(timezone.utc), lat=21.0, lon=-158.5)
    o.species_aphia_id, o.species_name = 777, "Testus marinus"
    db_session.commit()
    made = publish_outputs.generate_alerts(db_session, e)
    assert made["ECOLOGICAL_RISK"] == 1
    a = db_session.execute(select(Alert).where(Alert.alert_type == "ECOLOGICAL_RISK")).scalar_one()
    assert "potential environmental exposure" in a.message.lower()
    assert "not evidence of harm" in a.details["classification"] and "not a conservation assessment" in a.details["recommendation"]


def test_alert_api_exposes_details_and_status_workflow_still_works(client, db_session, outputs):
    publish_outputs.generate_alerts(db_session, load_env())
    h = auth_headers(client, role="RESEARCHER")
    listed = client.get("/api/alerts?alert_type=MARINE_HEATWAVE", headers=h).json()
    assert listed["total"] == 1 and listed["items"][0]["details"]["reasons"]
    aid = listed["items"][0]["id"]
    assert client.patch(f"/api/alerts/{aid}", json={"status": "ACKNOWLEDGED"}, headers=h).json()["status"] == "ACKNOWLEDGED"
    assert client.patch(f"/api/alerts/{aid}", json={"status": "RESOLVED"}, headers=h).json()["resolved_at"] is not None
    assert client.patch(f"/api/alerts/{aid}", json={"status": "NEW"}, headers=h).status_code == 409  # still forward-only
    assert client.patch(f"/api/alerts/{aid}", json={"status": "ACKNOWLEDGED"}, headers=auth_headers(client, role="USER")).status_code == 403


def test_heatwave_alert_evidence_counts_conservation_sensitive_species(db_session, outputs):
    from datetime import datetime, timezone
    db_session.add(Species(aphia_id=1, scientific_name="Aus bus", taxon_group="Fish", iucn_category="EN", sources={}))
    db_session.add(Species(aphia_id=2, scientific_name="Cus dus", taxon_group="Fish", iucn_category="LC", sources={}))
    ds = make_dataset(db_session)
    for aid, name in ((1, "Aus bus"), (2, "Cus dus")):  # inside the event bbox (lat 20-22, lon -159.5..-158)
        o = make_biodiversity_observation(db_session, ds, ts=datetime.now(timezone.utc), lat=21.0, lon=-159.0)
        o.species_aphia_id, o.species_name = aid, name
    db_session.commit()
    publish_outputs.generate_alerts(db_session, load_env())
    a = db_session.execute(select(Alert).where(Alert.alert_type == "MARINE_HEATWAVE")).scalar_one()
    ev = {row["label"]: row["value"] for row in a.details["evidence_summary"]}
    assert ev["Biodiversity overlap"].startswith("2 species") and ev["Conservation-sensitive species"] == "1"
    assert ev["Maximum anomaly"] == "+4.5 °C" and ev["Duration"].startswith("11 days")
    assert any("1 conservation-sensitive" in r for r in a.details["reasons"])
    assert {s["scientific_name"] for s in a.details["species"]} == {"Aus bus", "Cus dus"}


def test_regenerating_refreshes_evidence_but_keeps_workflow_status(db_session, outputs):
    from app.models.enums import AlertStatus
    e = load_env()
    publish_outputs.generate_alerts(db_session, e)
    a = db_session.execute(select(Alert).where(Alert.alert_type == "MARINE_HEATWAVE")).scalar_one()
    a.status = AlertStatus.ACKNOWLEDGED
    a.details = {**a.details, "reasons": ["stale text"]}
    db_session.commit()
    again = publish_outputs.generate_alerts(db_session, e)
    assert sum(v for k, v in again.items() if k != "REFRESHED") == 0 and again["REFRESHED"] >= 1
    db_session.refresh(a)
    assert a.status.value == "ACKNOWLEDGED" and "stale text" not in a.details["reasons"]


def test_small_heatwave_is_alerted_only_when_it_overlaps_conservation_sensitive_species(db_session, outputs):
    import json
    from datetime import datetime, timezone
    from app.services import environment
    path = outputs / "model" / "dashboard" / "heatwave.json"
    info = json.loads(path.read_text())
    info["events"][0].update(area_km2=20000.0, category=1, category_name="I (Moderate)")
    path.write_text(json.dumps(info))
    environment.clear_cache()
    e = load_env()
    assert publish_outputs.generate_alerts(db_session, e)["MARINE_HEATWAVE"] == 0  # small + mild + no species: no alert
    db_session.add(Species(aphia_id=5, scientific_name="Vul nerabilis", taxon_group="Fish", iucn_category="VU", sources={}))
    ds = make_dataset(db_session)
    o = make_biodiversity_observation(db_session, ds, ts=datetime.now(timezone.utc), lat=21.0, lon=-159.0)
    o.species_aphia_id, o.species_name = 5, "Vul nerabilis"
    db_session.commit()
    assert publish_outputs.generate_alerts(db_session, e)["MARINE_HEATWAVE"] == 1
    a = db_session.execute(select(Alert).where(Alert.alert_type == "MARINE_HEATWAVE")).scalar_one()
    assert a.severity == AlertSeverity.MEDIUM and a.details["evidence_summary"][-1] == {"label": "Conservation-sensitive species", "value": "1"}
