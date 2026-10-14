"""Per-horizon MAE / RMSE / R2 over valid ocean cells only."""
from __future__ import annotations

import numpy as np

BATCH = 64


def calculate_metrics(pred, truth, valid=None, horizons=None) -> dict:
    """pred, truth: (N, Hn, H, W) (or (N, H, W) for one horizon); valid: bool, broadcastable to truth
    (True = use the cell). Cells where valid is False or pred/truth is non-finite are excluded.

    R2 is the pooled spatio-temporal coefficient of determination per horizon:
    1 - SS_res / SS_tot, SS_tot taken about the mean of the valid truth values of that horizon.
    Returns {"horizons": [...], "mae": [...], "rmse": [...], "r2": [...], "n": [...]} (one entry per horizon)."""
    pred, truth = np.asarray(pred), np.asarray(truth)
    if pred.shape != truth.shape:
        raise ValueError(f"shape mismatch {pred.shape} vs {truth.shape}")
    if pred.ndim == 3:
        pred, truth = pred[:, None], truth[:, None]
        valid = None if valid is None else np.asarray(valid)[:, None]
    Hn = pred.shape[1]
    horizons = list(range(1, Hn + 1)) if horizons is None else list(horizons)
    valid = np.ones(truth.shape, bool) if valid is None else np.broadcast_to(np.asarray(valid, bool), truth.shape)
    out = {"horizons": horizons, "mae": [], "rmse": [], "r2": [], "n": []}
    for h in range(Hn):
        n = sae = sse = s1 = s2 = 0.0
        for a in range(0, pred.shape[0], BATCH):
            p = pred[a:a + BATCH, h].astype("float64")
            t = truth[a:a + BATCH, h].astype("float64")
            m = valid[a:a + BATCH, h] & np.isfinite(p) & np.isfinite(t)
            p, t = p[m], t[m]
            n += p.size
            sae += np.abs(p - t).sum()
            sse += ((p - t) ** 2).sum()
            s1 += t.sum()
            s2 += (t ** 2).sum()
        if n == 0:
            out["mae"].append(float("nan")); out["rmse"].append(float("nan")); out["r2"].append(float("nan"))
        else:
            sst = s2 - s1 * s1 / n
            out["mae"].append(sae / n)
            out["rmse"].append((sse / n) ** 0.5)
            out["r2"].append(1.0 - sse / sst if sst > 0 else float("nan"))
        out["n"].append(int(n))
    return out
