"""Daily, unattended refresh of the Pacific product. Meant to be started by the scheduler (see scripts/install_daily_task.ps1) but safe to run by hand.

    python scripts/daily_refresh.py            # check NOAA, and when a newer observation exists rebuild everything that depends on it
    python scripts/daily_refresh.py --force    # rebuild even when nothing newer arrived

What it does, in order:
  1. sync: ask NOAA for the newest day (never a fixed date), download and validate what is missing, keep the previous valid store if anything fails;
  2. only when the newest observation is newer than the processed data: climate indices, preprocessing, SST-history cache, ConvLSTM evaluation and the 7-day forecast that
     starts the day after the newest observation, marine heatwaves, alerts;
  3. check that every product refers to the same observation day, and write data/refresh_status.json (what happened, newest day, expected day, forecast dates).

If NOAA is unreachable or has nothing newer, the previous valid dataset stays in place and the status says so: no value is invented, and the interface shows the actual
latest date. A lock file prevents two runs at once; the log is logs/daily_refresh.log."""
from __future__ import annotations

import argparse
import json
import logging
import os
import signal
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from oceanmind_environment.refresh_status import check_consistency, write_status  # noqa: E402
from oceanmind_environment.schedule import expected_latest, lag_status  # noqa: E402

LOCK = ROOT / "data" / "refresh.lock"
LOCK_MAX_AGE_S = 4 * 3600
CONFIG = "config.pacific.yaml"
log = logging.getLogger("daily_refresh")


def stage(*args: str, cwd: Path = ROOT, capture: bool = False) -> subprocess.CompletedProcess:
    cmd = [sys.executable, *args]
    log.info("$ %s", " ".join(cmd))
    t = time.perf_counter()
    r = subprocess.run(cmd, cwd=cwd, capture_output=capture, text=True)
    log.info("  exit %s in %.0fs", r.returncode, time.perf_counter() - t)
    if capture and r.stdout:
        log.info(r.stdout[-1500:])
    if capture and r.returncode != 0:
        log.error((r.stderr or "")[-1500:])
    return r


def pid_alive(pid: int) -> bool:
    """Whether a process with this id exists (without signalling it: on Windows os.kill would terminate it)."""
    if pid <= 0:
        return False
    if os.name == "nt":
        r = subprocess.run(["tasklist", "/FI", f"PID eq {pid}", "/NH"], capture_output=True, text=True)
        return str(pid) in r.stdout
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def lock_holder() -> int | None:
    """The process that holds a valid lock, or None. A lock left behind by a run that was killed (its process is gone) or that is older than the limit is not valid."""
    try:
        pid = int(LOCK.read_text().split()[0])
        age = time.time() - LOCK.stat().st_mtime
    except (OSError, ValueError, IndexError):
        return None
    return pid if age < LOCK_MAX_AGE_S and pid_alive(pid) else None


def acquire_lock() -> bool:
    LOCK.parent.mkdir(parents=True, exist_ok=True)
    holder = lock_holder()
    if holder is not None and holder != os.getpid():
        return False
    if LOCK.exists() and holder is None:
        log.warning("removing a stale lock left by a run that did not finish (%s)", LOCK.read_text().strip()[:40])
    LOCK.write_text(str(os.getpid()))
    return True


def last_json(text: str) -> dict | None:
    """The JSON object printed at the end of a stage's output."""
    i = text.rfind("\n{")
    i = 0 if i < 0 and text.lstrip().startswith("{") else i + 1
    try:
        return json.loads(text[i:])
    except ValueError:
        return None


def store_path() -> Path:
    sys.path.insert(0, str(ROOT))
    from oceanmind_preprocess.config import _read_yaml
    cfg = _read_yaml((ROOT / CONFIG).resolve())
    p = Path(cfg["environment_provider"].get("source", {}).get("store", "data/pacific_oisst/sst.zarr"))
    out = Path(cfg["paths"]["out_dir"])
    return (p if p.is_absolute() else ROOT / p), (out if out.is_absolute() else ROOT / out)


