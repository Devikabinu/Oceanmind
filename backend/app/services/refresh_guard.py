"""Lets the daily refresh rewrite the processed cubes while the API is running.

On Windows a file that is memory-mapped cannot be overwritten, and the API keeps the processed cubes mapped. The preprocessing build therefore writes a marker file
(`data/dataset_rebuild.lock`) around the step that rewrites the cubes. While the marker exists the API lets go of every mapped file and answers dataset requests with
"being refreshed" (a minute or two); when it disappears the next request opens the new dataset."""
from __future__ import annotations

import gc
import logging
import threading
import time
from pathlib import Path

log = logging.getLogger("ocean_platform")
MARKER_MAX_AGE_S = 3 * 3600          # a marker left behind by a crashed build stops counting after this long
_started = False


def marker_file() -> Path:
    return Path(__file__).resolve().parents[3] / "data" / "dataset_rebuild.lock"


def rebuilding() -> bool:
    f = marker_file()
    try:
        return time.time() - f.stat().st_mtime < MARKER_MAX_AGE_S
    except OSError:
        return False


def release_all() -> None:
    """Drop every cached dataset object so that no cube stays mapped."""
    from app.services import environment_store as es, forecast_store, risk_service, sst_history
    es.clear_cache()
    sst_history._cache.clear()
    risk_service._inputs_cache.clear()
    forecast_store._read.cache_clear()
    gc.collect()


def _watch(interval: float) -> None:
    was = False
    while True:
        now = rebuilding()
        if now and not was:
            log.warning("dataset rebuild in progress: releasing the processed cubes")
            release_all()
        if was and not now:
            log.warning("dataset rebuild finished: the new dataset is served from the next request")
            release_all()
        was = now
        time.sleep(interval)


def start_watcher(interval: float = 2.0) -> None:
    global _started
    if _started:
        return
    _started = True
    threading.Thread(target=_watch, args=(interval,), daemon=True, name="refresh-guard").start()
