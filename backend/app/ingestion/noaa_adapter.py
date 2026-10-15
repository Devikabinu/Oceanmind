import logging
import os
import time
import uuid

import pandas as pd
import xarray as xr
from sqlalchemy import insert
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.ingestion import quality
from app.ingestion.base import BaseIngestionAdapter, IngestionParams, QualityMetrics
from app.models.enums import DatasetKind
from app.models.ocean_observation import OceanObservation

logger = logging.getLogger("ocean_platform")

# NOAA PSL publishes OISST v2.1 as one NetCDF file per variable per year.
_VARIABLE_FILES = {
    "sst": "sst.day.mean.{year}.nc",
    "sst_anomaly": "sst.day.anom.{year}.nc",
    "measurement_error": "sst.day.err.{year}.nc",
    "ice_concentration": "icec.day.mean.{year}.nc",
}
_SOURCE_VARIABLE_NAMES = {
    "sst": "sst",
    "sst_anomaly": "anom",
    "measurement_error": "err",
    "ice_concentration": "icec",
}

_REQUIRED_RAW_COLUMNS = ["time", "lat", "lon", "sst"]


def _to_0_360(lon: float) -> float:
    return lon % 360


def _work_around_netcdf_ca_path_with_spaces() -> None:
    """netCDF4 points netcdf-c's HTTP.SSL.CAINFO at certifi's bundle, but netcdf-c mangles paths that contain
    a space (e.g. a Windows user profile or venv under a "First Last" user folder), so every https OPeNDAP open
    fails with "NetCDF: I/O failure". Re-point it at the space-free 8.3 short path of the same file."""
    if os.name != "nt":
        return
    try:
        import certifi
        import ctypes
        import netCDF4

        path = certifi.where()
        if " " not in path or not hasattr(netCDF4, "rc_set"):
            return
        buf = ctypes.create_unicode_buffer(1024)
        if ctypes.windll.kernel32.GetShortPathNameW(path, buf, 1024) and " " not in buf.value:
            netCDF4.rc_set("HTTP.SSL.CAINFO", buf.value)
    except Exception:  # best effort: never block ingestion on this shim
        logger.debug("could not adjust netCDF CA bundle path", exc_info=True)


_work_around_netcdf_ca_path_with_spaces()


def _decode_time_coord(ds: xr.Dataset) -> xr.Dataset:
    """Manually decode the CF 'days since <reference>' time units via pandas.

    xarray's built-in decode_times=True (via cftime) reliably segfaults with
    this environment's numpy/cftime build when opening this dataset over
    OPeNDAP - reproduced with a minimal `xr.open_dataset(url)` call outside
    any application code. NOAA OISST uses the standard/proleptic-gregorian
    calendar, which pandas can decode directly with no native-code risk, so
    time is decoded here instead of relying on xarray/cftime for it.
    """
    units = ds["time"].attrs["units"]  # e.g. "days since 1800-01-01 00:00:00"
    reference = pd.Timestamp(units.split("since", 1)[1].strip())
    decoded = reference + pd.to_timedelta(ds["time"].values, unit="D")
    return ds.assign_coords(time=("time", decoded))


