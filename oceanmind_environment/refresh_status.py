"""What the daily refresh did, and whether every product of the Pacific dataset refers to the same observation day.

`data/refresh_status.json` is written after every attempt (also a failed one) and read by the backend, so the interface can show the real latest date and the outcome of the last
attempt: a source that was unreachable or had nothing newer leaves the previous valid dataset in place and says so, it never produces data."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

from .schedule import FORECAST_HORIZONS, forecast_window

STATUS_FILE = Path("data") / "refresh_status.json"
OUTCOMES = ("running", "updated", "unchanged", "source_unavailable", "failed")
RUNNING_MAX_AGE_S = 4 * 3600            # a run that has not finished after this long (the lock limit of the scheduler script) is reported as interrupted


def write_status(root: Path, **fields) -> dict:
    """Record one attempt. `last_success_at` is the time of the newest attempt that reached NOAA and ended with a consistent dataset (updated, or nothing newer); a failed attempt keeps the
    previous one, so the display can say how long ago the data were last confirmed. `last_update_at` is when the dataset last changed."""
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    before = read_status(root) or {}
    status = {"attempted_at": now, **fields}
    ok = fields.get("outcome") in ("updated", "unchanged") and fields.get("consistent", True)
    status.setdefault("last_success_at", now if ok else before.get("last_success_at"))
    status.setdefault("last_update_at", now if fields.get("outcome") == "updated" else before.get("last_update_at"))
    status.setdefault("source_checked_at", now if fields.get("source_latest") else before.get("source_checked_at"))          # when NOAA was last actually asked and answered
    f = Path(root) / STATUS_FILE
    f.parent.mkdir(parents=True, exist_ok=True)
    tmp = f.with_suffix(".tmp")
    tmp.write_text(json.dumps(status, indent=1))
    tmp.replace(f)
    return status


def read_status(root: Path) -> dict | None:
    f = Path(root) / STATUS_FILE
    try:
        return json.loads(f.read_text())
    except (OSError, ValueError):
        return None


def _last_date(npy: Path):
    return str(pd.Timestamp(np.load(npy)[-1]).date()) if npy.exists() else None


def check_consistency(processed: Path, store: Path | None = None, ignore: tuple = ()) -> dict:
    """The newest day of every product of a processed dataset: source store, processed cubes, heatwave results, forecast, SST-history cache. They must all be one day, and the
    forecast must start on the day after it. Returns {"consistent": bool, "latest": ..., "products": {...}, "problems": [...]}."""
    processed = Path(processed)
    dash = processed / "model" / "dashboard"
    products: dict = {}
    cubes = [d for d in (_last_date(processed / "cubes" / f"{s}_dates.npy") for s in ("train", "val", "test")) if d]
    products["processed_cubes"] = max(cubes) if cubes else None
    try:
        products["heatwaves"] = json.loads((dash / "heatwave.json").read_text())["latest_date"]
    except (OSError, ValueError, KeyError):
        products["heatwaves"] = None
    forecast_dates = None
    try:
        snap = json.loads((dash / "snapshot.json").read_text())["latest"]
        products["forecast_issued_from"] = snap["observed_date"]
        forecast_dates = snap["target_dates"]
    except (OSError, ValueError, KeyError):
        products["forecast_issued_from"] = None
    try:
        with np.load(processed / "region_series.npz") as z:
            products["sst_history"] = str(pd.Timestamp(z["dates"][-1]).date())
    except (OSError, ValueError, KeyError):
        products["sst_history"] = None
    if store is not None:
        try:
            import xarray as xr
            with xr.open_zarr(store) as ds:
                products["source_store"] = str(pd.Timestamp(ds.time.values[-1]).date())
        except Exception:  # noqa: BLE001
            products["source_store"] = None
    for k in ignore:                                                  # e.g. the SST-history cache of a dataset that is still being staged
        products.pop(k, None)
    present = {k: v for k, v in products.items() if v}
    problems = [f"{k} is missing" for k, v in products.items() if not v]
    latest = max(present.values()) if present else None
    problems += [f"{k} ends {v}, not {latest}" for k, v in present.items() if v != latest]
    if forecast_dates is not None and latest is not None and products["forecast_issued_from"] == latest and forecast_dates != forecast_window(latest, len(forecast_dates)):
        problems.append(f"forecast covers {forecast_dates[0]}..{forecast_dates[-1]}, expected to start the day after {latest}")
    return {"consistent": not problems, "latest": latest, "products": products, "forecast_dates": forecast_dates, "problems": problems, "horizons": FORECAST_HORIZONS}
