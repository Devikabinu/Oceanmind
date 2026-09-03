import uuid

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.models.environment_biodiversity_match import EnvironmentBiodiversityMatch
from app.repositories.match_repository import MatchRepository

# For each biodiversity observation, find the single nearest ocean observation
# that is within `spatial_radius_km` (great-circle distance, via a geography
# cast) AND within `temporal_window_hours` of it. Implemented as one
# CROSS JOIN LATERAL query rather than N+1 Python-side lookups - this is the
# standard PostGIS pattern for a per-row nearest-neighbor join and lets
# Postgres do the spatial filtering directly against the GIST index.
_MATCH_QUERY = text(
    """
    SELECT
        bio.id AS biodiversity_observation_id,
        matched.ocean_observation_id,
        matched.distance_km,
        matched.time_diff_hours,
        matched.sst,
        matched.sst_anomaly
    FROM biodiversity_observations bio
    CROSS JOIN LATERAL (
        SELECT
            oo.id AS ocean_observation_id,
            oo.sst,
            oo.sst_anomaly,
            ST_Distance(bio.geometry::geography, oo.geometry::geography) / 1000.0 AS distance_km,
            ABS(EXTRACT(EPOCH FROM (bio.timestamp - oo.timestamp))) / 3600.0 AS time_diff_hours
        FROM ocean_observations oo
        WHERE ST_DWithin(bio.geometry::geography, oo.geometry::geography, :radius_m)
          AND ABS(EXTRACT(EPOCH FROM (bio.timestamp - oo.timestamp))) <= :window_seconds
        ORDER BY ST_Distance(bio.geometry::geography, oo.geometry::geography) ASC
        LIMIT 1
    ) AS matched
    WHERE (:bio_dataset_id IS NULL OR bio.dataset_id = :bio_dataset_id)
    """
)


class AlignmentService:
    def __init__(self, db: Session):
        self.db = db

    def run(
        self,
        spatial_radius_km: float,
        temporal_window_hours: float,
        biodiversity_dataset_id: uuid.UUID | None = None,
    ) -> int:
        rows = self.db.execute(
            _MATCH_QUERY,
            {
                "radius_m": spatial_radius_km * 1000,
                "window_seconds": temporal_window_hours * 3600,
                "bio_dataset_id": biodiversity_dataset_id,
            },
        ).mappings()

        matches = [
            EnvironmentBiodiversityMatch(
                biodiversity_observation_id=row["biodiversity_observation_id"],
                ocean_observation_id=row["ocean_observation_id"],
                distance_km=row["distance_km"],
                time_difference_hours=row["time_diff_hours"],
                matched_sst=row["sst"],
                matched_sst_anomaly=row["sst_anomaly"],
                spatial_radius_km=spatial_radius_km,
                temporal_window_hours=temporal_window_hours,
            )
            for row in rows
        ]
        return MatchRepository(self.db).bulk_create(matches)
