"""Unit tests for the simplified Hobday-style event detection (synthetic series; the logic, not the data)."""
import numpy as np

from oceanmind_model.heatwaves import _baseline_threshold, detect_runs


def series(pattern):
    return np.array([c == "x" for c in pattern], dtype=bool)[:, None]  # (T, 1 cell)


def test_runs_shorter_than_five_days_are_dropped():
    mhw, _ = detect_runs(series("..xxxx.........."))
    assert not mhw.any()


def test_five_day_run_is_an_event_and_marks_every_day_of_the_run():
    mhw, rl = detect_runs(series("..xxxxx........"))
    assert mhw[:, 0].tolist() == [c == "x" for c in "..xxxxx........"]
    assert rl[6, 0] == 5


def test_gaps_of_up_to_two_days_are_bridged_but_three_are_not():
    bridged, _ = detect_runs(series("xxx..xxx....."))      # 3 + 2 gap + 3 -> one 8-day event
    assert bridged[:, 0].tolist() == [True] * 8 + [False] * 5
    split, _ = detect_runs(series("xxx...xxx....."))       # 3-day gap: two runs of 3 -> no event
    assert not split.any()


def test_event_still_in_progress_on_the_last_day_counts_once_it_is_five_days_old():
    assert detect_runs(series("........xxxxx"))[0][-1, 0]      # 5 days so far -> active today
    assert not detect_runs(series(".........xxxx"))[0][-1, 0]  # only 4 days so far -> not yet


def test_run_length_counts_bridged_days_and_resets_after_the_event():
    _, rl = detect_runs(series("xxxxxxx..xx.........."))
    assert rl[6, 0] == 7 and rl[10, 0] == 11 and rl[12, 0] == 0


def test_threshold_is_the_baseline_90th_percentile_of_the_same_season_only():
    import pandas as pd
    dates = pd.date_range("2012-01-01", "2023-12-31", freq="D").append(pd.date_range("2024-01-01", "2024-12-31", freq="D"))
    rng = np.random.default_rng(0)
    sst = (15 + rng.normal(0, 1, (len(dates), 1, 1))).astype("float32")
    sst[dates >= "2024-01-01"] += 50  # 2024 is outside the baseline and must not influence the threshold
    thr = _baseline_threshold(sst, dates)
    assert thr.shape == (366, 1, 1)
    assert 15.5 < float(thr[180, 0, 0]) < 17.0  # ~ mean + 1.28 sd for N(15, 1)