class NOAAAdapter(BaseIngestionAdapter):
    """NOAA OISST v2.1 - 0.25deg daily gridded SST, served over OPeNDAP by
    NOAA PSL. No API key required. https://psl.noaa.gov/data/gridded/data.noaa.oisst.v2.highres.html
    """

    data_source_name = "NOAA OISST v2.1"
    dataset_kind = DatasetKind.ENVIRONMENTAL

    def __init__(self) -> None:
        self.settings = get_settings()

    @staticmethod
    def _open_with_retry(url: str, attempts: int = 5, base_delay: float = 6.0) -> xr.Dataset | None:
        """NOAA PSL rate-limits bursts of OPeNDAP opens (HTTP 429 -> netCDF "Access failure"), so back off and retry
        before treating a file as unavailable."""
        for attempt in range(1, attempts + 1):
            try:
                ds = xr.open_dataset(url, decode_times=False)
                if "units" not in ds["time"].attrs:  # degraded OPeNDAP response under load: metadata missing
                    ds.close()
                    raise OSError("incomplete metadata in NOAA response (time units missing)")
                return ds
            except (OSError, KeyError) as exc:
                if attempt == attempts:
                    logger.warning("NOAA source file unavailable, skipping: %s (%s)", url, exc)
                    return None
                logger.info("NOAA open failed (attempt %d/%d), retrying: %s (%s)", attempt, attempts, url, exc)
                time.sleep(base_delay * attempt)
        return None

    def _open_year(self, year: int, params: IngestionParams) -> xr.Dataset | None:
        lon_min_360 = _to_0_360(params.min_longitude)
        lon_max_360 = _to_0_360(params.max_longitude)
        wraps = lon_min_360 > lon_max_360

        per_variable = []
        for field_name, file_template in _VARIABLE_FILES.items():
            url = f"{self.settings.NOAA_OISST_BASE_URL}/{file_template.format(year=year)}"
            ds = self._open_with_retry(url)
            if ds is None:
                return None
            ds = _decode_time_coord(ds)

            source_var = _SOURCE_VARIABLE_NAMES[field_name]
            da = ds[source_var]

            time_slice = slice(str(params.start_date), str(params.end_date))
            lat_slice = slice(params.min_latitude, params.max_latitude)

            if not wraps:
                subset = da.sel(time=time_slice, lat=lat_slice, lon=slice(lon_min_360, lon_max_360))
            else:
                west = da.sel(time=time_slice, lat=lat_slice, lon=slice(lon_min_360, 360))
                east = da.sel(time=time_slice, lat=lat_slice, lon=slice(0, lon_max_360))
                subset = xr.concat([west, east], dim="lon")

            per_variable.append(subset.rename(field_name))

        merged = xr.merge(per_variable, join="inner")
        return merged

    def fetch(self, params: IngestionParams) -> pd.DataFrame:
        years = range(params.start_date.year, params.end_date.year + 1)
        frames: list[pd.DataFrame] = []

        for year in years:
            merged = self._open_year(year, params)
            if merged is None:
                continue
            df = merged.to_dataframe().reset_index()
            frames.append(df)

        if not frames:
            return pd.DataFrame(
                columns=["time", "lat", "lon", "sst", "sst_anomaly", "measurement_error", "ice_concentration"]
            )

        raw_df = pd.concat(frames, ignore_index=True)
        # Store longitude in the standard -180..180 convention used everywhere
        # else in this platform (PostGIS, OBIS), not NOAA's native 0..360.
        raw_df["lon"] = ((raw_df["lon"] + 180) % 360) - 180
        return raw_df

    def validate(self, raw_df: pd.DataFrame) -> tuple[pd.DataFrame, QualityMetrics]:
        metrics = QualityMetrics(records_read=len(raw_df))
        metrics.schema_mismatches = quality.check_schema(raw_df, _REQUIRED_RAW_COLUMNS)

        if raw_df.empty:
            return raw_df, metrics

        missing_valid, metrics.missing_values = quality.flag_missing(
            raw_df, ["time", "lat", "lon", "sst"]
        )
        dup_valid, metrics.duplicate_records = quality.flag_duplicates(
            raw_df, ["time", "lat", "lon"]
        )
        coord_valid, metrics.invalid_coordinates = quality.flag_invalid_coordinates(
            raw_df, "lat", "lon"
        )
        time_valid, metrics.invalid_timestamps = quality.flag_invalid_timestamps(raw_df, "time")
        sst_valid, metrics.invalid_sst = quality.flag_invalid_sst(raw_df, "sst")
        # Outliers are reported, not rejected - a legitimate marine heatwave
        # looks statistically identical to a bad sensor reading.
        _, outlier_count = quality.flag_outliers(raw_df, "sst")
        metrics.outliers = outlier_count

        keep = missing_valid & dup_valid & coord_valid & time_valid & sst_valid
        valid_df = raw_df.loc[keep].copy()

        metrics.records_valid = len(valid_df)
        metrics.records_rejected = metrics.records_read - metrics.records_valid
        # Longitude was normalized from 0..360 to -180..180 for every valid row.
        metrics.records_modified = metrics.records_valid
        metrics.details = {
            "longitude_convention": "normalized from 0..360 (NOAA native) to -180..180",
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
                    "ice_concentration",
                    "source_record_id",
                ]
            )

        out = pd.DataFrame(
            {
                "timestamp": pd.to_datetime(valid_df["time"], utc=True),
                "latitude": valid_df["lat"].astype(float),
                "longitude": valid_df["lon"].astype(float),
                "sst": valid_df["sst"].astype(float),
                "sst_anomaly": valid_df.get("sst_anomaly"),
                "measurement_error": valid_df.get("measurement_error"),
                "ice_concentration": valid_df.get("ice_concentration"),
                "source_record_id": (
                    valid_df["time"].astype(str)
                    + "_"
                    + valid_df["lat"].round(3).astype(str)
                    + "_"
                    + valid_df["lon"].round(3).astype(str)
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
                    "ice_concentration": (
                        None if pd.isna(record.ice_concentration) else record.ice_concentration
                    ),
                    "source_record_id": record.source_record_id,
                    "geometry": f"SRID=4326;POINT({record.longitude} {record.latitude})",
                }
            )

        db.execute(insert(OceanObservation), rows)
        db.commit()
        return len(rows)
