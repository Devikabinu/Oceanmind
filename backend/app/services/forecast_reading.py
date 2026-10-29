"""Reading a 7-day forecast in plain language, from its own numbers only.

Used by the location report and by the forecast explanation so that both say the same thing. Nothing here knows a cause: it classifies what the model predicts
(warming / cooling / stable; anomaly strengthening / weakening / persistent / changing sign) and quotes the values."""
from __future__ import annotations

import numpy as np

STABLE_C = 0.15          # |change of SST over the whole forecast| below this is called stable
SHIFT_C = 0.3            # a change of the anomaly smaller than this is "persistent"
SIGN_C = 0.5             # a sign change counts only when the new anomaly is at least this large


def classify_anomaly(a: float | None) -> str | None:
    """Low / Moderate / High / Extreme by the size of the departure from normal (either sign)."""
    if a is None or not np.isfinite(a):
        return None
    m = abs(a)
    return "Low" if m < 1.0 else "Moderate" if m < 2.0 else "High" if m < 3.0 else "Extreme"


def sg(v: float, d: int = 2) -> str:
    """A signed number that never prints -0.00."""
    return f"{0.0:.{d}f}" if abs(v) < 0.5 * 10 ** -d else f"{v:+.{d}f}"


SEASON_MATCH_C = 0.15        # the predicted change counts as "about the normal seasonal change" when it is this close to it


def day_direction(change: float, flat: float = 0.05) -> str:
    return "stable" if abs(change) < flat else "warming" if change > 0 else "cooling"


def trajectory(anom_now: float, end: float) -> str:
    """near normal / changing sign / strengthening / weakening / persistent: the one rule every sentence about the anomaly's future uses."""
    if abs(anom_now) < SIGN_C and abs(end) < SIGN_C:
        return "near normal"
    if anom_now * end < 0 and abs(end) >= SIGN_C:
        return "changing sign"
    if abs(end) < SIGN_C and abs(anom_now) >= SIGN_C:
        return "returning toward normal"
    if abs(end) > abs(anom_now) + SHIFT_C:
        return "strengthening"
    if abs(end) < abs(anom_now) - SHIFT_C:
        return "weakening"
    return "persistent"


EXPECTED_ING = {"returning toward normal": "returning toward normal", "near normal": "staying close to normal", "changing sign": "changing sign", "strengthening": "strengthening", "weakening": "weakening", "persistent": "persisting"}
EXPECTED = {"returning toward normal": "return toward normal", "near normal": "stay close to normal", "changing sign": "change sign", "strengthening": "strengthen", "weakening": "weaken", "persistent": "persist"}


def reading(sst_now: float, anom_now: float, sst_f: list[float], anom_f: list[float], dates: list[str] | None = None, typical_error: list[float] | None = None,
            clim_f: list[float] | None = None, normal_now: float | None = None) -> dict:
    n = len(anom_f)
    a = np.asarray(anom_f, dtype=float)
    s = np.asarray(sst_f, dtype=float)
    change = float(s[-1] - sst_now)
    direction = "stable" if abs(change) < STABLE_C else "warming" if change > 0 else "cooling"
    end = float(a[-1])
    peak = int(np.argmax(np.abs(a)))
    peak_a = float(a[peak])
    seasonal = None if clim_f is None or normal_now is None else float(clim_f[-1] - normal_now)
    label = trajectory(anom_now, end)
    side = "warm" if anom_now >= 0 else "cold"
    span = f"{sg(anom_now, 1)} °C now to {sg(end, 1)} °C at day +{n}"
    if label == "near normal":
        text = (f"The model predicts {direction if direction != 'stable' else 'little change'} in SST ({change:+.2f} °C over {n} days)"
                + (f", about the normal seasonal change ({sg(seasonal)} °C)" if seasonal is not None and abs(change - seasonal) < SEASON_MATCH_C else "")
                + f". The anomaly stays close to normal ({sg(anom_now, 1)} °C now, {sg(end, 1)} °C at day +{n}).")
    elif direction == "stable":
        text = f"The model predicts little change in SST ({change:+.2f} °C over {n} days). The anomaly is {label}: {span}."
    elif 0 < peak < n - 1 and abs(peak_a) > abs(end) + SHIFT_C and abs(peak_a) > abs(anom_now) + SHIFT_C:
        text = (f"The model predicts {direction} over the next {peak + 1} days, with the {side} anomaly increasing from {anom_now:+.1f} °C to {peak_a:+.1f} °C "
                f"before beginning to weaken to {end:+.1f} °C by day +{n}.")
    elif label == "changing sign":
        text = f"The model predicts {direction}. The anomaly changes sign over the forecast: {span}."
    elif label == "returning toward normal":
        text = f"The model predicts gradual {direction}. The {side} anomaly returns toward normal: {span}."
    elif label == "weakening":
        text = f"The model predicts gradual {direction}. The {side} anomaly weakens: {span}."
    elif label == "strengthening":
        text = f"The model predicts continued {direction}. The {side} anomaly strengthens: {span}."
    else:
        seas = (f", about the normal seasonal change of {sg(seasonal)} °C" if seasonal is not None and abs(change - seasonal) < SEASON_MATCH_C else "")
        text = f"The model predicts {direction} by {abs(change):.2f} °C over {n} days{seas}, with the {side} anomaly persisting: {span}."
    return {"label": direction, "anomaly_label": label, "sst_change_c": round(change, 2), "peak_day": peak + 1, "peak_anomaly_c": round(peak_a, 2),
            "max_abs_anomaly_c": round(float(np.abs(a).max()), 2), "mean_anomaly_c": round(float(a.mean()), 2), "anomaly_now_c": round(float(anom_now), 2), "anomaly_end_c": round(end, 2),
            "seasonal_change_c": None if seasonal is None else round(seasonal, 2), "days": n, "text": text + (f" Typical model error at day +{n} is ±{typical_error[-1]:.2f} °C." if typical_error else "")}


def trend_label(values: list[float], flat: float = 0.1) -> str:
    """rising / falling / steady for a short series (change between its first and last value)."""
    d = float(values[-1] - values[0])
    return "steady" if abs(d) < flat else "rising" if d > 0 else "falling"
