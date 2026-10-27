import uuid
from datetime import datetime

from pydantic import BaseModel, Field

from app.schemas.biodiversity_observation import BiodiversityObservationRead


class SpeciesRead(BaseModel):
    aphia_id: int
    scientific_name: str
    common_name: str | None
    taxon_group: str
    class_name: str | None
    order_name: str | None
    family: str | None
    iucn_category: str | None = Field(None, description="IUCN Red List category via OBIS (VU/EN/CR/EX); null = not listed as threatened by this source")
    iucn_label: str | None
    iucn_source: str | None
    watchlist: bool
    n_observations: int
    last_observation: datetime | None


class SpeciesDetail(SpeciesRead):
    first_observation: datetime | None = None
    sources: dict = {}
    last_synced_at: datetime | None = None


class PaginatedSpecies(BaseModel):
    items: list[SpeciesRead]
    total: int
    page: int
    page_size: int
    groups: dict[str, int]
    statuses: dict[str, int] = {}


class SpeciesObservations(BaseModel):
    items: list[BiodiversityObservationRead]
    total: int
    page: int
    page_size: int
    source: str = "OBIS (stored sample)"


class SpeciesSearchHit(BaseModel):
    aphia_id: int
    scientific_name: str
    rank: str | None = None
    taxon_group: str
    class_name: str | None = None
    family: str | None = None
    in_catalogue: bool


class TrackSpeciesRequest(BaseModel):
    aphia_id: int = Field(..., gt=0)


class RiskFactorRead(BaseModel):
    factor: str
    value: float | None
    level: str | None
    weight: float
    available: bool
    reason: str | None = None


class SpeciesRiskRead(BaseModel):
    available: bool
    aphia_id: int
    scientific_name: str
    n_records: int
    window_days: int
    methodology: str
    message: str | None = None
    score: float | None = None
    level: str | None = None
    factors: list[RiskFactorRead] = []
    reasons: list[str] = []
    n_cells: int | None = None
    exposed_share: float | None = None
    heatwave_share: float | None = None
    mean_anomaly_c: float | None = None
    thermal_range_c: dict | None = None
    max_anomaly_c: float | None = None
    observed_locations: int | None = None
    overlapping_locations: int | None = None
    exposure_pct_locations: float | None = None
    heatwave_locations: int | None = None
    heatwave_days_mean: float | None = None
    heatwave_days_max: int | None = None
    forecast_exposure: str | None = None
    forecast_mean_anomaly_c: float | None = None
    recent_records_90d: int | None = None
    latest_record: str | None = None
    dataset: str | None = None
    status: str | None = None
    evidence_completeness: float | None = None
    unavailable_factors: dict | None = None
    labels: dict = {
        "records": "OBSERVATION (OBIS)",
        "conditions": "OBSERVATION (NOAA OISST) + MODEL OUTPUT (ConvLSTM forecast)",
        "score": "DERIVED METRIC (project environmental risk indicator; potential exposure, not proof of harm)",
    }


class SpeciesId(BaseModel):
    id: uuid.UUID
