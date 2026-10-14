"""Window indices for forecasting and anomaly detection. Windows never cross a split boundary."""
from __future__ import annotations

import numpy as np
import pandas as pd


def daily_missing_frac(cube, names, ocean, filter_vars):
    """Mean over filter_vars of the fraction of ocean cells without data, per day."""
    fr = []
    for v in filter_vars:
        i = names.index(f"mask_{v}")
        fr.append(np.concatenate([1.0 - np.asarray(cube[t:t + 256, i])[:, ocean].mean(axis=1)
                                  for t in range(0, cube.shape[0], 256)]))
    return np.mean(fr, axis=0)


def forecast_index(miss, nrt, dates, lookback, horizons, max_frac, stride=1):
    """One row per accepted window. A window spans `lookback` input days and targets at
    last_input_day + h for each h in horizons. Returns (DataFrame, n_skipped)."""
    hz = np.asarray(horizons)
    n = len(miss)
    rows, skipped = [], 0
    for s in range(0, n - (lookback + hz.max()) + 1, stride):
        tgt = s + lookback - 1 + hz
        frac = np.mean(np.concatenate([miss[s:s + lookback], miss[tgt]]))
        if frac > max_frac:
            skipped += 1
            continue
        rows.append({
            "start_idx": s,
            "start_date": dates[s],
            "input_end_date": dates[s + lookback - 1],
            "target_first_date": dates[tgt[0]],
            "target_last_date": dates[tgt[-1]],
            "miss_frac": float(frac),
            "n_nrt_days": int(nrt[s:s + lookback].sum()),
        })
    return pd.DataFrame(rows, columns=["start_idx", "start_date", "input_end_date", "target_first_date",
                                       "target_last_date", "miss_frac", "n_nrt_days"]), skipped


def anomaly_index(miss, nrt, dates, days, max_frac):
    rows, skipped = [], 0
    for s in range(0, len(miss) - days + 1):
        frac = float(miss[s:s + days].mean())
        if frac > max_frac:
            skipped += 1
            continue
        rows.append({"start_idx": s, "start_date": dates[s], "miss_frac": frac,
                     "n_nrt_days": int(nrt[s:s + days].sum())})
    return pd.DataFrame(rows, columns=["start_idx", "start_date", "miss_frac", "n_nrt_days"]), skipped
