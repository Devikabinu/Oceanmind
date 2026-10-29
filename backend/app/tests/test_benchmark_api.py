"""/api/monitor/benchmark: a read-only view of a saved benchmark run. Uses a tiny hand-made results folder (TEST DATA ONLY)."""
import base64
import json

import pytest

from app.services import benchmark_service, environment
from app.tests._helpers import auth_headers

PNG_1X1 = base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNkYPhfDwAChwGA60e6kgAAAABJRU5ErkJggg==")
H = [1, 2, 3]


def _stat(mean, std=0.01):
    return {"mean": mean, "std": std}


def _model(base, params):
    return {"params": params, "mean_rmse": _stat(base), "mean_mae": _stat(base * 0.8), "mean_acc": _stat(0.9, 0.02),
            "rmse_by_horizon": {"mean": [base * 0.5, base, base * 1.5], "std": [0.01] * 3},
            "mae_by_horizon": {"mean": [base * 0.4, base * 0.8, base * 1.2], "std": [0.01] * 3},
            "train_seconds": _stat(30.0, 2.0), "epochs_run": _stat(10.0, 1.0), "per_seed_mean_rmse": [base] * 3}


def _baseline(base):
    return {"mean_rmse": base, "mean_mae": base * 0.8, "mean_acc": None, "rmse": [base] * 3, "mae": [base * 0.8] * 3}


RESULTS = {
    "horizons": H, "n_test_windows": 10,
    "settings": {"data": {"benchmark_block": {"start": "2023-05-01", "end": "2026-04-30", "days": 1096},
                          "split_dates": {"train": ["2023-05-01", "2025-07-30"], "val": ["2025-07-31", "2025-12-09"], "test": ["2025-12-10", "2026-04-30"]}},
                 "training": {"seeds": [0, 1, 2]}},
    "models": {"cnn_only": _model(0.30, 1000), "lstm_only": _model(0.40, 1100), "hybrid_convlstm": _model(0.20, 1050)},
    "baselines": {"persistence": _baseline(0.50), "climatology": _baseline(0.90)},
    "sample_map": {"date": "2026-02-25", "horizon_days": 7, "seed": 0},
}


@pytest.fixture
def bench(tmp_path, monkeypatch):
    run = tmp_path / "benchmark" / benchmark_service.RUN_DIR
    run.mkdir(parents=True)
    (run / "results.json").write_text(json.dumps(RESULTS))
    (run / benchmark_service.MAPS_FILE).write_bytes(PNG_1X1)
    monkeypatch.setattr(environment, "processed_dir", lambda: tmp_path)
    return run


def test_benchmark_requires_auth(client):
    assert client.get("/api/monitor/benchmark").status_code == 401


def test_benchmark_returns_the_stored_numbers_unchanged(client, bench):
    r = client.get("/api/monitor/benchmark", headers=auth_headers(client))
    assert r.status_code == 200, r.text
    b = r.json()
    assert b["test_period"] == ["2025-12-10", "2026-04-30"]
    assert b["horizons"] == H
    by = {m["key"]: m for m in b["models"]}
    assert set(by) == {"cnn_only", "lstm_only", "hybrid_convlstm"}
    assert by["hybrid_convlstm"]["mean_rmse"] == {"mean": 0.20, "std": 0.01}
    assert by["cnn_only"]["params"] == 1000
    assert by["lstm_only"]["rmse_by_horizon"]["mean"] == [0.2, 0.4, 0.6000000000000001]
    assert b["baselines"]["persistence"]["mean_rmse"] == 0.50
    assert b["baselines"]["climatology"]["mean_acc"] is None


def test_benchmark_includes_the_sample_map_as_a_png_data_uri(client, bench):
    sm = client.get("/api/monitor/benchmark", headers=auth_headers(client)).json()["sample_map"]
    assert sm["date"] == "2026-02-25" and sm["horizon_days"] == 7
    assert sm["image"].startswith("data:image/png;base64,")
    assert base64.b64decode(sm["image"].split(",", 1)[1]) == PNG_1X1


def test_benchmark_without_a_map_file_still_returns_the_numbers(client, bench):
    (bench / benchmark_service.MAPS_FILE).unlink()
    b = client.get("/api/monitor/benchmark", headers=auth_headers(client)).json()
    assert b["sample_map"]["image"] is None and len(b["models"]) == 3


def test_benchmark_is_503_when_no_results_exist(client, tmp_path, monkeypatch):
    monkeypatch.setattr(environment, "processed_dir", lambda: tmp_path)   # empty folder
    r = client.get("/api/monitor/benchmark", headers=auth_headers(client))
    assert r.status_code == 503 and "results.json" in r.json()["detail"]


def test_benchmark_endpoint_is_read_only(client, bench):
    h = auth_headers(client)
    for method in (client.post, client.put, client.patch, client.delete):
        assert method("/api/monitor/benchmark", headers=h).status_code == 405


# ---- the committed run, read through the real route, whatever the working directory
def test_the_committed_benchmark_is_served_from_the_project_root_regardless_of_the_working_directory(client, tmp_path, monkeypatch):
    from pathlib import Path
    monkeypatch.chdir(tmp_path)                                                              # a working directory that has no processed/ folder
    monkeypatch.setattr(environment.get_settings(), "PROCESSED_DIR", "", raising=False)       # the default: derived from the code's own location, not from the cwd
    root = Path(environment.__file__).resolve().parents[3]
    committed = json.loads((root / "processed" / "benchmark" / benchmark_service.RUN_DIR / "results.json").read_text(encoding="utf-8"))
    assert environment.processed_dir() == root / "processed"
    r = client.get("/api/monitor/benchmark", headers=auth_headers(client))
    assert r.status_code == 200
    b = r.json()
    assert [m["key"] for m in b["models"]] == ["cnn_only", "lstm_only", "hybrid_convlstm"]
    for m in b["models"]:                                                                    # every number is the stored one, unchanged
        assert m["mean_rmse"] == committed["models"][m["key"]]["mean_rmse"] and m["mean_mae"] == committed["models"][m["key"]]["mean_mae"]
    assert b["sample_map"]["image"] is None or b["sample_map"]["image"].startswith("data:image/png;base64,")


def test_the_benchmark_route_is_mounted_under_the_api_prefix_and_nowhere_else(client):
    paths = set(client.get("/openapi.json").json()["paths"])
    assert "/api/monitor/benchmark" in paths and "/monitor/benchmark" not in paths and "/api/benchmark" not in paths
