import logging
import uuid

import copernicusmarine
import pandas as pd
from sqlalchemy import insert
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.ingestion import quality
from app.ingestion.base import BaseIngestionAdapter, IngestionParams, QualityMetrics
from app.models.enums import DatasetKind
from app.models.ocean_observation import OceanObservation

logger = logging.getLogger("ocean_platform")

# Product SST_GLO_PHY_L4_NRT_010_005 - "Global Ocean GMPE Sea Surface
# Temperature Multi Product Ensemble" (Met Office, GHRSST), 0.25deg daily.
# Variable names verified via `copernicusmarine describe --contains GMPE`
# against the live public catalog.
_SOURCE_VARIABLES = {
    "sst": "analysed_sst",  # kelvin, absolute -> converted to Celsius
    "sst_anomaly": "anomaly_fields",  # kelvin delta == celsius delta, no offset
    "measurement_error": "standard_deviation",  # kelvin delta == celsius delta
}
_REQUIRED_RAW_COLUMNS = ["time", "latitude", "longitude", "sst"]


class CopernicusCredentialsMissingError(Exception):
    pass


class CopernicusAdapter(BaseIngestionAdapter):
    """Copernicus Marine Global Ocean GMPE SST Multi Product Ensemble
    (dataset cmems_obs-sst_glo_phy-temp_nrt_P1D-m), used as a secondary SST
    source for cross-validation against NOAA OISST. Requires a free account:
    https://data.marine.copernicus.eu/register
    """

    data_source_name = "Copernicus Marine SST"
    dataset_kind = DatasetKind.ENVIRONMENTAL

    def __init__(self) -> None:
        self.settings = get_settings()

    def fetch(self, params: IngestionParams) -> pd.DataFrame:
        if not self.settings.COPERNICUS_MARINE_USERNAME or not self.settings.COPERNICUS_MARINE_PASSWORD:
            raise CopernicusCredentialsMissingError(
                "COPERNICUS_MARINE_USERNAME / COPERNICUS_MARINE_PASSWORD are not set. "
                "Register a free account at https://data.marine.copernicus.eu/register "
                "and set both in .env before running Copernicus ingestion."
            )

        ds = copernicusmarine.open_dataset(
            dataset_id=self.settings.COPERNICUS_MARINE_DATASET_ID,
            username=self.settings.COPERNICUS_MARINE_USERNAME,
            password=self.settings.COPERNICUS_MARINE_PASSWORD,
            variables=list(_SOURCE_VARIABLES.values()),
            minimum_longitude=params.min_longitude,
            maximum_longitude=params.max_longitude,
            minimum_latitude=params.min_latitude,
            maximum_latitude=params.max_latitude,
            start_datetime=str(params.start_date),
            end_datetime=str(params.end_date),
        )

        rename_map = {source: target for target, source in _SOURCE_VARIABLES.items()}
        ds = ds.rename(rename_map)
        raw_df = ds.to_dataframe().reset_index()
        return raw_df

    def validate(self, raw_df: pd.DataFrame) -> tuple[pd.DataFrame, QualityMetrics]:
        metrics = QualityMetrics(records_read=len(raw_df))
        metrics.schema_mismatches = quality.check_schema(raw_df, _REQUIRED_RAW_COLUMNS)

        if raw_df.empty:
            return raw_df, metrics

        # Kelvin -> Celsius for the absolute SST field before range-checking
        # it against the physically-plausible-range check (which is in Celsius).
        raw_df = raw_df.copy()
        raw_df["sst"] = raw_df["sst"] - 273.15

        missing_valid, metrics.missing_values = quality.flag_missing(
            raw_df, ["time", "latitude", "longitude", "sst"]
        )
        dup_valid, metrics.duplicate_records = quality.flag_duplicates(
            raw_df, ["time", "latitude", "longitude"]
        )
        coord_valid, metrics.invalid_coordinates = quality.flag_invalid_coordinates(
            raw_df, "latitude", "longitude"
        )
        time_valid, metrics.invalid_timestamps = quality.flag_invalid_timestamps(raw_df, "time")
        sst_valid, metrics.invalid_sst = quality.flag_invalid_sst(raw_df, "sst")
        _, metrics.outliers = quality.flag_outliers(raw_df, "sst")

        keep = missing_valid & dup_valid & coord_valid & time_valid & sst_valid
        valid_df = raw_df.loc[keep].copy()

        metrics.records_valid = len(valid_df)
        metrics.records_rejected = metrics.records_read - metrics.records_valid
        metrics.records_modified = metrics.records_valid
        metrics.details = {
            "unit_conversion": "sst converted from kelvin (source) to celsius",
            "outlier_check": "z-score > 4.0 on sst, flagged only (not rejected)",
        }
        return valid_df, metrics

    def transform(self, valid_df: pd.DataFrame) -> pd.DataFrame:
        if valid_df.empty:
            return pd.DataFrame(
                columns=[
                    "timestamp",
                    "latitude",
                    "longitude",
                    "sst",
                    "sst_anomaly",
                    "measurement_error",
                    "source_record_id",
                ]
            )

        out = pd.DataFrame(
            {
                "timestamp": pd.to_datetime(valid_df["time"], utc=True),
                "latitude": valid_df["latitude"].astype(float),
                "longitude": valid_df["longitude"].astype(float),
                "sst": valid_df["sst"].astype(float),
                "sst_anomaly": valid_df.get("sst_anomaly"),
                "measurement_error": valid_df.get("measurement_error"),
                "source_record_id": (
                    valid_df["time"].astype(str)
                    + "_"
                    + valid_df["latitude"].round(3).astype(str)
                    + "_"
                    + valid_df["longitude"].round(3).astype(str)
                ),
            }
        )
        return out

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
                    "sst": record.sst,
                    "sst_anomaly": None if pd.isna(record.sst_anomaly) else record.sst_anomaly,
                    "measurement_error": (
                        None if pd.isna(record.measurement_error) else record.measurement_error
                    ),
                    "ice_concentration": None,
                    "source_record_id": record.source_record_id,
                    "geometry": f"SRID=4326;POINT({record.longitude} {record.latitude})",
                }
            )

        db.execute(insert(OceanObservation), rows)
        db.commit()
        return len(rows)
