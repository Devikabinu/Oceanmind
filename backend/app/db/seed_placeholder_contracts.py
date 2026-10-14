"""
############################################################################
#  GENERATING PLACEHOLDER DATA ONLY                                        #
#                                                                          #
#  Everything this script writes is FAKE. It exists so the backend API and #
#  frontend can be built and demoed before the Module 2/3/4 models are     #
#  ready. It is to be REPLACED by real model output later - see            #
#  CONTRACTS.md at the repo root.                                          #
#                                                                          #
#  Every row it creates is tagged model_version = PLACEHOLDER_MODEL_VERSION#
#  (alerts have no model_version; they are identified by being linked to   #
#  placeholder rows) so placeholder rows can be told apart from real ones. #
############################################################################

Populates, for Modules 2-4:
  sst_forecasts, anomaly_detections, ecological_risk_scores, alerts

Realism comes from Module 1's real data: lat/lon points, timestamps and SST
values are sampled from the rows actually present in `ocean_observations` and
`biodiversity_observations`. No region or date range is hardcoded; if Module 1
has not ingested anything yet the script stops with an explanation.

Usage (from backend/, with DATABASE_URL set as for the app / alembic):

    python -m app.db.seed_placeholder_contracts            # refuses if tables already have rows
    python -m app.db.seed_placeholder_contracts --reset    # deletes ONLY placeholder rows, then reseeds
"""
import argparse
import logging
import random
import statistics
import uuid
from datetime import timedelta

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from app.db.session import SessionLocal
from app.models import (
    Alert,
    AnomalyDetection,
    BiodiversityObservation,
    EcologicalRiskScore,
    OceanObservation,
    SSTForecast,
)
from app.models.dataset import Dataset
from app.models.enums import AlertSeverity, AlertStatus, DatasetKind, RiskLevel

logger = logging.getLogger("ocean_platform")

PLACEHOLDER_MODEL_VERSION = "placeholder-seed-v0"
ROWS_PER_TABLE = 400
RNG_SEED = 42  # deterministic so every teammate sees the same fake data

FORECAST_HORIZONS_DAYS = [1, 3, 7, 14]
ANOMALY_THRESHOLD = 0.7  # anomaly_score (0..1) at/above this => is_anomaly
HEAT_FORECAST_DELTA_C = 1.0  # forecast this far above the observed SST => raises an alert

SPECIES_SENSITIVITY_FACTORS = ["thermal_stress", "range_shift", "habitat_loss", "low_occurrence_density"]


def _risk_level(score: float) -> RiskLevel:
    if score < 0.25:
        return RiskLevel.LOW
    if score < 0.5:
        return RiskLevel.MEDIUM
    if score < 0.75:
        return RiskLevel.HIGH
    return RiskLevel.CRITICAL


def _severity_from_score(score: float) -> AlertSeverity:
    return AlertSeverity(_risk_level(score).value)


def _sample(db: Session, model, n: int, rng: random.Random):
    """Random sample of up to n rows, chosen in Python so the result is reproducible."""
    ids = list(db.scalars(select(model.id)))
    rng.shuffle(ids)
    chosen = ids[:n]
    return list(db.scalars(select(model).where(model.id.in_(chosen)))) if chosen else []


def _clear_placeholders(db: Session) -> None:
    # Alerts first (they reference the others). Alerts carry no model_version, so
    # remove any alert pointing at a placeholder row.
    fc = select(SSTForecast.id).where(SSTForecast.model_version == PLACEHOLDER_MODEL_VERSION)
    an = select(AnomalyDetection.id).where(AnomalyDetection.model_version == PLACEHOLDER_MODEL_VERSION)
    rk = select(EcologicalRiskScore.id).where(
        EcologicalRiskScore.contributing_factors["placeholder"].as_boolean().is_(True)
    )
    db.execute(
        delete(Alert).where(
            Alert.related_forecast_id.in_(fc)
            | Alert.related_anomaly_id.in_(an)
            | Alert.related_risk_id.in_(rk)
        )
    )
    db.execute(delete(EcologicalRiskScore).where(EcologicalRiskScore.id.in_(rk)))
    db.execute(delete(AnomalyDetection).where(AnomalyDetection.id.in_(an)))
    db.execute(delete(SSTForecast).where(SSTForecast.id.in_(fc)))
    db.commit()


