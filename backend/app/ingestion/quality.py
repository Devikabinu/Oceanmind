"""Reusable data-quality checks shared by every ingestion adapter.

Each `flag_*` function returns a boolean Series that is True for rows that
PASS the check, plus the count of rows that failed it. Adapters combine these
into a single valid mask so every rejected row is attributable to a specific
reason in the resulting QualityMetrics/DataQualityReport.
"""

import numpy as np
import pandas as pd


def check_schema(df: pd.DataFrame, required_columns: list[str]) -> int:
    """Returns the number of required columns absent from the raw payload."""
    return len(set(required_columns) - set(df.columns))


def flag_missing(df: pd.DataFrame, required_columns: list[str]) -> tuple[pd.Series, int]:
    present_columns = [c for c in required_columns if c in df.columns]
    if not present_columns:
        return pd.Series(True, index=df.index), 0
    valid = ~df[present_columns].isna().any(axis=1)
    return valid, int((~valid).sum())


def flag_duplicates(df: pd.DataFrame, key_columns: list[str]) -> tuple[pd.Series, int]:
    present_columns = [c for c in key_columns if c in df.columns]
    if not present_columns:
        return pd.Series(True, index=df.index), 0
    is_duplicate = df.duplicated(subset=present_columns, keep="first")
    return ~is_duplicate, int(is_duplicate.sum())


def flag_invalid_coordinates(
    df: pd.DataFrame, lat_col: str, lon_col: str
) -> tuple[pd.Series, int]:
    lat = pd.to_numeric(df[lat_col], errors="coerce")
    lon = pd.to_numeric(df[lon_col], errors="coerce")
    valid = lat.between(-90, 90) & lon.between(-180, 180) & lat.notna() & lon.notna()
    return valid, int((~valid).sum())


def flag_invalid_timestamps(df: pd.DataFrame, time_col: str) -> tuple[pd.Series, int]:
    parsed = pd.to_datetime(df[time_col], errors="coerce", utc=True)
    valid = parsed.notna()
    return valid, int((~valid).sum())


def flag_invalid_sst(
    df: pd.DataFrame, sst_col: str, min_valid_c: float = -3.0, max_valid_c: float = 40.0
) -> tuple[pd.Series, int]:
    """Physically plausible sea surface temperature range in degrees Celsius.
    Seawater freezes around -1.8C; open-ocean SST rarely exceeds ~35C.
    """
    if sst_col not in df.columns:
        return pd.Series(True, index=df.index), 0
    sst = pd.to_numeric(df[sst_col], errors="coerce")
    valid = sst.isna() | sst.between(min_valid_c, max_valid_c)
    return valid, int((~valid).sum())


def flag_outliers(df: pd.DataFrame, column: str, z_threshold: float = 4.0) -> tuple[pd.Series, int]:
    """Flags statistical outliers via z-score. Used in addition to (not instead
    of) the physically-plausible-range check, to catch values that are valid
    in range but anomalous relative to the rest of the batch.
    """
    if column not in df.columns:
        return pd.Series(True, index=df.index), 0
    values = pd.to_numeric(df[column], errors="coerce")
    std = values.std(ddof=0)
    if not std or np.isnan(std):
        return pd.Series(True, index=df.index), 0
    z_scores = (values - values.mean()).abs() / std
    valid = values.isna() | (z_scores <= z_threshold)
    return valid, int((~valid).sum())
