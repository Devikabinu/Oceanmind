import logging
import uuid

import pandas as pd
import requests
from sqlalchemy import insert
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.ingestion import quality
from app.ingestion.base import BaseIngestionAdapter, IngestionParams, QualityMetrics
from app.models.biodiversity_observation import BiodiversityObservation
from app.models.enums import DatasetKind

logger = logging.getLogger("ocean_platform")

_FIELDS = [
    "id",
    "decimalLatitude",
    "decimalLongitude",
    "eventDate",
    "date_year",
    "scientificName",
    "occurrenceStatus",
    "minimumDepthInMeters",
    "maximumDepthInMeters",
    "flags",
    "species",
    "speciesid",
    "class",
]
_REQUIRED_RAW_COLUMNS = ["decimalLatitude", "decimalLongitude", "eventDate", "scientificName"]

# Hard cap per ingestion run: OBIS holds hundreds of millions of records
# globally, and this platform intentionally ingests geographic/temporal
# subsets, not the full database.
_MAX_RECORDS_PER_RUN = 10_000
_PAGE_SIZE = 500


def _bbox_to_wkt_polygon(params: IngestionParams) -> str:
    min_lon, max_lon = params.min_longitude, params.max_longitude
    min_lat, max_lat = params.min_latitude, params.max_latitude
    return (
        f"POLYGON(({min_lon} {min_lat},{max_lon} {min_lat},"
        f"{max_lon} {max_lat},{min_lon} {max_lat},{min_lon} {min_lat}))"
    )


class OBISAdapter(BaseIngestionAdapter):
    """Ocean Biodiversity Information System - public REST API v3, no key
    required. https://api.obis.org
    """

    data_source_name = "OBIS"
    dataset_kind = DatasetKind.BIODIVERSITY

    def __init__(self) -> None:
        self.settings = get_settings()

    def fetch(self, params: IngestionParams) -> pd.DataFrame:
        base_url = f"{self.settings.OBIS_API_BASE_URL}/occurrence"
        cap = min(params.max_records or _MAX_RECORDS_PER_RUN, _MAX_RECORDS_PER_RUN)
        page_size = min(_PAGE_SIZE, cap)
        query = {
            "geometry": _bbox_to_wkt_polygon(params),
            "startdate": params.start_date.isoformat(),
            "enddate": params.end_date.isoformat(),
            "size": page_size,
        }
        if params.scientific_name:
            query["scientificname"] = params.scientific_name

        records: list[dict] = []
        after: str | None = None
        while len(records) < cap:
            page_query = dict(query)
            if after is not None:
                page_query["after"] = after

            response = requests.get(base_url, params=page_query, timeout=30)
            response.raise_for_status()
            payload = response.json()
            results = payload.get("results", [])
            if not results:
                break

            for result in results:
                records.append({field: result.get(field) for field in _FIELDS})

            if len(results) < page_size:
                break
            after = results[-1]["id"]

        return pd.DataFrame(records[:cap])

    def validate(self, raw_df: pd.DataFrame) -> tuple[pd.DataFrame, QualityMetrics]:
        metrics = QualityMetrics(records_read=len(raw_df))
        metrics.schema_mismatches = quality.check_schema(raw_df, _REQUIRED_RAW_COLUMNS)

        if raw_df.empty:
            return raw_df, metrics

        missing_valid, metrics.missing_values = quality.flag_missing(
            raw_df, _REQUIRED_RAW_COLUMNS
        )
        dup_valid, metrics.duplicate_records = quality.flag_duplicates(raw_df, ["id"])
        coord_valid, coord_count = quality.flag_invalid_coordinates(
            raw_df, "decimalLatitude", "decimalLongitude"
        )
        # OBIS runs its own QC and flags points that fall on land - treat that
        # as an additional coordinate-validity signal specific to this source.
        on_land = raw_df["flags"].apply(lambda f: isinstance(f, list) and "ON_LAND" in f)
        coord_valid = coord_valid & ~on_land
        metrics.invalid_coordinates = coord_count + int(on_land.sum())

        time_valid, metrics.invalid_timestamps = quality.flag_invalid_timestamps(
            raw_df, "eventDate"
        )
        _, metrics.outliers = quality.flag_outliers(raw_df, "minimumDepthInMeters")

        keep = missing_valid & dup_valid & coord_valid & time_valid
        valid_df = raw_df.loc[keep].copy()

        metrics.records_valid = len(valid_df)
        metrics.records_rejected = metrics.records_read - metrics.records_valid
        metrics.records_modified = 0
        metrics.details = {
            "on_land_flagged_by_obis": int(on_land.sum()),
            "outlier_check": "z-score > 4.0 on minimumDepthInMeters, flagged only (not rejected)",
        }
        return valid_df, metrics

    def transform(self, valid_df: pd.DataFrame) -> pd.DataFrame:
        if valid_df.empty:
            return pd.DataFrame(
                columns=[
                    "timestamp",
                    "latitude",
                    "longitude",
                    "scientific_name",
                    "occurrence_status",
                    "min_depth",
                    "max_depth",
                    "source_record_id",
                    "species_name",
                    "species_aphia_id",
                    "taxon_class",
                ]
            )

        out = pd.DataFrame(
            {
                "timestamp": pd.to_datetime(valid_df["eventDate"], utc=True, errors="coerce"),
                "latitude": valid_df["decimalLatitude"].astype(float),
                "longitude": valid_df["decimalLongitude"].astype(float),
                "scientific_name": valid_df["scientificName"],
                # Some providers put long values (e.g. taxon LSID lists) here; column is varchar(50).
                "occurrence_status": valid_df["occurrenceStatus"].astype("string").str.slice(0, 50),
                "min_depth": pd.to_numeric(valid_df["minimumDepthInMeters"], errors="coerce"),
                "max_depth": pd.to_numeric(valid_df["maximumDepthInMeters"], errors="coerce"),
                "source_record_id": valid_df["id"],
                "species_name": valid_df["species"],
                "species_aphia_id": pd.to_numeric(valid_df["speciesid"], errors="coerce"),
                "taxon_class": valid_df["class"],
            }
        )
        # A handful of eventDate values are year-only or otherwise unparsable
        # even after passing the raw string-presence check; drop those rather
        # than writing a null timestamp into a NOT NULL column.
        return out.dropna(subset=["timestamp"])

    def load(self, records_df: pd.DataFrame, dataset_id: uuid.UUID, db: Session) -> int:
        if records_df.empty:
            return 0

        rows = []
        for record in records_df.itertuples(index=False):
            rows.append(
                {
                    "id": uuid.uuid4(),
                    "dataset_id": dataset_id,
                    "timestamp": record.timestamp,
                    "latitude": record.latitude,
                    "longitude": record.longitude,
                    "scientific_name": record.scientific_name,
                    "occurrence_status": record.occurrence_status,
                    "min_depth": None if pd.isna(record.min_depth) else record.min_depth,
                    "max_depth": None if pd.isna(record.max_depth) else record.max_depth,
                    "source_record_id": record.source_record_id,
                    "species_name": None if pd.isna(record.species_name) else record.species_name,
                    "species_aphia_id": None if pd.isna(record.species_aphia_id) else int(record.species_aphia_id),
                    "taxon_class": None if pd.isna(record.taxon_class) else record.taxon_class,
                    "geometry": f"SRID=4326;POINT({record.longitude} {record.latitude})",
                }
            )

        db.execute(insert(BiodiversityObservation), rows)
        db.commit()
        return len(rows)
