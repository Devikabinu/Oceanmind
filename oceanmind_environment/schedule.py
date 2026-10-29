"""Which day the newest SST observation should be, which one it actually is, and which days the forecast covers. Nothing here is a fixed date: every value is derived from
the clock and from the days a data source really offers.

Operational lag: NOAA publishes the preliminary OISST field for a day about a day later, so on day D the newest observation to expect is D - OPERATIONAL_LAG_DAYS, and the
7-day forecast issued from it covers D through D + 6."""
from __future__ import annotations

import numpy as np
import pandas as pd

OPERATIONAL_LAG_DAYS = 1
FORECAST_HORIZONS = 7
MIN_DAY_COVERAGE = 0.5          # a trailing day with less than this share of the usual number of valid ocean cells is an incomplete delivery, not an observation


def today(now=None) -> pd.Timestamp:
    """The local calendar date (the operator's day), as a midnight timestamp."""
    t = pd.Timestamp(now) if now is not None else pd.Timestamp.now()
    return t.tz_localize(None).normalize() if t.tzinfo else t.normalize()


def expected_latest(now=None, lag_days: int = OPERATIONAL_LAG_DAYS) -> pd.Timestamp:
    return today(now) - pd.Timedelta(days=lag_days)


def discover_latest(*day_lists) -> pd.Timestamp | None:
    """The newest day offered by any of the product listings (final, preliminary), or None when a source offers none."""
    days = [pd.DatetimeIndex(d) for d in day_lists if d is not None and len(d)]
    return max(d.max() for d in days).normalize() if days else None


def lag_status(latest, now=None, lag_days: int = OPERATIONAL_LAG_DAYS) -> dict:
    """How the newest observation compares with the one expected today. `behind_expected` is 0 when the data are as new as the lag allows."""
    latest = pd.Timestamp(latest).normalize()
    exp = expected_latest(now, lag_days)
    behind = int((exp - latest).days)
    status = "current" if behind <= 0 else "delayed" if behind <= 2 else "stale"
    return {"latest": str(latest.date()), "expected": str(exp.date()), "behind_expected": max(behind, 0), "status": status, "lag_days": lag_days}


def forecast_window(latest, horizons: int = FORECAST_HORIZONS) -> list[str]:
    """The days a forecast issued from the observation of `latest` covers: the day after it, for `horizons` days."""
    start = pd.Timestamp(latest).normalize() + pd.Timedelta(days=1)
    return [str(d.date()) for d in pd.date_range(start, periods=horizons)]


def trim_incomplete_tail(times: pd.DatetimeIndex, valid_cells: np.ndarray) -> tuple[pd.DatetimeIndex, int]:
    """Drop trailing days whose number of valid cells is far below the record's usual (a partly delivered or empty day). Returns the kept times and how many days were dropped.
    The newest valid observation is then the last kept day."""
    valid_cells = np.asarray(valid_cells, dtype=float)
    if len(valid_cells) == 0:
        return times, 0
    usual = float(np.median(valid_cells[valid_cells > 0])) if (valid_cells > 0).any() else 0.0
    keep = len(valid_cells)
    while keep > 0 and valid_cells[keep - 1] < MIN_DAY_COVERAGE * usual:
        keep -= 1
    return times[:keep], len(valid_cells) - keep
