"""Shared helpers for the Module 2-4 read API tests."""
import uuid
from datetime import datetime, timezone

from app.models import (
    Alert,
    AnomalyDetection,
    BiodiversityObservation,
    DataSource,
    Dataset,
    EcologicalRiskScore,
    OceanObservation,
    SSTForecast,
)
from app.models.enums import (
    AlertSeverity,
    AlertStatus,
    DatasetKind,
    DataSourceStatus,
    RiskLevel,
)


def auth_headers(client, role="USER", email=None):
    email = email or f"{role.lower()}-{uuid.uuid4().hex[:8]}@example.com"
    client.post(
        "/api/auth/register",
        json={"email": email, "full_name": "Test User", "password": "s3cure-pass", "role": role},
    )
    login = client.post("/api/auth/login", json={"email": email, "password": "s3cure-pass"})
    return {"Authorization": f"Bearer {login.json()['access_token']}"}


def utc(year, month, day, hour=0):
    return datetime(year, month, day, hour, tzinfo=timezone.utc)


def make_dataset(db, kind=DatasetKind.ENVIRONMENTAL):
    source = DataSource(
        name=f"src-{uuid.uuid4().hex[:6]}",
        provider="p",
        dataset="d",
        version="1",
        description="d",
        source_url="http://example.com",
        status=DataSourceStatus.ACTIVE,
    )
    db.add(source)
    db.flush()
    dataset = Dataset(data_source_id=source.id, name="ds", kind=kind, record_count=0)
    db.add(dataset)
    db.flush()
    return dataset


def make_ocean_observation(db, dataset, ts=None, lat=10.0, lon=75.0):
    obs = OceanObservation(
        dataset_id=dataset.id,
        timestamp=ts or utc(2026, 6, 1),
        latitude=lat,
        longitude=lon,
        sst=28.0,
        geometry=f"SRID=4326;POINT({lon} {lat})",
    )
    db.add(obs)
    db.flush()
    return obs


def make_biodiversity_observation(db, dataset, ts=None, lat=10.0, lon=75.0):
    obs = BiodiversityObservation(
        dataset_id=dataset.id,
        timestamp=ts or utc(2026, 6, 1),
        latitude=lat,
        longitude=lon,
        scientific_name="Thunnus albacares",
        geometry=f"SRID=4326;POINT({lon} {lat})",
    )
    db.add(obs)
    db.flush()
    return obs


def make_forecast(db, dataset, ts=None, lat=10.0, lon=75.0, horizon=7, sst=29.5):
    row = SSTForecast(
        dataset_id=dataset.id,
        timestamp=ts or utc(2026, 9, 1),
        latitude=lat,
        longitude=lon,
        predicted_sst=sst,
        forecast_horizon_days=horizon,
        model_version="test-v1",
    )
    db.add(row)
    db.commit()
    return row


def make_anomaly(db, observation, is_anomaly=True, score=0.9):
    row = AnomalyDetection(
        observation_id=observation.id,
        timestamp=observation.timestamp,
        latitude=observation.latitude,
        longitude=observation.longitude,
        anomaly_score=score,
        is_anomaly=is_anomaly,
        model_version="test-v1",
    )
    db.add(row)
    db.commit()
    return row


def make_risk(db, observation, level=RiskLevel.HIGH, score=0.6):
    row = EcologicalRiskScore(
        biodiversity_observation_id=observation.id,
        timestamp=observation.timestamp,
        latitude=observation.latitude,
        longitude=observation.longitude,
        risk_score=score,
        risk_level=level,
        contributing_factors={"thermal_stress": 0.8},
    )
    db.add(row)
    db.commit()
    return row


def make_alert(
    db,
    alert_type="SST_ANOMALY",
    severity=AlertSeverity.HIGH,
    status=AlertStatus.NEW,
    ts=None,
    **related,
):
    row = Alert(
        alert_type=alert_type,
        severity=severity,
        latitude=10.0,
        longitude=75.0,
        timestamp=ts or utc(2026, 6, 1),
        message="test alert",
        status=status,
        **related,
    )
    db.add(row)
    db.commit()
    return row