def run(force: bool = False) -> dict:
    store, processed = store_path()
    from oceanmind_environment import publish
    if publish.recover(processed):
        log.warning("restored the previous dataset generation after an interrupted publication")
    before = check_consistency(processed, store)
    previous = before["products"].get("processed_cubes") or before["latest"]          # the day the processed dataset (what the application shows) ends on
    write_status(ROOT, outcome="running", message="A refresh is running; the published dataset is unchanged until it finishes.", latest_observation=previous, processed_latest=previous,
                 forecast_dates=before["forecast_dates"], consistent=before["consistent"], problems=before["problems"])           # an unfinished run (killed, machine asleep) then shows as interrupted, never as a success
    sync = stage("-m", "oceanmind_environment", "sync", "--config", CONFIG, capture=True)
    report = last_json(sync.stdout or "") if sync.returncode == 0 else None
    if sync.returncode != 0 or report is None:
        why = ((sync.stderr or "").strip().splitlines() or ["the NOAA sources could not be reached"])[-1][:300]
        log.error("sync failed; the previous valid dataset (latest %s) is kept: %s", previous, why)
        lag = lag_status(previous) if previous else {}
        return write_status(ROOT, outcome="source_unavailable", message=f"NOAA could not be reached or returned unusable data; the previous valid dataset is kept. {why}",
                            latest_observation=previous, processed_latest=previous, source_latest=None, expected_latest=str(expected_latest().date()), **{k: lag.get(k) for k in ("behind_expected", "status")},
                            forecast_dates=before["forecast_dates"], consistent=before["consistent"])
    latest = report.get("latest")
    newer = latest is not None and (previous is None or latest > previous or not before["consistent"])      # a newer day, or products that disagree: rebuild
    log.info("newest valid observation %s (expected %s, behind expected %s day(s)); processed data end %s", latest, report.get("expected"), report.get("behind_expected"), previous)
    if not (newer or force):
        after = check_consistency(processed, store)
        msg = ("No newer observation is available yet: the dataset keeps its latest day " + str(latest)
               + (f" (expected {report.get('expected')}); it will be tried again at the next run." if report.get("behind_expected") else "."))
        return write_status(ROOT, outcome="unchanged", message=msg, latest_observation=previous, processed_latest=previous, source_latest=latest, expected_latest=report.get("expected"), behind_expected=report.get("behind_expected"),
                            status=report.get("status"), forecast_dates=after["forecast_dates"], consistent=after["consistent"], problems=after["problems"])
    # `build` builds the dataset, the forecast and the marine heatwaves in a staging directory and publishes them together (see refresh_pacific.staged_build)
    steps = [("scripts/refresh_pacific.py", "--only", "climate"), ("scripts/refresh_pacific.py", "--only", "build"), ("scripts/refresh_pacific.py", "--only", "alerts")]
    for s in steps:
        r = stage(*s)
        if r.returncode != 0 and s[2] != "climate":                                  # the indices are optional context; everything else is required
            live = check_consistency(processed, None)                                   # what users see: the generation that was published before this run
            return write_status(ROOT, outcome="failed", message=f"Stage '{s[2]}' failed (see logs/daily_refresh.log); the published dataset in place has observations to {live['latest']}.",
                                latest_observation=live["latest"], processed_latest=live["latest"], source_latest=latest, expected_latest=report.get("expected"), forecast_dates=live["forecast_dates"],
                                consistent=live["consistent"], problems=live["problems"])
    after = check_consistency(processed, store)
    if not after["consistent"]:
        log.error("products refer to different days: %s", after["problems"])
    return write_status(ROOT, outcome="updated", message=f"Observations now end {after['latest']}; the forecast covers {after['forecast_dates'][0]} to {after['forecast_dates'][-1]}.",
                        latest_observation=after["latest"], processed_latest=after["products"].get("processed_cubes"), source_latest=latest, expected_latest=report.get("expected"),
                        behind_expected=report.get("behind_expected"), status=report.get("status"), forecast_dates=after["forecast_dates"], consistent=after["consistent"], problems=after["problems"], previous_latest=previous)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--force", action="store_true", help="rebuild even when no newer observation exists")
    args = ap.parse_args()
    (ROOT / "logs").mkdir(exist_ok=True)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s", handlers=[logging.FileHandler(ROOT / "logs" / "daily_refresh.log", encoding="utf-8"), logging.StreamHandler()])
    if not acquire_lock():
        log.warning("another refresh is running (lock %s); nothing done", LOCK)
        return 0
    for name in ("SIGTERM", "SIGBREAK"):                                           # a stopped task is reported, and the lock is released by the finally below
        if hasattr(signal, name):
            signal.signal(getattr(signal, name), lambda *_: (_ for _ in ()).throw(KeyboardInterrupt()))
    try:
        try:
            status = run(args.force)
        except KeyboardInterrupt:
            store, processed = store_path()
            now = check_consistency(processed, store)
            status = write_status(ROOT, outcome="failed", message="The refresh was interrupted before it finished; the previously published dataset is still in place and the next run starts again.",
                                  latest_observation=now["latest"], processed_latest=now["products"].get("processed_cubes"), forecast_dates=now["forecast_dates"], consistent=now["consistent"], problems=now["problems"])
        log.info("result: %s", json.dumps(status))
        return 0 if status["outcome"] != "failed" else 1
    finally:
        LOCK.unlink(missing_ok=True)


if __name__ == "__main__":
    raise SystemExit(main())
