"""Refresh the whole Pacific product from the public sources, in order, without code changes:

    1. sync      download and validate NOAA OISST v2.1 (cached: only missing / changed days are fetched), merge onto one east-longitude axis
    1b. climate  download the Oceanic Nino Index and PDO index (labelled context only)
    2. build     align, mask, climatology, anomalies, features, splits  (oceanmind_preprocess)         skipped when the processed data are already up to date
    3. evaluate  score the forecast model on the held-out period, forecast from the latest day, marine heatwaves (current + historical)    (oceanmind_model)
    4. alerts    raise alerts from heatwaves, anomalies, ecological risk, species exposure and the forecast           (backend job)
    5. species   optional: refresh OBIS species records for the Pacific watch list (--species)

    python scripts/refresh_pacific.py                # normal daily refresh
    python scripts/refresh_pacific.py --force        # rebuild everything even if no new day arrived
    python scripts/refresh_pacific.py --species      # also refresh species records
    python scripts/refresh_pacific.py --only sync    # run a single stage (sync | climate | build | evaluate | alerts | species)

Every stage is re-runnable. Old data are kept: the merged store and the processed cubes hold the full record, never only the latest day, and each stage prints the dates it
used so a stale source is visible rather than hidden."""
from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CONFIG = "config.pacific.yaml"
STAGES = ["sync", "climate", "build", "evaluate", "alerts", "species"]


def run(args: list[str], cwd: Path = ROOT) -> None:
    print(f"\n$ {' '.join(args)}   (in {cwd.name})", flush=True)
    t = time.perf_counter()
    subprocess.run([sys.executable, *args], cwd=cwd, check=True)
    print(f"  done in {time.perf_counter() - t:.0f}s", flush=True)


def store_last_day(store: Path) -> str | None:
    try:
        import xarray as xr
        return str(xr.open_zarr(store).time.values.max())[:10]
    except Exception:  # noqa: BLE001 - no store yet
        return None


def processed_last_day(out: Path) -> str | None:
    import numpy as np
    last = None
    for sp in ("train", "val", "test"):
        f = out / "cubes" / f"{sp}_dates.npy"
        if f.exists():
            d = str(np.load(f)[-1])[:10]
            last = d if last is None or d > last else last
    return last


def staged_build(config: str, out: Path, store: Path) -> None:
    """Build the whole new generation (cubes, climatology, anomalies, forecast from the newest observation, marine heatwaves) in `<out>.staging`, check it, and only then replace the
    live dataset in one swap. The application keeps serving the previous generation until the swap; if any step fails the live dataset is untouched."""
    from oceanmind_environment import publish as pub
    from oceanmind_environment.refresh_status import check_consistency
    note = pub.recover(out)
    if note:
        print(note)
    stage_dir = pub.staging_dir(out)
    shutil.rmtree(stage_dir, ignore_errors=True)
    cfg_file = ROOT / "config.pacific.staging.yaml"
    cfg_file.write_text(f"extends: {config}" + chr(10) + "paths:" + chr(10) + f"  out_dir: {stage_dir.name}" + chr(10), encoding="utf-8")
    try:
        run(["-m", "oceanmind_preprocess", "build", "--config", cfg_file.name])
        if (out / "model").exists():                                       # the trained weights and their origin (not retrained by a refresh)
            shutil.copytree(out / "model", stage_dir / "model", dirs_exist_ok=True)
        run(["-m", "oceanmind_model", "evaluate", "--config", cfg_file.name])
        run(["-m", "oceanmind_model", "export-dashboard", "--config", cfg_file.name])
        check = check_consistency(stage_dir, store, ignore=("sst_history",))
        if not check["consistent"]:
            raise RuntimeError("the new generation is inconsistent and was not published: " + "; ".join(check["problems"]))
        kept = pub.carry_over(out, stage_dir)
        if kept:
            print("kept from the live dataset:", ", ".join(kept))
        marker = ROOT / "data" / "dataset_rebuild.lock"                     # tells a running API to let go of the cubes it has mapped (Windows cannot rename a mapped directory)
        marker.parent.mkdir(parents=True, exist_ok=True)
        marker.write_text("publishing")
        try:
            time.sleep(5)                                                  # the API checks the marker every 2 seconds
            prev = pub.swap(out, stage_dir)
        finally:
            marker.unlink(missing_ok=True)
        print(f"published generation ending {check['latest']}; forecast {check['forecast_dates'][0]} to {check['forecast_dates'][-1]}")
        pub.finalize(prev)
    finally:
        cfg_file.unlink(missing_ok=True)
        if stage_dir.exists():                                             # a failed build leaves nothing behind
            shutil.rmtree(stage_dir, ignore_errors=True)
    run(["-m", "app.jobs", "build-sst-history", "--dataset", "pacific"], cwd=ROOT / "backend")      # daily regional means behind the Historical SST graph


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--config", default=CONFIG)
    ap.add_argument("--force", action="store_true", help="rebuild even when no new day was downloaded")
    ap.add_argument("--only", choices=STAGES, help="run one stage")
    ap.add_argument("--species", action="store_true", help="also refresh OBIS species records")
    args = ap.parse_args()
    want = [args.only] if args.only else [s for s in STAGES if s != "species" or args.species]
    sys.path.insert(0, str(ROOT))
    from oceanmind_preprocess.config import _read_yaml
    cfg = _read_yaml((ROOT / args.config).resolve())            # plain read: the dataset may not exist yet, so the provider cannot be built before `sync`
    out = Path(cfg["paths"]["out_dir"])
    out = out if out.is_absolute() else ROOT / out
    store = Path(cfg["environment_provider"].get("source", {}).get("store", "data/pacific_oisst/sst.zarr"))
    store = store if store.is_absolute() else (ROOT / store)

    if "sync" in want:
        run(["-m", "oceanmind_environment", "sync", "--config", args.config])
    latest_source, latest_processed = store_last_day(store), processed_last_day(out)
    print(f"\nsource store: {latest_source}   processed data: {latest_processed}")
    stale = args.force or latest_source != latest_processed

    if "climate" in want:
        run(["-m", "app.jobs", "sync-climate-indices"], cwd=ROOT / "backend")      # ONI (NOAA CPC) and PDO (NOAA NCEI): labelled context for anomaly explanations
    published_staged = False
    if "build" in want:
        if not stale and args.only != "build":
            print("processed data are up to date with the source: build skipped")
        else:
            staged_build(args.config, out, store)
            published_staged = True
    if "evaluate" in want:
        if published_staged:
            print("forecast and heatwave results were built and published together with the dataset: evaluate skipped")
        elif not stale and args.only != "evaluate" and (out / "model" / "dashboard" / "heatwave_history.json").exists():
            print("forecast and heatwave results are up to date: evaluate skipped")
        else:
            run(["-m", "oceanmind_model", "evaluate", "--config", args.config])
            run(["-m", "oceanmind_model", "export-dashboard", "--config", args.config])
    if "alerts" in want:
        run(["-m", "app.jobs", "publish-dataset-alerts", "--dataset", "pacific"], cwd=ROOT / "backend")
    if "species" in want:
        run(["-m", "app.jobs", "sync-biodiversity", "--region", "pacific"], cwd=ROOT / "backend")

    summary = {"source_last_day": store_last_day(store), "processed_last_day": processed_last_day(out)}
    print("\n" + json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
