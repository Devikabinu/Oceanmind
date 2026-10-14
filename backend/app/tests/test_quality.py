import pandas as pd

from app.ingestion import quality


def test_check_schema_reports_missing_columns():
    df = pd.DataFrame({"a": [1], "b": [2]})
    assert quality.check_schema(df, ["a", "b", "c"]) == 1
    assert quality.check_schema(df, ["a", "b"]) == 0


def test_flag_missing_counts_any_null_in_required_columns():
    df = pd.DataFrame({"lat": [1.0, None, 3.0], "lon": [1.0, 2.0, None]})
    valid, count = quality.flag_missing(df, ["lat", "lon"])
    assert count == 2
    assert list(valid) == [True, False, False]


def test_flag_duplicates_keeps_first_occurrence():
    df = pd.DataFrame({"k": ["a", "a", "b"]})
    valid, count = quality.flag_duplicates(df, ["k"])
    assert count == 1
    assert list(valid) == [True, False, True]


def test_flag_invalid_coordinates_rejects_out_of_range():
    df = pd.DataFrame({"lat": [0, 91, -90, 45], "lon": [0, 10, 200, -181]})
    valid, count = quality.flag_invalid_coordinates(df, "lat", "lon")
    assert count == 3
    assert list(valid) == [True, False, False, False]


def test_flag_invalid_timestamps_rejects_unparseable_values():
    df = pd.DataFrame({"t": ["2023-01-01", "not-a-date", None]})
    valid, count = quality.flag_invalid_timestamps(df, "t")
    assert count == 2
    assert list(valid) == [True, False, False]


def test_flag_invalid_sst_uses_physically_plausible_range():
    df = pd.DataFrame({"sst": [-5.0, -1.5, 15.0, 45.0, None]})
    valid, count = quality.flag_invalid_sst(df, "sst", min_valid_c=-3.0, max_valid_c=40.0)
    # -5.0 and 45.0 are out of range; None passes through (missing is a
    # separate check, not this one's responsibility).
    assert count == 2
    assert list(valid) == [False, True, True, False, True]


def test_flag_outliers_flags_extreme_deviation():
    df = pd.DataFrame({"v": [10.0] * 20 + [1000.0]})
    valid, count = quality.flag_outliers(df, "v", z_threshold=4.0)
    assert count == 1
    assert valid.iloc[-1] == False  # noqa: E712 - clearer as a literal here
