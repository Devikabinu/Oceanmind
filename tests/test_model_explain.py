"""Putting a dataset on the checkpoint's scale, and the sensitivity analysis of the trained forecast model."""
import json
from pathlib import Path

import numpy as np
import pytest

from oceanmind_model.normalisation import ModelSpace

ROOT = Path(__file__).resolve().parents[1]
CH = ["sst", "sst_anom", "sst_grad", "doy_sin", "mask_sst"]


def dataset(tmp_path, declared=True):
    root = tmp_path / "ds"
    (root / "model").mkdir(parents=True)
    (root / "stats.json").write_text(json.dumps({"channels": {"sst": {"mean": 20.0, "std": 8.0}, "sst_anom": {"mean": 0.0, "std": 1.0}, "sst_grad": {"mean": 0.1, "std": 0.2}}}))
    if declared:
        (tmp_path / "ne_stats.json").write_text(json.dumps({"channels": {"sst": {"mean": 18.0, "std": 5.0}, "sst_anom": {"mean": 0.0, "std": 0.5}, "sst_grad": {"mean": 0.1, "std": 0.1}}}))
        (root / "model" / "checkpoint_origin.json").write_text(json.dumps({"normalization_stats": "ne_stats.json"}))
    return root


def test_without_a_declaration_the_dataset_is_used_unchanged(tmp_path):
    sp = ModelSpace(dataset(tmp_path, declared=False), channels=CH)
    x = np.random.default_rng(0).normal(size=(2, 5, 3, 4)).astype("float32")
    assert sp.convert(x) is x and sp.output == {"mean": 20.0, "std": 8.0}


def test_conversion_to_the_training_scale_preserves_degrees_and_roundtrips(tmp_path):
    sp = ModelSpace(dataset(tmp_path), channels=CH)
    sst_c = np.array([[15.0, 25.0], [20.0, 30.0]], dtype="float32")
    x = np.zeros((5, 2, 2), dtype="float32")
    x[0] = (sst_c - 20.0) / 8.0                                                                       # the dataset's own z-score
    x[4] = 1.0                                                                                        # mask: not rescaled
    y = sp.convert(x)
    np.testing.assert_allclose(y[0] * 5.0 + 18.0, sst_c, atol=1e-4)                                     # same degrees on the training scale
    assert (y[4] == 1.0).all() and x[0, 0, 0] == pytest.approx(-5 / 8)                                  # mask untouched, input not modified
    np.testing.assert_allclose(sp.to_degC(y[0]), sst_c, atol=1e-4)                                      # output converted with the training statistics


@pytest.mark.skipif(not (ROOT / "processed_pacific" / "model" / "best_model.pt").exists(), reason="trained Pacific model not present")
def test_sensitivity_of_the_trained_model_is_real_and_consistent_with_the_exported_forecast():
    from oceanmind_preprocess.config import load_config
    from oceanmind_model.explain import explain_cell
    cfg = load_config(str(ROOT / "config.pacific.yaml"))
    e = explain_cell(cfg, 0.0, -150.0, device="cpu")
    w = e["input_window"]
    assert w["days"] == 7 == len(w["sst_c"]) and len(e["forecast_c"]) == 7
    s = e["sensitivity"]
    assert len(s["temporal"]["delta_c"]) == 7 and all(len(r) == 7 for r in s["temporal"]["delta_c"])
    assert len(s["local_all_days_c"]) == 7 and len(s["everywhere_all_days_c"]) == 7
    allv = np.array(s["temporal"]["delta_c"] + [s["local_all_days_c"], s["everywhere_all_days_c"]])
    assert np.isfinite(allv).all() and np.abs(allv).max() > 0                                          # the model responds to its input: not a constant
    assert np.abs(s["everywhere_all_days_c"]).max() >= np.abs(s["temporal"]["delta_c"][0]).max()      # removing everything matters at least as much as one day
    snap = np.load(ROOT / "processed_pacific" / "model" / "dashboard" / "snapshot.npz")
    i, j = e["cell"]["row"], e["cell"]["col"]
    info = json.loads((ROOT / "processed_pacific" / "model" / "dashboard" / "snapshot.json").read_text())
    if info["latest"]["observed_date"] == w["dates"][-1]:
        np.testing.assert_allclose(e["forecast_c"], snap["latest_forecast"][:, i, j], atol=0.05)       # explanation of the forecast that is shown


@pytest.mark.skipif(not (ROOT / "processed_pacific" / "model" / "best_model.pt").exists(), reason="trained Pacific model not present")
def test_land_cells_are_refused():
    from oceanmind_preprocess.config import load_config
    from oceanmind_model.explain import explain_cell
    with pytest.raises(ValueError, match="land"):
        explain_cell(load_config(str(ROOT / "config.pacific.yaml")), 48.0, -100.0, device="cpu")       # North America
