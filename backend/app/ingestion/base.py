import uuid
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import date
from typing import ClassVar

import pandas as pd
from sqlalchemy.orm import Session

from app.models.enums import DatasetKind


@dataclass
class IngestionParams:
    """User-supplied bounds for a single ingestion run. Radius/time-window
    concerns belong to the alignment service, not ingestion.
    """

    start_date: date
    end_date: date
    min_latitude: float
    max_latitude: float
    min_longitude: float
    max_longitude: float

    def __post_init__(self) -> None:
        if self.start_date > self.end_date:
            raise ValueError("start_date must not be after end_date")
        if not (-90 <= self.min_latitude <= self.max_latitude <= 90):
            raise ValueError("latitude bounds must satisfy -90 <= min <= max <= 90")
        if not (-180 <= self.min_longitude <= self.max_longitude <= 180):
            raise ValueError("longitude bounds must satisfy -180 <= min <= max <= 180")


@dataclass
class QualityMetrics:
    """Mirrors DataQualityReport. Every rejected/modified record is accounted
    for in one of these buckets - nothing is silently discarded.
    """

    records_read: int = 0
    records_valid: int = 0
    records_rejected: int = 0
    records_modified: int = 0

    missing_values: int = 0
    duplicate_records: int = 0
    invalid_coordinates: int = 0
    invalid_timestamps: int = 0
    invalid_sst: int = 0
    outliers: int = 0
    schema_mismatches: int = 0

    details: dict = field(default_factory=dict)


class BaseIngestionAdapter(ABC):
    """Common interface every source adapter implements, so a new dataset can
    be added without touching the ingestion service or API layer.

    Pipeline: fetch (raw) -> validate (clean) -> transform (normalize +
    spatial/temporal processing) -> load (database).
    """

    data_source_name: ClassVar[str]
    dataset_kind: ClassVar[DatasetKind]

    @abstractmethod
    def fetch(self, params: IngestionParams) -> pd.DataFrame:
        """Pull raw records from the upstream source for the given bounds."""

    @abstractmethod
    def validate(self, raw_df: pd.DataFrame) -> tuple[pd.DataFrame, QualityMetrics]:
        """Run quality checks, drop invalid rows, and report exactly why."""

    @abstractmethod
    def transform(self, valid_df: pd.DataFrame) -> pd.DataFrame:
        """Normalize into the common data model's column names/types."""

    @abstractmethod
    def load(self, records_df: pd.DataFrame, dataset_id: uuid.UUID, db: Session) -> int:
        """Persist normalized records. Returns the number of rows written."""

    def run(
        self, params: IngestionParams, dataset_id: uuid.UUID, db: Session
    ) -> tuple[QualityMetrics, int]:
        raw_df = self.fetch(params)
        valid_df, metrics = self.validate(raw_df)
        normalized_df = self.transform(valid_df)
        records_loaded = self.load(normalized_df, dataset_id, db)
        return metrics, records_loaded