def seed(db: Session, reset: bool = False) -> dict[str, int]:
    rng = random.Random(RNG_SEED)

    existing = {
        m.__tablename__: db.scalar(select(func.count()).select_from(m))
        for m in (SSTForecast, AnomalyDetection, EcologicalRiskScore, Alert)
    }
    if reset:
        _clear_placeholders(db)
        existing = {
            m.__tablename__: db.scalar(select(func.count()).select_from(m))
            for m in (SSTForecast, AnomalyDetection, EcologicalRiskScore, Alert)
        }
    if any(existing.values()):
        raise SystemExit(
            f"Tables are not empty ({existing}); not seeding on top of existing rows. "
            "Re-run with --reset to remove placeholder rows first."
        )

    n_ocean = db.scalar(select(func.count()).select_from(OceanObservation))
    n_bio = db.scalar(select(func.count()).select_from(BiodiversityObservation))
    if not n_ocean or not n_bio:
        raise SystemExit(
            "Module 1 has no data to base placeholders on "
            f"(ocean_observations={n_ocean}, biodiversity_observations={n_bio}). "
            "Run NOAA + OBIS ingestion first (POST /api/ingestion/noaa and /obis)."
        )

    # --- Real ranges from Module 1 (for the log, and the SST fallback) ---------
    lat_lo, lat_hi, lon_lo, lon_hi, t_lo, t_hi = db.execute(
        select(
            func.min(OceanObservation.latitude), func.max(OceanObservation.latitude),
            func.min(OceanObservation.longitude), func.max(OceanObservation.longitude),
            func.min(OceanObservation.timestamp), func.max(OceanObservation.timestamp),
        )
    ).one()
    mean_sst = db.scalar(select(func.avg(OceanObservation.sst))) or 15.0
    logger.info(
        "Module 1 ocean range: lat %.2f..%.2f lon %.2f..%.2f, %s .. %s, mean SST %.2f",
        lat_lo, lat_hi, lon_lo, lon_hi, t_lo, t_hi, mean_sst,
    )

    ocean_sample = _sample(db, OceanObservation, ROWS_PER_TABLE, rng)
    bio_sample = _sample(db, BiodiversityObservation, ROWS_PER_TABLE, rng)

    # --- Module 2: sst_forecasts ------------------------------------------------
    # Forecast for the grid points that were really observed, for dates AFTER the
    # ingested window; predicted_sst = observed SST + small seasonal drift + noise.
    env_dataset_ids = set(
        db.scalars(select(Dataset.id).where(Dataset.kind == DatasetKind.ENVIRONMENTAL))
    )
    forecasts: list[SSTForecast] = []
    for obs in ocean_sample:
        horizon = rng.choice(FORECAST_HORIZONS_DAYS)
        base = obs.sst if obs.sst is not None else mean_sst
        predicted = base + rng.gauss(0.2 * horizon ** 0.5, 0.35 + 0.05 * horizon)
        forecasts.append(
            SSTForecast(
                id=uuid.uuid4(),
                dataset_id=obs.dataset_id if obs.dataset_id in env_dataset_ids else next(iter(env_dataset_ids)),
                timestamp=t_hi + timedelta(days=horizon),
                latitude=obs.latitude,
                longitude=obs.longitude,
                predicted_sst=round(predicted, 3),
                forecast_horizon_days=horizon,
                model_version=PLACEHOLDER_MODEL_VERSION,
            )
        )
    forecast_base = {f.id: (o.sst if o.sst is not None else mean_sst) for f, o in zip(forecasts, ocean_sample)}

    # --- Module 3a: anomaly_detections -----------------------------------------
    # Score correlates with |sst_anomaly| when Module 1 has it, plus noise;
    # roughly 25-30% end up flagged.
    anomalies: list[AnomalyDetection] = []
    for obs in ocean_sample:
        signal = min(abs(obs.sst_anomaly) / 3.0, 1.0) if obs.sst_anomaly is not None else rng.random() * 0.5
        score = min(max(0.15 + 0.6 * signal + rng.gauss(0, 0.15) + (0.35 if rng.random() < 0.12 else 0), 0.0), 1.0)
        anomalies.append(
            AnomalyDetection(
                id=uuid.uuid4(),
                observation_id=obs.id,
                timestamp=obs.timestamp,
                latitude=obs.latitude,
                longitude=obs.longitude,
                anomaly_score=round(score, 4),
                is_anomaly=score >= ANOMALY_THRESHOLD,
                model_version=PLACEHOLDER_MODEL_VERSION,
            )
        )

    # --- Module 3b: ecological_risk_scores -------------------------------------
    sst_anoms = [o.sst_anomaly for o in ocean_sample if o.sst_anomaly is not None]
    anom_sd = statistics.pstdev(sst_anoms) if len(sst_anoms) > 1 else 1.0
    risks: list[EcologicalRiskScore] = []
    for bio in bio_sample:
        thermal = min(max(rng.gauss(0.4, 0.28), 0.0), 1.0)
        sensitivity = rng.random()
        density = rng.random()
        score = min(max(0.5 * thermal + 0.3 * sensitivity + 0.2 * (1 - density) + rng.gauss(0, 0.05), 0.0), 1.0)
        risks.append(
            EcologicalRiskScore(
                id=uuid.uuid4(),
                biodiversity_observation_id=bio.id,
                timestamp=bio.timestamp,
                latitude=bio.latitude,
                longitude=bio.longitude,
                risk_score=round(score, 4),
                risk_level=_risk_level(score),
                contributing_factors={
                    "placeholder": True,  # marker used by --reset; real Module 3 output should omit it
                    "species": bio.scientific_name,
                    "thermal_stress": round(thermal, 3),
                    "species_sensitivity": round(sensitivity, 3),
                    "occurrence_density": round(density, 3),
                    "sst_anomaly_stddev_c": round(anom_sd, 3),
                    "top_factor": rng.choice(SPECIES_SENSITIVITY_FACTORS),
                },
            )
        )

    db.add_all(forecasts)
    db.add_all(anomalies)
    db.add_all(risks)
    db.flush()  # alerts need these rows to exist for their FKs

    # --- Module 4: alerts ------------------------------------------------------
    alerts: list[Alert] = []
    for f in forecasts:
        delta = f.predicted_sst - forecast_base[f.id]
        if delta >= HEAT_FORECAST_DELTA_C:
            alerts.append(
                Alert(
                    alert_type="SST_FORECAST_HEAT",
                    severity=_severity_from_score(min(delta / 3.0, 1.0)),
                    latitude=f.latitude, longitude=f.longitude, timestamp=f.timestamp,
                    message=(
                        f"[PLACEHOLDER] Forecast SST of {f.predicted_sst:.1f}°C is {delta:.1f}°C above "
                        f"the latest observation, {f.forecast_horizon_days} day(s) ahead."
                    ),
                    related_forecast_id=f.id,
                )
            )
    for a in anomalies:
        if a.is_anomaly:
            alerts.append(
                Alert(
                    alert_type="SST_ANOMALY",
                    severity=_severity_from_score(a.anomaly_score),
                    latitude=a.latitude, longitude=a.longitude, timestamp=a.timestamp,
                    message=f"[PLACEHOLDER] Anomalous SST reading detected (score {a.anomaly_score:.2f}).",
                    related_anomaly_id=a.id,
                )
            )
    for r in risks:
        if r.risk_level in (RiskLevel.HIGH, RiskLevel.CRITICAL):
            alerts.append(
                Alert(
                    alert_type="ECOLOGICAL_RISK",
                    severity=AlertSeverity(r.risk_level.value),
                    latitude=r.latitude, longitude=r.longitude, timestamp=r.timestamp,
                    message=(
                        f"[PLACEHOLDER] {r.risk_level.value.title()} ecological risk for "
                        f"{r.contributing_factors['species']} (score {r.risk_score:.2f})."
                    ),
                    related_risk_id=r.id,
                )
            )
    for alert in alerts:
        alert.id = uuid.uuid4()
        alert.status = rng.choices(
            [AlertStatus.NEW, AlertStatus.ACKNOWLEDGED, AlertStatus.RESOLVED], weights=[55, 25, 20]
        )[0]
        if alert.status == AlertStatus.RESOLVED:
            alert.resolved_at = alert.timestamp + timedelta(hours=rng.randint(2, 96))
    db.add_all(alerts)
    db.commit()

    return {
        "sst_forecasts": len(forecasts),
        "anomaly_detections": len(anomalies),
        "ecological_risk_scores": len(risks),
        "alerts": len(alerts),
    }


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    parser = argparse.ArgumentParser(description="Seed PLACEHOLDER data for Modules 2-4.")
    parser.add_argument("--reset", action="store_true", help="delete existing placeholder rows first")
    args = parser.parse_args()
    with SessionLocal() as db:
        counts = seed(db, reset=args.reset)
    print("PLACEHOLDER data written:", counts)


if __name__ == "__main__":
    main()
