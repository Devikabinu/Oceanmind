"""The boundary between the application and wherever environmental data come from.

Everything downstream (preprocessing, anomalies, heatwaves, risk, alerts, API) should depend on `EnvironmentalDataProvider` only. A temporary generated
provider and a future real Pacific provider implement the same interface, so swapping them is a configuration change.

Conventions (matching the project's xarray pipeline in oceanmind_preprocess):
  * datasets have dims (time, lat, lon); lat ascending; time = daily UTC midnight
  * values are float32 degrees Celsius; NaN marks land / invalid cells
  * longitudes are **east longitude 0..360**, because the Pacific crosses the antimeridian and this keeps the grid contiguous. `lon_convention="180"` returns the
    -180..180 convention (re-ordered, so the longitude axis then has a gap where the domain does not cover the Atlantic/Indian side).
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import asdict, dataclass, field

import numpy as np
import pandas as pd
import xarray as xr


class DateNotAvailable(ValueError):
    """The requested date lies outside the provider's temporal coverage."""


@dataclass(frozen=True)
class ProviderMetadata:
    provider_id: str
    provider_type: str                 # "generated_temporary" | "observational" | ...
    is_observational: bool             # False for generated data: values are NOT measurements
    description: str
    dataset_type: str
    variables: dict                    # name -> {"units": ..., "long_name": ...}
    units: str
    extent: dict                       # lat_min, lat_max, lon_min, lon_max (cell edges)
    coordinate_system: str
    lon_convention: str
    resolution_deg: float
    temporal_resolution: str
    temporal_coverage: dict            # start, end, n_timestamps
    latest_timestamp: str
    grid_shape: tuple                  # (n_lat, n_lon)
    total_cells: int
    valid_cells: int
    mask_source: str
    seed: int | None = None
    generator_version: str | None = None
    notes: list = field(default_factory=list)
    source: dict | None = None         # provider, dataset, URLs, citation, update frequency (observational providers)

    def to_dict(self) -> dict:
        return asdict(self)


class EnvironmentalDataProvider(ABC):
    """Source of gridded environmental fields on a fixed lat/lon grid."""

    @abstractmethod
    def metadata(self) -> ProviderMetadata: ...

    @abstractmethod
    def grid(self) -> tuple[np.ndarray, np.ndarray]:
        """(lat, lon) 1-D cell-centre coordinates; lat ascending, lon east 0..360 and contiguous."""

    @abstractmethod
    def ocean_mask(self) -> np.ndarray:
        """bool (n_lat, n_lon), True where the cell is valid ocean for this provider."""

    @abstractmethod
    def available_dates(self) -> pd.DatetimeIndex: ...

    @abstractmethod
    def get_dataset(self, start=None, end=None, variables=("sst",), lon_convention: str = "360") -> xr.Dataset:
        """Variables on (time, lat, lon). With start and end both None, the latest available day is returned."""

    # --- conveniences shared by every provider ---------------------------------------------------------------------------------
    def latest_timestamp(self) -> pd.Timestamp:
        return self.available_dates()[-1]

    def get_sst(self, date=None) -> xr.DataArray:
        """SST on one day (default: latest) as a (lat, lon) DataArray."""
        day = self.latest_timestamp() if date is None else pd.Timestamp(date)
        return self.get_dataset(day, day, ("sst",))["sst"].isel(time=0, drop=True)

    def sst_series(self, start, end) -> xr.DataArray:
        return self.get_dataset(start, end, ("sst",))["sst"]
